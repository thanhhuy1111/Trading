"""Offline tests for the append-only derivatives history cache -- all use `tmp_path` as
`cache_dir`, no monkeypatching of module constants, no real filesystem writes outside pytest's
own temp dir."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from packages.market_data.derivatives_history import RETENTION_DAYS, append_snapshot, load_history
from packages.market_data.derivatives_models import DerivativesSnapshot
from packages.market_data.models import DataQualityStatus

SYMBOL = "BTC/USDT"
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _snapshot(ts: datetime, funding_rate: str = "0.0001") -> DerivativesSnapshot:
    return DerivativesSnapshot(
        exchange="binance_usdm_futures",
        symbol=SYMBOL,
        exchange_timestamp=ts,
        data_quality_status=DataQualityStatus.HEALTHY,
        funding_rate=Decimal(funding_rate),
    )


def test_append_then_load_round_trips(tmp_path: Path) -> None:
    snap = _snapshot(BASE_TIME)
    assert append_snapshot(snap, cache_dir=tmp_path) is True

    history = load_history(SYMBOL, as_of=BASE_TIME + timedelta(hours=1), cache_dir=tmp_path)
    assert len(history) == 1
    assert history[0].funding_rate == Decimal("0.0001")


def test_append_skips_near_duplicate_within_min_interval(tmp_path: Path) -> None:
    first = _snapshot(BASE_TIME)
    assert append_snapshot(first, cache_dir=tmp_path) is True

    too_soon = _snapshot(BASE_TIME + timedelta(minutes=1))
    assert append_snapshot(too_soon, cache_dir=tmp_path) is False

    history = load_history(SYMBOL, as_of=BASE_TIME + timedelta(hours=1), cache_dir=tmp_path)
    assert len(history) == 1  # the near-duplicate was never persisted


def test_append_accepts_entry_past_min_interval(tmp_path: Path) -> None:
    first = _snapshot(BASE_TIME)
    append_snapshot(first, cache_dir=tmp_path)

    later = _snapshot(BASE_TIME + timedelta(minutes=5))
    assert append_snapshot(later, cache_dir=tmp_path) is True

    history = load_history(SYMBOL, as_of=BASE_TIME + timedelta(hours=1), cache_dir=tmp_path)
    assert len(history) == 2


def test_append_trims_entries_older_than_retention(tmp_path: Path) -> None:
    stale = _snapshot(BASE_TIME)
    append_snapshot(stale, cache_dir=tmp_path)

    fresh = _snapshot(BASE_TIME + timedelta(days=RETENTION_DAYS + 1))
    append_snapshot(fresh, cache_dir=tmp_path)

    history = load_history(SYMBOL, as_of=fresh.exchange_timestamp + timedelta(hours=1), cache_dir=tmp_path)
    assert len(history) == 1
    assert history[0].exchange_timestamp == fresh.exchange_timestamp


def test_load_history_never_leaks_snapshots_after_as_of(tmp_path: Path) -> None:
    past = _snapshot(BASE_TIME)
    append_snapshot(past, cache_dir=tmp_path)
    future = _snapshot(BASE_TIME + timedelta(minutes=10))
    append_snapshot(future, cache_dir=tmp_path)

    history = load_history(SYMBOL, as_of=BASE_TIME + timedelta(minutes=1), cache_dir=tmp_path)
    assert len(history) == 1
    assert history[0].exchange_timestamp == BASE_TIME


def test_load_history_respects_lookback_window(tmp_path: Path) -> None:
    old = _snapshot(BASE_TIME)
    append_snapshot(old, cache_dir=tmp_path)
    recent = _snapshot(BASE_TIME + timedelta(hours=2))
    append_snapshot(recent, cache_dir=tmp_path)

    as_of = BASE_TIME + timedelta(hours=3)
    history = load_history(SYMBOL, as_of=as_of, lookback=timedelta(hours=1), cache_dir=tmp_path)
    assert len(history) == 1
    assert history[0].exchange_timestamp == recent.exchange_timestamp


def test_load_history_empty_when_no_cache_file(tmp_path: Path) -> None:
    assert load_history(SYMBOL, as_of=BASE_TIME, cache_dir=tmp_path) == []
