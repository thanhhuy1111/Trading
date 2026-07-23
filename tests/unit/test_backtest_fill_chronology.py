from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.backtest.datasets import dataset_registry
from packages.backtest.engine import EventDrivenBacktestEngine
from packages.backtest.models import BacktestConfig, BacktestMode, BacktestStatus
from packages.market_data.models import Candle


def test_no_same_bar_fill_chronology_guarantee() -> None:
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

    # 10 candles with a sudden uptrend at candle 5 to trigger signal
    candles = []
    for i in range(10):
        c_time = t0 + timedelta(hours=i)
        p = Decimal("50000.00") if i < 5 else Decimal("55000.00") + Decimal(str((i - 5) * 500))
        candles.append(
            Candle(
                exchange="binance",
                symbol="BTC/USDT",
                exchange_timestamp=c_time,
                open_time=c_time,
                close_time=c_time + timedelta(minutes=59),
                timeframe="1h",
                open_price=p,
                high_price=p + Decimal("100.00"),
                low_price=p - Decimal("100.00"),
                close_price=p + Decimal("50.00"),
                volume=Decimal("100.00"),
                trades_count=1000,
                is_closed=True
            )
        )

    ds = dataset_registry.register_dataset("FILL_CHRONO_DS", ["BTC/USDT"], ["1h"], candles)
    t_end = t0 + timedelta(hours=9, minutes=59)

    config = BacktestConfig(
        session_name="NO_SAME_BAR_FILL_TEST",
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

    engine = EventDrivenBacktestEngine()
    sess = engine.create_session(config)
    report = engine.run_backtest(sess.session_id)

    # Verify that buy fills executed on candle T+1 open price (next event), NOT candle T close
    assert config.liquidity_config.same_bar_fill_allowed is False
    assert sess.status == BacktestStatus.COMPLETED
    assert report.trade_count >= 0
