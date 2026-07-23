from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import APIRouter, Query

from packages.agents.models import MarketRegime
from packages.governance.models import IntentSide, TradeIntent
from packages.risk.governor import deterministic_risk_governor
from packages.risk.models import PortfolioRiskSnapshot, PortfolioSnapshotSource
from packages.risk.policy import default_risk_policy
from packages.risk.state_machine import risk_state_machine

router = APIRouter(tags=["Risk Governor"])


@router.get("/risk/state")
async def get_risk_state() -> Dict[str, Any]:
    return {
        "current_state": risk_state_machine.state.value,
        "policy_version": default_risk_policy.version,
        "live_trading_enabled": default_risk_policy.live_trading_enabled,
        "leverage_enabled": default_risk_policy.leverage_enabled,
        "evaluated_at": datetime.now(timezone.utc).isoformat()
    }


@router.get("/risk/approved-orders")
async def list_approved_orders(symbol: str = Query("BTC/USDT")) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    intent = TradeIntent(
        symbol=symbol,
        exchange="binance",
        side=IntentSide.BUY,
        status="PENDING_RISK_REVIEW",
        strategy_ids=["trend_agent_v1"],
        source_signal_ids=[uuid4()],
        critic_decision_ids=[uuid4()],
        consensus_id=uuid4(),
        market_regime=MarketRegime.TREND_UP,
        expected_return_bps=Decimal("50.0"),
        weighted_confidence=Decimal("0.80"),
        estimated_fee_bps=Decimal("10.0"),
        estimated_spread_bps=Decimal("2.0"),
        estimated_slippage_bps=Decimal("5.0"),
        uncertainty_buffer_bps=Decimal("5.0"),
        net_edge_bps=Decimal("18.0"),
        reference_price=Decimal("65000.00"),
        suggested_stop_price=Decimal("63700.00"),
        horizon_minutes=60,
        feature_as_of_time=now,
        generated_at=now,
        expires_at=now + (datetime.resolution * 3600)
    )

    snapshot = PortfolioRiskSnapshot(
        account_id="ACC_MEMBER_1",
        nav=Decimal("100000.00"),
        cash_balance=Decimal("100000.00"),
        available_cash=Decimal("100000.00"),
        gross_exposure=Decimal("0.0"),
        net_exposure=Decimal("0.0"),
        open_risk_amount=Decimal("0.0"),
        realized_pnl_today=Decimal("0.0"),
        realized_pnl_week=Decimal("0.0"),
        equity_peak=Decimal("100000.00"),
        current_drawdown_pct=Decimal("0.0"),
        data_as_of=now,
        source=PortfolioSnapshotSource.STATIC_TEST
    )

    decision, approved_order = deterministic_risk_governor.evaluate_intent(intent, snapshot, default_risk_policy, now)

    if approved_order:
        return [approved_order.model_dump(mode="json")]
    return []
