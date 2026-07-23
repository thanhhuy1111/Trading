from datetime import datetime, timezone
from decimal import Decimal
from typing import List
from uuid import UUID

from pydantic import BaseModel, Field


class RiskLimits(BaseModel):
    """System risk limit parameters."""
    max_risk_per_trade_pct: float = 0.0025    # 0.25% NAV
    max_open_risk_pct: float = 0.015         # 1.5% NAV
    max_daily_loss_pct: float = 0.015        # 1.5% NAV
    max_weekly_loss_pct: float = 0.04        # 4.0% NAV
    warning_drawdown_pct: float = 0.05       # 5.0% NAV
    hard_stop_drawdown_pct: float = 0.08     # 8.0% NAV
    max_allocation_per_asset_pct: float = 0.20 # 20.0% NAV
    max_correlated_exposure_pct: float = 0.40  # 40.0% NAV
    max_leverage: float = 1.0                # No leverage in Spot MVP


class RiskDecision(BaseModel):
    """Evaluation result generated deterministically by Risk Governor."""
    intent_id: UUID
    approved: bool
    approved_quantity: Decimal = Decimal("0")
    approved_notional: Decimal = Decimal("0")
    risk_amount: Decimal = Decimal("0")
    risk_percentage: float = 0.0
    rejection_codes: List[str] = Field(default_factory=list)
    risk_policy_version: str = "1.0.0"
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
