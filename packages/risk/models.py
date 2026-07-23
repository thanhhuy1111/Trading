from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RiskState(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    SOFT_STOP = "SOFT_STOP"
    HARD_STOP = "HARD_STOP"
    MANUAL_HALT = "MANUAL_HALT"
    RECOVERY_PENDING = "RECOVERY_PENDING"


class RiskDecisionResult(str, Enum):
    APPROVED = "APPROVED"
    APPROVED_REDUCED = "APPROVED_REDUCED"
    REJECTED = "REJECTED"
    SOFT_STOPPED = "SOFT_STOPPED"
    HARD_STOPPED = "HARD_STOPPED"
    EXPIRED = "EXPIRED"
    INVALID_INPUT = "INVALID_INPUT"


class PortfolioSnapshotSource(str, Enum):
    STATIC_TEST = "STATIC_TEST"
    SIMULATED = "SIMULATED"
    REPOSITORY = "REPOSITORY"


class RiskCheckSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PositionRiskView(BaseModel):
    symbol: str
    side: Literal["LONG"] = "LONG"
    quantity: Decimal = Field(ge=Decimal("0.0"))
    average_entry_price: Decimal = Field(gt=Decimal("0.0"))
    current_price: Decimal = Field(gt=Decimal("0.0"))
    market_value: Decimal = Field(ge=Decimal("0.0"))
    unrealized_pnl: Decimal
    stop_price: Optional[Decimal] = None
    open_risk_amount: Decimal = Field(ge=Decimal("0.0"))
    sector_or_group: Optional[str] = None


class PendingOrderRiskView(BaseModel):
    order_id: UUID
    symbol: str
    side: Literal["BUY"] = "BUY"
    quantity: Decimal = Field(gt=Decimal("0.0"))
    price: Decimal = Field(gt=Decimal("0.0"))
    reserved_cash: Decimal = Field(ge=Decimal("0.0"))


class PortfolioRiskSnapshot(BaseModel):
    snapshot_id: UUID = Field(default_factory=uuid4)
    account_id: str
    base_currency: str = "USDT"
    nav: Decimal = Field(gt=Decimal("0.0"))
    cash_balance: Decimal = Field(ge=Decimal("0.0"))
    available_cash: Decimal = Field(ge=Decimal("0.0"))
    gross_exposure: Decimal = Field(ge=Decimal("0.0"))
    net_exposure: Decimal = Field(ge=Decimal("0.0"))
    open_risk_amount: Decimal = Field(ge=Decimal("0.0"))
    realized_pnl_today: Decimal = Decimal("0.0")
    realized_pnl_week: Decimal = Decimal("0.0")
    unrealized_pnl: Decimal = Decimal("0.0")
    equity_peak: Decimal = Field(gt=Decimal("0.0"))
    current_drawdown_pct: Decimal = Field(ge=Decimal("0.0"))
    positions: List[PositionRiskView] = Field(default_factory=list)
    pending_orders: List[PendingOrderRiskView] = Field(default_factory=list)
    data_as_of: datetime
    source: PortfolioSnapshotSource = PortfolioSnapshotSource.STATIC_TEST
    schema_version: int = 1


class RiskCheckResult(BaseModel):
    check_name: str
    passed: bool
    severity: RiskCheckSeverity
    current_value: Optional[Any] = None
    limit_value: Optional[Any] = None
    reason_codes: List[str] = Field(default_factory=list)
    explanation: List[str] = Field(default_factory=list)


class RiskDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: UUID = Field(default_factory=uuid4)
    intent_id: UUID
    account_id: str
    result: RiskDecisionResult
    risk_state: RiskState

    nav: Decimal
    base_risk_budget: Decimal
    adjusted_risk_budget: Decimal

    reference_price: Decimal
    conservative_entry_price: Decimal
    approved_stop_price: Optional[Decimal] = None

    raw_quantity: Optional[Decimal] = None
    approved_quantity: Optional[Decimal] = None
    approved_notional: Optional[Decimal] = None
    actual_risk_amount: Optional[Decimal] = None
    actual_risk_pct: Optional[Decimal] = None

    current_open_risk_pct: Decimal
    projected_open_risk_pct: Decimal
    current_total_exposure_pct: Decimal
    projected_total_exposure_pct: Decimal
    projected_symbol_allocation_pct: Decimal
    projected_correlated_exposure_pct: Decimal

    daily_loss_pct: Decimal
    weekly_loss_pct: Decimal
    drawdown_pct: Decimal

    checks: List[RiskCheckResult] = Field(default_factory=list)
    warning_codes: List[str] = Field(default_factory=list)
    rejection_codes: List[str] = Field(default_factory=list)

    portfolio_snapshot_id: UUID
    symbol_metadata_version: str = "1.0.0"
    policy_version: str = "1.0.0"
    governor_version: str = "1.0.0"
    decision_fingerprint: str

    reviewed_at: datetime
    valid_until: datetime
    schema_version: int = 1


class ApprovedOrder(BaseModel):
    model_config = ConfigDict(frozen=True)

    approved_order_id: UUID = Field(default_factory=uuid4)
    client_order_id: UUID = Field(default_factory=uuid4)
    risk_decision_id: UUID
    intent_id: UUID

    exchange: str
    symbol: str
    side: Literal["BUY"] = "BUY"

    approved_quantity: Decimal = Field(gt=Decimal("0.0"))
    maximum_notional: Decimal = Field(gt=Decimal("0.0"))
    approved_stop_price: Decimal = Field(gt=Decimal("0.0"))
    maximum_entry_price: Decimal = Field(gt=Decimal("0.0"))
    maximum_entry_slippage_bps: Decimal = Field(ge=Decimal("0.0"))

    expires_at: datetime
    risk_policy_version: str = "1.0.0"
    governor_version: str = "1.0.0"

    status: Literal["PENDING_EXECUTION"] = "PENDING_EXECUTION"
    schema_version: int = 1

    @model_validator(mode="after")
    def validate_safety_invariants(self) -> "ApprovedOrder":
        forbidden_fields = ["exchange_order_id", "fill_quantity", "fill_price", "execution_status", "api_key"]
        for f in forbidden_fields:
            if hasattr(self, f):
                raise ValueError(f"Safety Violation: ApprovedOrder must NOT contain execution/broker field '{f}'")

        if self.approved_stop_price >= self.maximum_entry_price:
            raise ValueError(
                "Safety Invariant Violation: approved_stop_price must be strictly lower than maximum_entry_price"
            )

        return self
