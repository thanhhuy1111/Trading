from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.risk.models import PositionRiskView


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HALTED = "HALTED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    DISABLED = "DISABLED"


class TradingAccount(BaseModel):
    account_id: str = "SIM_ACCOUNT_001"
    base_currency: str = "USDT"
    status: AccountStatus = AccountStatus.ACTIVE
    accounting_method: Literal["WEIGHTED_AVERAGE"] = "WEIGHTED_AVERAGE"
    created_at: datetime
    schema_version: int = 1


class LedgerEntryType(str, Enum):
    CASH_DEBIT = "CASH_DEBIT"
    CASH_CREDIT = "CASH_CREDIT"
    ASSET_DEBIT = "ASSET_DEBIT"
    ASSET_CREDIT = "ASSET_CREDIT"
    FEE_DEBIT = "FEE_DEBIT"
    REALIZED_PNL = "REALIZED_PNL"
    ADJUSTMENT = "ADJUSTMENT"


class LedgerEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry_id: UUID = Field(default_factory=uuid4)
    transaction_id: UUID
    account_id: str = "SIM_ACCOUNT_001"

    asset: str
    entry_type: LedgerEntryType
    amount: Decimal

    fill_id: Optional[UUID] = None
    position_id: Optional[UUID] = None
    reference_type: str
    reference_id: str

    effective_at: datetime
    recorded_at: datetime
    sequence_number: int

    schema_version: int = 1


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    EXIT_PENDING = "EXIT_PENDING"
    CLOSED = "CLOSED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    ERROR = "ERROR"


class Position(BaseModel):
    position_id: UUID = Field(default_factory=uuid4)
    account_id: str = "SIM_ACCOUNT_001"
    exchange: str = "binance"
    symbol: str

    side: Literal["LONG"] = "LONG"
    status: PositionStatus = PositionStatus.OPEN

    quantity: Decimal = Field(ge=Decimal("0.0"))
    available_quantity: Decimal = Field(ge=Decimal("0.0"))
    reserved_exit_quantity: Decimal = Field(ge=Decimal("0.0"))

    average_entry_price: Decimal = Field(ge=Decimal("0.0"))
    total_cost_basis: Decimal = Field(ge=Decimal("0.0"))

    realized_pnl: Decimal = Decimal("0.0")
    unrealized_pnl: Decimal = Decimal("0.0")
    total_fees: Decimal = Decimal("0.0")

    current_market_price: Optional[Decimal] = None
    market_value: Optional[Decimal] = None

    initial_stop_price: Optional[Decimal] = None
    active_stop_price: Optional[Decimal] = None
    take_profit_price: Optional[Decimal] = None
    trailing_stop_price: Optional[Decimal] = None

    opened_at: datetime
    last_fill_at: datetime
    closed_at: Optional[datetime] = None
    version: int = 1
    schema_version: int = 1

    @model_validator(mode="after")
    def validate_invariants(self) -> "Position":
        if self.available_quantity + self.reserved_exit_quantity != self.quantity:
            raise ValueError("Position Invariant Violation: available_quantity + reserved_exit_quantity != quantity")
        return self


class RealizedPnlEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    pnl_entry_id: UUID = Field(default_factory=uuid4)
    account_id: str = "SIM_ACCOUNT_001"
    position_id: UUID
    sell_fill_id: UUID

    quantity: Decimal = Field(gt=Decimal("0.0"))
    sale_proceeds: Decimal = Field(ge=Decimal("0.0"))
    released_cost_basis: Decimal = Field(ge=Decimal("0.0"))
    exit_fee: Decimal = Field(ge=Decimal("0.0"))
    realized_pnl: Decimal

    realized_at: datetime
    accounting_method: str = "WEIGHTED_AVERAGE"
    schema_version: int = 1


class ValuationQuality(str, Enum):
    HEALTHY = "HEALTHY"
    STALE = "STALE"
    DEGRADED = "DEGRADED"


class PortfolioSnapshot(BaseModel):
    snapshot_id: UUID = Field(default_factory=uuid4)
    account_id: str = "SIM_ACCOUNT_001"

    cash_balance: Decimal = Field(ge=Decimal("0.0"))
    available_cash: Decimal = Field(ge=Decimal("0.0"))

    asset_market_value: Decimal = Field(ge=Decimal("0.0"))
    nav: Decimal = Field(ge=Decimal("0.0"))

    gross_exposure: Decimal = Field(ge=Decimal("0.0"))
    net_exposure: Decimal = Field(ge=Decimal("0.0"))
    open_risk_amount: Decimal = Field(ge=Decimal("0.0"))

    realized_pnl_today: Decimal = Decimal("0.0")
    realized_pnl_week: Decimal = Decimal("0.0")
    unrealized_pnl: Decimal = Decimal("0.0")
    total_fees: Decimal = Decimal("0.0")

    equity_peak: Decimal = Field(ge=Decimal("0.0"))
    drawdown_pct: Decimal = Field(ge=Decimal("0.0"))

    positions: List[PositionRiskView] = Field(default_factory=list)

    valuation_quality: ValuationQuality = ValuationQuality.HEALTHY
    data_as_of: datetime
    generated_at: datetime
    schema_version: int = 1


class ExitTriggerType(str, Enum):
    INITIAL_STOP = "INITIAL_STOP"
    TAKE_PROFIT = "TAKE_PROFIT"
    TRAILING_STOP = "TRAILING_STOP"
    MANUAL = "MANUAL"


class PositionExitIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    exit_intent_id: UUID = Field(default_factory=uuid4)
    position_id: UUID
    account_id: str = "SIM_ACCOUNT_001"

    exchange: str = "binance"
    symbol: str
    side: Literal["SELL"] = "SELL"
    reduce_only: Literal[True] = True

    requested_quantity: Decimal = Field(gt=Decimal("0.0"))
    maximum_quantity: Decimal = Field(gt=Decimal("0.0"))

    trigger_type: ExitTriggerType
    trigger_price: Decimal = Field(gt=Decimal("0.0"))
    reference_market_price: Decimal = Field(gt=Decimal("0.0"))

    minimum_exit_price: Optional[Decimal] = None
    maximum_slippage_bps: Decimal = Decimal("10.0")

    position_version: int
    market_data_reference_id: UUID = Field(default_factory=uuid4)
    policy_version: str = "1.0.0"

    generated_at: datetime
    expires_at: datetime

    status: Literal["PENDING_RISK_REVIEW"] = "PENDING_RISK_REVIEW"
    schema_version: int = 1


class ApprovedExitOrder(BaseModel):
    model_config = ConfigDict(frozen=True)

    approved_exit_order_id: UUID = Field(default_factory=uuid4)
    client_order_id: UUID = Field(default_factory=uuid4)
    exit_intent_id: UUID
    position_id: UUID

    account_id: str = "SIM_ACCOUNT_001"
    exchange: str = "binance"
    symbol: str

    side: Literal["SELL"] = "SELL"
    reduce_only: Literal[True] = True

    approved_quantity: Decimal = Field(gt=Decimal("0.0"))
    minimum_exit_price: Optional[Decimal] = None
    maximum_slippage_bps: Decimal = Decimal("10.0")

    position_version: int

    expires_at: datetime
    policy_version: str = "1.0.0"
    governor_version: str = "1.0.0"

    status: Literal["PENDING_EXECUTION"] = "PENDING_EXECUTION"
    schema_version: int = 1
