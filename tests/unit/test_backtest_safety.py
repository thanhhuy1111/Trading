from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from packages.backtest.clock import ReplayClock
from packages.backtest.datasets import DatasetRegistry
from packages.backtest.models import BacktestConfig, BacktestMode
from packages.backtest.reproducibility import ReproducibilityVerifier
from packages.backtest.walk_forward import WalkForwardRunner
from packages.common.config import settings
from packages.market_data.models import Candle


def test_dataset_registration_checksum_and_quality_gate() -> None:
    registry = DatasetRegistry()
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles = [
        Candle(
            exchange="binance",
            symbol="BTC/USDT",
            exchange_timestamp=t0 + timedelta(hours=i),
            open_time=t0 + timedelta(hours=i),
            close_time=t0 + timedelta(hours=i, minutes=59),
            timeframe="1h",
            open_price=Decimal("50000.00"),
            high_price=Decimal("51000.00"),
            low_price=Decimal("49500.00"),
            close_price=Decimal("50500.00"),
            volume=Decimal("100.00"),
            trades_count=1000,
            is_closed=True
        )
        for i in range(10)
    ]

    ds = registry.register_dataset(
        name="BTC_TEST_DATASET",
        symbols=["BTC/USDT"],
        timeframes=["1h"],
        candles=candles
    )

    assert ds.candle_count == 10
    assert len(ds.checksum) == 64
    assert ds.quality_status == "VALIDATED"


def test_replay_clock_monotonic_and_no_wall_clock() -> None:
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    clock = ReplayClock(t0)

    assert clock.now() == t0

    t1 = t0 + timedelta(hours=1)
    clock.advance_to(t1)
    assert clock.now() == t1

    # Regressing time must raise ValueError
    with pytest.raises(ValueError, match="REPLAY_CLOCK_TIME_REGRESSION"):
        clock.advance_to(t0)


def test_walk_forward_fold_isolation_purge_and_embargo() -> None:
    runner = WalkForwardRunner()
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)

    folds = runner.generate_folds(
        session_id=uuid4(),
        start_time=start,
        end_time=end,
        num_folds=3,
        purge_hours=12,
        embargo_hours=12
    )

    assert len(folds) == 3
    for fold in folds:
        assert fold.train_end < fold.validation_start
        assert fold.validation_end < fold.test_start


def test_reproducibility_fingerprint_matching() -> None:
    verifier = ReproducibilityVerifier()
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)

    config = BacktestConfig(
        session_name="FINGERPRINT_TEST",
        mode=BacktestMode.HISTORICAL_REPLAY,
        dataset_id=uuid4(),
        symbols=["BTC/USDT"],
        timeframes=["1h"],
        start_time=t0,
        end_time=t1,
        warmup_start_time=t0,
        random_seed=42
    )

    fp1 = verifier.compute_fingerprint("DUMMY_CHECKSUM_AAA", config)
    fp2 = verifier.compute_fingerprint("DUMMY_CHECKSUM_AAA", config)
    fp_diff = verifier.compute_fingerprint("DUMMY_CHECKSUM_BBB", config)

    assert fp1 == fp2
    assert fp1 != fp_diff
    assert verifier.verify_reproducibility(fp1, fp2) is True


def test_backtest_safety_no_live_trading_or_private_apis() -> None:
    assert settings.LIVE_TRADING_ENABLED is False
    assert settings.SYSTEM_MODE in ["SIMULATION", "MINIMAL", "PAPER_TRADING", "DEVELOPMENT", "TEST"]
