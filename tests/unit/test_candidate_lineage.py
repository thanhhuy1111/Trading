"""Candidate lineage: Market candle -> FeatureSnapshot -> AgentSignal -> Candidate -> Trade
Result -> meta_label must survive every stage, with real agent attribution (no fabrication)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.backtest.datasets import dataset_registry
from packages.backtest.engine import EventDrivenBacktestEngine
from packages.backtest.models import BacktestConfig, BacktestMode
from packages.candidates.builder import build_proposed_candidate
from packages.candidates.models import CandidateStatus
from packages.market_data.models import Candle, Timeframe
from packages.risk.models import RiskState
from packages.risk.state_machine import risk_state_machine


def _rising_then_falling_candles(t0: datetime) -> list:
    candles = []
    price = Decimal("50000")
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
    return candles


def test_build_proposed_candidate_returns_none_without_trade_intent() -> None:
    from dataclasses import dataclass

    @dataclass
    class _FakeDecision:
        trade_intent = None

    result = build_proposed_candidate(
        _FakeDecision(), session_id=None, strategy_name="x", strategy_version="1.0.0"
    )
    assert result is None


def test_candidate_lineage_survives_full_round_trip() -> None:
    risk_state_machine.state = RiskState.NORMAL
    t0 = datetime(2026, 3, 1, tzinfo=timezone.utc)
    candles = _rising_then_falling_candles(t0)

    ds = dataset_registry.register_dataset("CANDIDATE_LINEAGE_DS", ["BTC/USDT"], ["1h"], candles)
    cfg = BacktestConfig(
        session_name="baseline", mode=BacktestMode.HISTORICAL_REPLAY, dataset_id=ds.dataset_id,
        symbols=["BTC/USDT"], timeframes=["1h"], start_time=t0, end_time=t0 + timedelta(hours=59),
        warmup_start_time=t0, initial_cash=Decimal("100000.00"), random_seed=42, fold_number=2,
    )
    engine = EventDrivenBacktestEngine()
    sess = engine.create_session(cfg)
    report = engine.run_backtest(sess.session_id)
    candidates = engine.get_candidates(sess.session_id)

    assert report.trade_count >= 1
    closed = [c for c in candidates if c.status == CandidateStatus.CLOSED]
    # Every completed trade episode has exactly one matching closed candidate.
    assert len(closed) == report.trade_count

    for c in closed:
        # Lineage identity: candidate ties back to this exact session/strategy/config.
        assert c.session_id == sess.session_id
        assert c.symbol == "BTC/USDT"
        assert c.strategy_name == "baseline"
        assert c.strategy_config_hash == cfg.strategy_config.config_hash
        assert c.fold_number == 2
        # Agent attribution: the dominant agent must be one of the three real agents, and it
        # must be a subset consistent with supporting/opposing partition (no double-counting).
        assert c.agent_source in {"trend_agent_v1", "reversion_agent_v1", "breakout_agent_v1"}
        assert c.agent_source in c.supporting_agents
        assert set(c.supporting_agents).isdisjoint(set(c.opposing_agents))
        assert len(c.supporting_agents) + len(c.opposing_agents) == 3
        # Regime/feature lineage: must be real values, not placeholders.
        assert c.market_regime != ""
        assert c.feature_snapshot  # non-empty — real computed features, not fabricated
        # Outcome lineage: meta_label must exactly match the sign convention (Phase 8 target).
        assert c.net_return_bps is not None
        expected_label = "ACCEPT" if c.net_return_bps > Decimal("0") else "REJECT"
        assert c.meta_label == expected_label
        assert c.exit_reason in {"INITIAL_STOP", "TAKE_PROFIT", "TRAILING_STOP", "MANUAL"}
        assert c.exit_timestamp is not None and c.exit_timestamp > c.decision_timestamp

    # No candidate is silently dropped: PROPOSED always resolves to a terminal status.
    for c in candidates:
        assert c.status != CandidateStatus.PROPOSED
