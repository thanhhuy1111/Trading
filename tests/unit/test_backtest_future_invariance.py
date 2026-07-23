from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.backtest.datasets import dataset_registry
from packages.backtest.engine import EventDrivenBacktestEngine
from packages.backtest.models import BacktestConfig, BacktestMode
from packages.market_data.models import Candle


def test_future_data_invariance_up_to_time_t() -> None:
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

    # Base dataset up to T (10 candles)
    candles_t = [
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
        for i in range(10)
    ]

    # Extended dataset up to T+N (15 candles)
    candles_tn = candles_t + [
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
        for i in range(10, 15)
    ]

    ds_t = dataset_registry.register_dataset("DS_T", ["BTC/USDT"], ["1h"], candles_t)
    ds_tn = dataset_registry.register_dataset("DS_TN", ["BTC/USDT"], ["1h"], candles_tn)

    t_end = t0 + timedelta(hours=9, minutes=59)

    # Run A: evaluated up to T
    config_a = BacktestConfig(
        session_name="RUN_A",
        mode=BacktestMode.HISTORICAL_REPLAY,
        dataset_id=ds_t.dataset_id,
        symbols=["BTC/USDT"],
        timeframes=["1h"],
        start_time=t0,
        end_time=t_end,
        warmup_start_time=t0,
        initial_cash=Decimal("10000.00"),
        random_seed=42
    )

    # Run B: evaluated up to T using extended dataset
    config_b = BacktestConfig(
        session_name="RUN_B",
        mode=BacktestMode.HISTORICAL_REPLAY,
        dataset_id=ds_tn.dataset_id,
        symbols=["BTC/USDT"],
        timeframes=["1h"],
        start_time=t0,
        end_time=t_end,
        warmup_start_time=t0,
        initial_cash=Decimal("10000.00"),
        random_seed=42
    )

    engine_a = EventDrivenBacktestEngine()
    engine_b = EventDrivenBacktestEngine()

    sess_a = engine_a.create_session(config_a)
    report_a = engine_a.run_backtest(sess_a.session_id)

    sess_b = engine_b.create_session(config_b)
    report_b = engine_b.run_backtest(sess_b.session_id)

    # Assert state at T is 100% identical regardless of T+1..T+N existing in dataset registry
    assert report_a.metrics.final_nav == report_b.metrics.final_nav
    assert report_a.metrics.total_trades == report_b.metrics.total_trades
    assert report_a.trade_count == report_b.trade_count
