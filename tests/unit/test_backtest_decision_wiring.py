"""F-01 (backtest): backtest uses the SAME DecisionService as paper (no fabrication)."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from packages.backtest.datasets import dataset_registry
from packages.backtest.engine import EventDrivenBacktestEngine
from packages.backtest.models import BacktestConfig, BacktestMode, BacktestStatus
from packages.governance.decision_service import decision_service
from packages.market_data.models import Candle, Timeframe
from packages.risk.models import RiskState
from packages.risk.state_machine import risk_state_machine

_ROOT = Path(__file__).resolve().parents[2]


def test_backtest_engine_source_uses_decision_service_no_fabrication() -> None:
    src = (_ROOT / "packages/backtest/engine.py").read_text(encoding="utf-8")
    assert "decision_service.decide(" in src
    assert 'weighted_confidence=Decimal("0.85")' not in src
    assert 'net_edge_bps=Decimal("120' not in src
    assert 'close[idx' not in src and "prev_close" not in src  # inline momentum rule removed


def test_decision_service_is_deterministic_for_same_inputs() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    price = Decimal("50000")
    candles = []
    for i in range(40):
        ct = t0 + timedelta(hours=i)
        step = price * Decimal("0.005")
        candles.append(Candle(
            exchange="binance", symbol="BTC/USDT", exchange_timestamp=ct, open_time=ct,
            close_time=ct + timedelta(minutes=59), timeframe=Timeframe.H1, open_price=price,
            high_price=price + step + Decimal("10"), low_price=price - Decimal("10"),
            close_price=price + step, volume=Decimal("100"), trades_count=100, is_closed=True,
        ))
        price += step
    last = candles[-1]

    async def run():
        return await decision_service.decide(
            exchange="binance", symbol="BTC/USDT", timeframe=Timeframe.H1,
            candles=candles, as_of_time=last.close_time, reference_price=last.close_price,
        )

    r1 = asyncio.run(run())
    r2 = asyncio.run(run())
    # Same business decision regardless of run (UUIDs differ, fingerprint/direction do not)
    assert r1.allocation.decision_fingerprint == r2.allocation.decision_fingerprint
    assert r1.consensus.direction == r2.consensus.direction
    assert r1.strategy_config_hash == r2.strategy_config_hash


def test_backtest_actually_trades_through_pipeline() -> None:
    risk_state_machine.state = RiskState.NORMAL
    t0 = datetime(2026, 3, 1, tzinfo=timezone.utc)
    candles = []
    price = Decimal("50000")
    # 40 rising bars (warm up + trigger a LONG entry) then 20 falling bars (trigger a stop exit)
    for i in range(60):
        ct = t0 + timedelta(hours=i)
        if i < 40:
            nxt = price * Decimal("1.005")
            hi, lo = nxt + Decimal("20"), price - Decimal("20")
        else:
            nxt = price * Decimal("0.97")
            hi, lo = price + Decimal("20"), nxt - Decimal("20")
        candles.append(Candle(
            exchange="binance", symbol="BTC/USDT", exchange_timestamp=ct, open_time=ct,
            close_time=ct + timedelta(minutes=59), timeframe=Timeframe.H1, open_price=price,
            high_price=hi, low_price=lo, close_price=nxt, volume=Decimal("100"),
            trades_count=100, is_closed=True,
        ))
        price = nxt

    ds = dataset_registry.register_dataset("BT_TRADE_DS", ["BTC/USDT"], ["1h"], candles)
    cfg = BacktestConfig(
        session_name="BT_TRADE", mode=BacktestMode.HISTORICAL_REPLAY, dataset_id=ds.dataset_id,
        symbols=["BTC/USDT"], timeframes=["1h"], start_time=t0, end_time=t0 + timedelta(hours=59),
        warmup_start_time=t0, initial_cash=Decimal("100000.00"), random_seed=42,
    )
    engine = EventDrivenBacktestEngine()
    sess = engine.create_session(cfg)
    report = engine.run_backtest(sess.session_id)

    assert sess.status == BacktestStatus.COMPLETED
    # A full round-trip (entry via DecisionService LONG + stop exit) was recorded
    assert report.trade_count >= 1
