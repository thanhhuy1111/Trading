from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.backtest.datasets import dataset_registry
from packages.backtest.engine import EventDrivenBacktestEngine
from packages.backtest.models import BacktestConfig, BacktestMode
from packages.market_data.models import Candle


def test_checkpoint_and_resume_state_equivalence() -> None:
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
        for i in range(16)
    ]

    ds = dataset_registry.register_dataset("CHECKPOINT_DS", ["BTC/USDT"], ["1h"], candles)
    t_end = t0 + timedelta(hours=15, minutes=59)

    # 1. Full continuous run
    config_continuous = BacktestConfig(
        session_name="CONTINUOUS_RUN",
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
    sess1 = engine1.create_session(config_continuous)
    report1 = engine1.run_backtest(sess1.session_id)

    # 2. Segmented run (Part 1: t0 to t8, Part 2: t8 to t15)
    t_mid = t0 + timedelta(hours=7, minutes=59)
    config_part1 = BacktestConfig(
        session_name="PART_1",
        mode=BacktestMode.HISTORICAL_REPLAY,
        dataset_id=ds.dataset_id,
        symbols=["BTC/USDT"],
        timeframes=["1h"],
        start_time=t0,
        end_time=t_mid,
        warmup_start_time=t0,
        initial_cash=Decimal("10000.00"),
        random_seed=42
    )

    engine_part1 = EventDrivenBacktestEngine()
    sess_part1 = engine_part1.create_session(config_part1)
    report_part1 = engine_part1.run_backtest(sess_part1.session_id)

    # Part 2 resumes from checkpoint NAV
    config_part2 = BacktestConfig(
        session_name="PART_2",
        mode=BacktestMode.HISTORICAL_REPLAY,
        dataset_id=ds.dataset_id,
        symbols=["BTC/USDT"],
        timeframes=["1h"],
        start_time=t0 + timedelta(hours=8),
        end_time=t_end,
        warmup_start_time=t0,
        initial_cash=report_part1.metrics.final_nav,
        random_seed=42
    )

    engine_part2 = EventDrivenBacktestEngine()
    sess_part2 = engine_part2.create_session(config_part2)
    report_part2 = engine_part2.run_backtest(sess_part2.session_id)

    # Final NAV of Part 2 must equal continuous run final NAV
    assert report_part2.metrics.final_nav == report1.metrics.final_nav
