from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.backtest.datasets import dataset_registry
from packages.backtest.engine import EventDrivenBacktestEngine
from packages.backtest.models import BacktestConfig, BacktestMode
from packages.backtest.reproducibility import ReproducibilityVerifier
from packages.market_data.models import Candle


def test_reproducibility_full_state_equivalence() -> None:
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles = [
        Candle(
            exchange="binance",
            symbol="BTC/USDT",
            exchange_timestamp=t0 + timedelta(hours=i),
            open_time=t0 + timedelta(hours=i),
            close_time=t0 + timedelta(hours=i, minutes=59),
            timeframe="1h",
            open_price=Decimal("50000.00") + Decimal(str(i * 100)),
            high_price=Decimal("51000.00") + Decimal(str(i * 100)),
            low_price=Decimal("49500.00") + Decimal(str(i * 100)),
            close_price=Decimal("50500.00") + Decimal(str(i * 100)),
            volume=Decimal("100.00"),
            trades_count=1000,
            is_closed=True
        )
        for i in range(20)
    ]

    ds = dataset_registry.register_dataset(
        name="REPRODUCIBILITY_TEST_DATASET",
        symbols=["BTC/USDT"],
        timeframes=["1h"],
        candles=candles
    )

    t_end = t0 + timedelta(hours=19, minutes=59)

    config1 = BacktestConfig(
        session_name="RUN_1",
        mode=BacktestMode.HISTORICAL_REPLAY,
        dataset_id=ds.dataset_id,
        symbols=["BTC/USDT"],
        timeframes=["1h"],
        start_time=t0,
        end_time=t_end,
        warmup_start_time=t0,
        initial_cash=Decimal("10000.00"),
        random_seed=42
    )

    config2 = BacktestConfig(
        session_name="RUN_2",
        mode=BacktestMode.HISTORICAL_REPLAY,
        dataset_id=ds.dataset_id,
        symbols=["BTC/USDT"],
        timeframes=["1h"],
        start_time=t0,
        end_time=t_end,
        warmup_start_time=t0,
        initial_cash=Decimal("10000.00"),
        random_seed=42
    )

    engine1 = EventDrivenBacktestEngine()
    engine2 = EventDrivenBacktestEngine()

    sess1 = engine1.create_session(config1)
    report1 = engine1.run_backtest(sess1.session_id)

    sess2 = engine2.create_session(config2)
    report2 = engine2.run_backtest(sess2.session_id)

    # 1. Final NAV
    assert report1.metrics.final_nav == report2.metrics.final_nav

    # 2. Total Trades & Win Rate
    assert report1.metrics.total_trades == report2.metrics.total_trades
    assert report1.metrics.win_rate == report2.metrics.win_rate

    # 3. Trade Count Equivalence
    assert report1.trade_count == report2.trade_count

    # 4. Fingerprint Equivalence
    verifier = ReproducibilityVerifier()
    fp1 = verifier.compute_fingerprint(ds.checksum, config1)
    fp2 = verifier.compute_fingerprint(ds.checksum, config2)
    assert fp1 == fp2
