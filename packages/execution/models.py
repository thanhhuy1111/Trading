from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExecutionMode(str, Enum):
    SIMULATION = "SIMULATION"
    PAPER = "PAPER"
    LIVE = "LIVE"


class ExchangeOrderStatus(str, Enum):
    PENDING_EXECUTION = "PENDING_EXECUTION"
    VALIDATING = "VALIDATING"
    BLOCKED = "BLOCKED"
    READY = "READY"
    SUBMISSION_PENDING = "SUBMISSION_PENDING"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    UNKNOWN = "UNKNOWN"


class SimulatorOrderType(str, Enum):
    SINGLE_MARKETABLE_LIMIT = "SINGLE_MARKETABLE_LIMIT"
    LIMIT_IOC = "LIMIT_IOC"
    LIMIT_GTC = "LIMIT_GTC"


class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class LiquidityType(str, Enum):
    MAKER = "MAKER"
    TAKER = "TAKER"


class ExecutionTactic(str, Enum):
    SINGLE_MARKETABLE_LIMIT = "SINGLE_MARKETABLE_LIMIT"
    SLICED_LIMIT = "SLICED_LIMIT"


class ExchangeOrderRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: UUID = Field(default_factory=uuid4)
    approved_order_id: UUID
    client_order_id: UUID

    exchange: str
    symbol: str
    side: Literal["BUY", "SELL"] = "BUY"
    order_type: SimulatorOrderType = SimulatorOrderType.SINGLE_MARKETABLE_LIMIT
    time_in_force: TimeInForce = TimeInForce.IOC

    quantity: Decimal = Field(gt=Decimal("0.0"))
    limit_price: Decimal = Field(gt=Decimal("0.0"))

    maximum_entry_price: Decimal = Field(gt=Decimal("0.0"))
    remaining_approved_quantity: Decimal = Field(gt=Decimal("0.0"))
    remaining_maximum_notional: Decimal = Field(gt=Decimal("0.0"))

    submitted_at: datetime
    expires_at: datetime

    execution_policy_version: str = "1.0.0"
    schema_version: int = 1

    @model_validator(mode="after")
    def validate_safety_invariants(self) -> "ExchangeOrderRequest":
        if self.limit_price > self.maximum_entry_price:
            raise ValueError("Safety Invariant Violation: limit_price cannot exceed maximum_entry_price")
        if self.quantity > self.remaining_approved_quantity:
            raise ValueError("Safety Invariant Violation: quantity cannot exceed remaining_approved_quantity")
        return self


class ExchangeOrderResponse(BaseModel):
    client_order_id: UUID
    exchange_order_id: UUID
    status: ExchangeOrderStatus
    acknowledged_at: datetime
    message: Optional[str] = None


class ExchangeOrder(BaseModel):
    exchange_order_id: UUID = Field(default_factory=uuid4)
    client_order_id: UUID
    approved_order_id: UUID

    exchange: str
    symbol: str
    side: Literal["BUY", "SELL"] = "BUY"
    order_type: SimulatorOrderType
    time_in_force: TimeInForce

    original_quantity: Decimal = Field(gt=Decimal("0.0"))
    filled_quantity: Decimal = Field(default=Decimal("0.0"), ge=Decimal("0.0"))
    remaining_quantity: Decimal = Field(ge=Decimal("0.0"))

    limit_price: Decimal = Field(gt=Decimal("0.0"))
    average_fill_price: Optional[Decimal] = None
    cumulative_quote_quantity: Decimal = Field(default=Decimal("0.0"), ge=Decimal("0.0"))
    cumulative_fee: Decimal = Field(default=Decimal("0.0"), ge=Decimal("0.0"))

    status: ExchangeOrderStatus

    submitted_at: datetime
    acknowledged_at: Optional[datetime] = None
    last_updated_at: datetime
    expires_at: datetime

    simulator_version: str = "1.0.0"
    schema_version: int = 1


class Fill(BaseModel):
    model_config = ConfigDict(frozen=True)

    fill_id: UUID = Field(default_factory=uuid4)
    exchange_fill_id: str
    exchange_order_id: UUID
    client_order_id: UUID

    symbol: str
    side: Literal["BUY", "SELL"] = "BUY"

    quantity: Decimal = Field(gt=Decimal("0.0"))
    price: Decimal = Field(gt=Decimal("0.0"))
    quote_quantity: Decimal = Field(gt=Decimal("0.0"))
    fee: Decimal = Field(ge=Decimal("0.0"))
    fee_asset: str = "USDT"

    liquidity: LiquidityType = LiquidityType.TAKER
    executed_at: datetime

    market_data_reference_id: Optional[UUID] = None
    simulator_version: str = "1.0.0"
    schema_version: int = 1


class PlannedChildOrder(BaseModel):
    child_id: UUID = Field(default_factory=uuid4)
    sequence: int
    quantity: Decimal
    limit_price: Decimal


class ExecutionPlan(BaseModel):
    plan_id: UUID = Field(default_factory=uuid4)
    approved_order_id: UUID
    client_order_id: UUID
    tactic: ExecutionTactic = ExecutionTactic.SINGLE_MARKETABLE_LIMIT
    total_approved_quantity: Decimal
    maximum_notional: Decimal
    maximum_entry_price: Decimal
    child_orders: List[PlannedChildOrder]
    created_at: datetime
    expires_at: datetime
    policy_version: str = "1.0.0"
    plan_fingerprint: str


class ExecutionReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_id: UUID = Field(default_factory=uuid4)
    approved_order_id: UUID
    client_order_id: UUID

    final_status: ExchangeOrderStatus

    approved_quantity: Decimal
    submitted_quantity: Decimal
    filled_quantity: Decimal
    unfilled_quantity: Decimal

    maximum_notional: Decimal
    executed_notional: Decimal
    total_fee: Decimal

    average_fill_price: Optional[Decimal] = None
    maximum_entry_price: Decimal

    child_order_ids: List[UUID] = Field(default_factory=list)
    fill_ids: List[UUID] = Field(default_factory=list)

    started_at: datetime
    completed_at: datetime

    execution_policy_version: str = "1.0.0"
    simulator_version: str = "1.0.0"
    report_fingerprint: str
    schema_version: int = 1
