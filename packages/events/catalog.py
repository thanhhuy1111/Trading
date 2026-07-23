from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from packages.events.registry import EventRegistry


# --- System Event Payloads ---
@EventRegistry.register("system.started", 1)
class SystemStartedPayload(BaseModel):
    environment: str
    mode: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


@EventRegistry.register("system.stopped", 1)
class SystemStoppedPayload(BaseModel):
    reason: str
    stopped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


@EventRegistry.register("system.soft_stop_requested", 1)
class SystemSoftStopRequestedPayload(BaseModel):
    requested_by: str
    reason: str


@EventRegistry.register("system.hard_stop_requested", 1)
class SystemHardStopRequestedPayload(BaseModel):
    requested_by: str
    reason: str
    kill_switch_active: bool = True


@EventRegistry.register("system.health_changed", 1)
class SystemHealthChangedPayload(BaseModel):
    previous_status: str
    new_status: str
    details: Dict[str, Any] = Field(default_factory=dict)


@EventRegistry.register("system.incident_created", 1)
class SystemIncidentCreatedPayload(BaseModel):
    incident_id: UUID
    severity: str
    service_name: str
    message: str


@EventRegistry.register("system.incident_acknowledged", 1)
class SystemIncidentAcknowledgedPayload(BaseModel):
    incident_id: UUID
    acknowledged_by: str
    acknowledged_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Configuration Event Payloads ---
@EventRegistry.register("config.created", 1)
class ConfigCreatedPayload(BaseModel):
    config_id: UUID
    namespace: str
    name: str
    version: int
    checksum: str


@EventRegistry.register("config.updated", 1)
class ConfigUpdatedPayload(BaseModel):
    config_id: UUID
    namespace: str
    name: str
    version: int
    changes: Dict[str, Any]


@EventRegistry.register("config.activated", 1)
class ConfigActivatedPayload(BaseModel):
    config_id: UUID
    namespace: str
    name: str
    version: int
    activated_by: str


@EventRegistry.register("config.deactivated", 1)
class ConfigDeactivatedPayload(BaseModel):
    config_id: UUID
    namespace: str
    name: str
    version: int
    deactivated_by: str


@EventRegistry.register("risk_policy.created", 1)
class RiskPolicyCreatedPayload(BaseModel):
    policy_id: UUID
    version: str
    limits: Dict[str, Any]


@EventRegistry.register("risk_policy.updated", 1)
class RiskPolicyUpdatedPayload(BaseModel):
    policy_id: UUID
    version: str
    updated_by: str


@EventRegistry.register("risk_policy.activated", 1)
class RiskPolicyActivatedPayload(BaseModel):
    policy_id: UUID
    version: str
    activated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Market Event Placeholders ---
@EventRegistry.register("market.tick_received", 1)
class MarketTickReceivedPayload(BaseModel):
    symbol: str
    price: Decimal
    quantity: Decimal
    exchange: str


@EventRegistry.register("market.candle_closed", 1)
class MarketCandleClosedPayload(BaseModel):
    symbol: str
    timeframe: str
    close_price: Decimal
    volume: Decimal


@EventRegistry.register("market.order_book_updated", 1)
class MarketOrderBookUpdatedPayload(BaseModel):
    symbol: str
    sequence_id: int


@EventRegistry.register("market.data_quality_changed", 1)
class MarketDataQualityChangedPayload(BaseModel):
    symbol: str
    is_healthy: bool
    reason: Optional[str] = None


# --- Intelligence Event Placeholders ---
@EventRegistry.register("features.snapshot_created", 1)
class FeaturesSnapshotCreatedPayload(BaseModel):
    symbol: str
    timeframe: str


@EventRegistry.register("agent.signal_created", 1)
class AgentSignalCreatedPayload(BaseModel):
    agent_id: str
    symbol: str
    action: str
    confidence: float


@EventRegistry.register("critic.decision_created", 1)
class CriticDecisionCreatedPayload(BaseModel):
    approved: bool
    rejection_reason: Optional[str] = None


@EventRegistry.register("trade.intent_created", 1)
class TradeIntentCreatedPayload(BaseModel):
    intent_id: UUID
    symbol: str
    side: str


# --- Risk Event Placeholders ---
@EventRegistry.register("risk.decision_created", 1)
class RiskDecisionCreatedPayload(BaseModel):
    intent_id: UUID
    approved: bool
    approved_quantity: Decimal


@EventRegistry.register("risk.limit_breached", 1)
class RiskLimitBreachedPayload(BaseModel):
    limit_type: str
    current_value: float
    threshold_value: float


@EventRegistry.register("risk.kill_switch_activated", 1)
class RiskKillSwitchActivatedPayload(BaseModel):
    level: str  # SOFT_STOP or HARD_STOP
    reason: str


# --- Execution Event Placeholders ---
@EventRegistry.register("order.approved", 1)
class OrderApprovedPayload(BaseModel):
    intent_id: UUID
    client_order_id: str
    approved_quantity: Decimal


@EventRegistry.register("order.submission_requested", 1)
class OrderSubmissionRequestedPayload(BaseModel):
    client_order_id: str


@EventRegistry.register("order.submitted", 1)
class OrderSubmittedPayload(BaseModel):
    client_order_id: str
    exchange_order_id: str


@EventRegistry.register("order.partially_filled", 1)
class OrderPartiallyFilledPayload(BaseModel):
    client_order_id: str
    filled_quantity: Decimal
    price: Decimal


@EventRegistry.register("order.filled", 1)
class OrderFilledPayload(BaseModel):
    client_order_id: str
    filled_quantity: Decimal
    price: Decimal


@EventRegistry.register("order.rejected", 1)
class OrderRejectedPayload(BaseModel):
    client_order_id: str
    reason: str


@EventRegistry.register("order.cancelled", 1)
class OrderCancelledPayload(BaseModel):
    client_order_id: str
    reason: str
