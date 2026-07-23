import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


class ConfigStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ARCHIVED = "ARCHIVED"


class RiskPolicyConfig(BaseModel):
    """Typed risk policy configuration model enforcing Decimal for financial risk limits."""
    max_risk_per_trade_pct: Decimal = Field(default=Decimal("0.0025"))    # 0.25% NAV
    max_open_risk_pct: Decimal = Field(default=Decimal("0.015"))         # 1.5% NAV
    max_daily_loss_pct: Decimal = Field(default=Decimal("0.015"))        # 1.5% NAV
    max_weekly_loss_pct: Decimal = Field(default=Decimal("0.04"))        # 4.0% NAV
    warning_drawdown_pct: Decimal = Field(default=Decimal("0.05"))       # 5.0% NAV
    hard_stop_drawdown_pct: Decimal = Field(default=Decimal("0.08"))     # 8.0% NAV
    max_asset_allocation_pct: Decimal = Field(default=Decimal("0.20"))   # 20.0% NAV
    max_correlated_exposure_pct: Decimal = Field(default=Decimal("0.40"))# 40.0% NAV
    leverage_enabled: bool = False

    @model_validator(mode="after")
    def validate_limits(self):
        if self.max_risk_per_trade_pct <= Decimal("0"):
            raise ValueError("max_risk_per_trade_pct must be strictly positive")
        if self.hard_stop_drawdown_pct <= self.warning_drawdown_pct:
            raise ValueError("hard_stop_drawdown_pct must be greater than warning_drawdown_pct")
        if self.leverage_enabled is True:
            raise ValueError("Leverage must remain disabled in Spot MVP")
        return self


class ConfigurationSet(BaseModel):
    """Versioned configuration set model."""
    id: UUID = Field(default_factory=uuid4)
    namespace: str
    name: str
    version: int
    status: ConfigStatus = ConfigStatus.DRAFT
    values: Dict[str, Any]
    checksum: str = ""
    created_by: str = "system"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    activated_at: Optional[datetime] = None
    deactivated_at: Optional[datetime] = None

    @model_validator(mode="after")
    def calculate_checksum(self):
        if not self.checksum:
            canonical = json.dumps(self.values, sort_keys=True)
            self.checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return self
