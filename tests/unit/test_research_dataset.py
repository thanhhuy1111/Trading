"""Unit tests for packages/research: config, checksums, candle_repository, dataset_builder,
artifacts. All offline -- no network, no real Binance calls.
"""

import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from packages.market_data.models import Candle, DataQualityStatus, Timeframe
from packages.research.artifacts import ArtifactStore
from packages.research.candle_repository import candles_to_dataframe, dataframe_to_candles
from packages.research.checksums import checksum_candles, checksum_json, get_code_commit
from packages.research.config import DatasetConfig, ResearchConfig
from packages.research.dataset_builder import build_raw_candle_dataset
from packages.research.exceptions import ArtifactNotFoundError, ChecksumMismatchError, DatasetValidationError
from packages.research.models import DatasetQualityStatus, RawCandleDataset

NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=timezone.utc)


def _candle(symbol="BTCUSDT", timeframe=Timeframe.H1, open_time=None, price=Decimal("65000.00"), is_closed=True):
    open_time = open_time or (NOW - timedelta(hours=1))
    close_time = open_time + timedelta(hours=1)
    return Candle(
        exchange="binance",
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_time,
        close_time=close_time,
        open_price=price,
        high_price=price + Decimal("10"),
        low_price=price - Decimal("10"),
        close_price=price + Decimal("2"),
        volume=Decimal("100.0"),
        exchange_timestamp=close_time,
        data_quality_status=DataQualityStatus.HEALTHY,
        is_closed=is_closed,
    )


def _candle_series(n, start=None, symbol="BTCUSDT", timeframe=Timeframe.H1):
    start = start or (NOW - timedelta(hours=n + 1))
    candles = []
    price = Decimal("65000.00")
    for i in range(n):
        open_time = start + timedelta(hours=i)
        candles.append(_candle(symbol=symbol, timeframe=timeframe, open_time=open_time, price=price))
        price += Decimal("10.00")
    return candles


def _config(**overrides):
    base = dict(
        symbols=["BTCUSDT"],
        timeframes=["1h"],
        start_time=NOW - timedelta(hours=50),
        end_time=NOW,
    )
    base.update(overrides)
    return DatasetConfig(**base)


# --------------------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------------------


def test_research_config_hash_is_deterministic():
    cfg1 = ResearchConfig(name="btc_eth_v1", dataset=_config())
    cfg2 = ResearchConfig(name="btc_eth_v1", dataset=_config())
    assert cfg1.config_hash == cfg2.config_hash


def test_research_config_hash_changes_with_threshold():
    cfg1 = ResearchConfig(name="a", dataset=_config())
    cfg2 = ResearchConfig(name="a", dataset=_config())
    from packages.research.config import ApprovalGateConfig

    cfg3 = ResearchConfig(name="a", dataset=_config(), approval=ApprovalGateConfig(min_sharpe=Decimal("2.0")))
    assert cfg1.config_hash == cfg2.config_hash
    assert cfg1.config_hash != cfg3.config_hash


# --------------------------------------------------------------------------------------
# checksums
# --------------------------------------------------------------------------------------


def test_checksum_candles_matches_backtest_dataset_registry():
    from packages.backtest.datasets import dataset_registry

    candles = _candle_series(5)
    assert checksum_candles(candles) == dataset_registry.compute_dataset_checksum(candles)


def test_checksum_candles_is_order_sensitive_so_dataset_builder_sorts_first():
    """compute_dataset_checksum hashes candles in the given order (it does not sort
    internally) -- this is exactly why build_raw_candle_dataset always sorts before
    computing the checksum, so two runs over the same (possibly differently-ordered) raw
    candle list still produce the same dataset_checksum. See test_build_raw_candle_dataset
    _is_deterministic for that guarantee at the dataset_builder level.
    """
    candles = _candle_series(5)
    reversed_candles = list(reversed(candles))
    assert checksum_candles(candles) != checksum_candles(reversed_candles)
    assert checksum_candles(candles) == checksum_candles(list(candles))


def test_checksum_json_is_deterministic():
    assert checksum_json({"b": 1, "a": 2}) == checksum_json({"a": 2, "b": 1})


def test_get_code_commit_never_raises():
    sha = get_code_commit()
    assert isinstance(sha, str)
    assert len(sha) > 0


# --------------------------------------------------------------------------------------
# candle_repository dataframe round-trip
# --------------------------------------------------------------------------------------


def test_candles_to_dataframe_and_back_roundtrips_values():
    candles = _candle_series(3)
    df = candles_to_dataframe(candles)
    assert len(df) == 3
    restored = dataframe_to_candles(df)
    assert len(restored) == 3
    for original, back in zip(candles, restored, strict=True):
        assert back.open_price == original.open_price
        assert back.close_price == original.close_price
        assert back.open_time == original.open_time
        assert back.symbol == original.symbol


# --------------------------------------------------------------------------------------
# dataset_builder
# --------------------------------------------------------------------------------------


def test_build_raw_candle_dataset_happy_path():
    candles = _candle_series(30)
    config = _config()
    dataset, kept = build_raw_candle_dataset(candles, config, config_hash="cfg-hash", now=NOW)

    assert dataset.candle_count == 30
    assert dataset.quality_status == DatasetQualityStatus.VALIDATED
    assert dataset.duplicate_count == 0
    assert len(dataset.dataset_checksum) == 64  # sha256 hex
    assert kept == sorted(kept, key=lambda c: c.open_time)


def test_build_raw_candle_dataset_removes_duplicates():
    candles = _candle_series(10)
    duplicated = candles + [candles[0], candles[3]]
    config = _config()
    dataset, kept = build_raw_candle_dataset(duplicated, config, config_hash="cfg-hash", now=NOW)

    assert dataset.duplicate_count == 2
    assert dataset.candle_count == 10
    assert len(kept) == 10


def test_build_raw_candle_dataset_rejects_unsupported_symbol():
    candles = _candle_series(5) + _candle_series(3, symbol="DOGEUSDT")
    config = _config()
    dataset, kept = build_raw_candle_dataset(candles, config, config_hash="cfg-hash", now=NOW)

    assert dataset.rejected_count == 3
    assert all(c.symbol == "BTCUSDT" for c in kept)


def test_build_raw_candle_dataset_rejects_open_candles():
    candles = _candle_series(5)
    open_candle = _candle(open_time=NOW - timedelta(minutes=30), is_closed=False)
    dataset, kept = build_raw_candle_dataset(candles + [open_candle], _config(), config_hash="cfg-hash", now=NOW)

    assert dataset.rejected_count == 1
    assert all(c.is_closed for c in kept)


def test_build_raw_candle_dataset_rejects_future_close_time():
    candles = _candle_series(5)
    future_candle = _candle(open_time=NOW + timedelta(hours=1))
    dataset, kept = build_raw_candle_dataset(candles + [future_candle], _config(), config_hash="cfg-hash", now=NOW)

    assert dataset.rejected_count == 1
    assert all(c.close_time <= NOW for c in kept)


def test_build_raw_candle_dataset_rejects_invalid_ohlc_via_guardian():
    candles = _candle_series(5)
    # Bypass Candle's own pydantic OHLC validator (model_construct skips validation) to
    # prove the DataGuardian defense-in-depth check independently rejects it.
    bad = Candle.model_construct(
        exchange="binance", symbol="BTCUSDT", timeframe=Timeframe.H1,
        open_time=NOW - timedelta(hours=2), close_time=NOW - timedelta(hours=1),
        open_price=Decimal("100"), high_price=Decimal("50"), low_price=Decimal("200"),
        close_price=Decimal("100"), volume=Decimal("1.0"), quote_volume=Decimal("0"),
        trades_count=1, is_closed=True, exchange_timestamp=NOW - timedelta(hours=1),
        received_timestamp=NOW, schema_version=1, source="binance_public",
        data_quality_status=DataQualityStatus.HEALTHY,
    )
    dataset, kept = build_raw_candle_dataset(candles + [bad], _config(), config_hash="cfg-hash", now=NOW)
    assert dataset.rejected_count == 1
    assert len(kept) == 5


def test_build_raw_candle_dataset_detects_gaps():
    early = _candle_series(5, start=NOW - timedelta(hours=40))
    late = _candle_series(5, start=NOW - timedelta(hours=10))
    dataset, kept = build_raw_candle_dataset(early + late, _config(), config_hash="cfg-hash", now=NOW)

    assert dataset.quality_status == DatasetQualityStatus.DEGRADED
    assert "GAPS_DETECTED" in " ".join(dataset.quality_issues)


def test_build_raw_candle_dataset_raises_when_nothing_survives():
    candles = _candle_series(3, symbol="DOGEUSDT")
    with pytest.raises(DatasetValidationError):
        build_raw_candle_dataset(candles, _config(), config_hash="cfg-hash", now=NOW)


def test_build_raw_candle_dataset_is_deterministic():
    candles = _candle_series(20)
    d1, k1 = build_raw_candle_dataset(candles, _config(), config_hash="cfg-hash", now=NOW)
    d2, k2 = build_raw_candle_dataset(candles, _config(), config_hash="cfg-hash", now=NOW)
    assert d1.dataset_checksum == d2.dataset_checksum
    assert [c.open_time for c in k1] == [c.open_time for c in k2]


# --------------------------------------------------------------------------------------
# artifacts
# --------------------------------------------------------------------------------------


@pytest.fixture
def tmp_store():
    tmp_dir = tempfile.mkdtemp(prefix="research_artifacts_test_")
    yield ArtifactStore(root=tmp_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_artifact_store_metadata_roundtrip(tmp_store):
    candles = _candle_series(5)
    dataset, kept = build_raw_candle_dataset(candles, _config(), config_hash="cfg-hash", now=NOW)

    tmp_store.save_metadata("datasets", dataset.dataset_id, dataset)
    loaded = tmp_store.load_metadata("datasets", dataset.dataset_id, RawCandleDataset)

    assert loaded.dataset_checksum == dataset.dataset_checksum
    assert loaded.candle_count == dataset.candle_count


def test_artifact_store_dataframe_roundtrip_and_checksum(tmp_store):
    candles = _candle_series(5)
    df = candles_to_dataframe(candles)
    tmp_store.save_dataframe("datasets", "abc", df)

    loaded = tmp_store.load_dataframe("datasets", "abc")
    assert len(loaded) == 5

    checksum = tmp_store.dataframe_checksum("datasets", "abc")
    tmp_store.verify_dataframe_checksum("datasets", "abc", checksum)  # should not raise

    with pytest.raises(ChecksumMismatchError):
        tmp_store.verify_dataframe_checksum("datasets", "abc", "0" * 64)


def test_artifact_store_missing_metadata_raises(tmp_store):
    with pytest.raises(ArtifactNotFoundError):
        tmp_store.load_metadata("datasets", "does-not-exist", RawCandleDataset)


def test_artifact_store_list_ids(tmp_store):
    candles = _candle_series(3)
    dataset, _ = build_raw_candle_dataset(candles, _config(), config_hash="cfg-hash", now=NOW)
    tmp_store.save_metadata("datasets", dataset.dataset_id, dataset)
    ids = tmp_store.list_ids("datasets")
    assert dataset.dataset_id in ids
