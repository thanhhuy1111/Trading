from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class RiskPolicyConfig(BaseModel):
    enabled: bool = True
    version: str = "1.0.0"

    risk_per_trade_pct: Decimal = Field(default=Decimal("0.0025"), gt=Decimal("0.0"), le=Decimal("0.05"))
    max_open_risk_pct: Decimal = Field(default=Decimal("0.0100"), gt=Decimal("0.0"), le=Decimal("0.10"))
    max_symbol_allocation_pct: Decimal = Field(default=Decimal("0.1500"), gt=Decimal("0.0"), le=Decimal("0.50"))
    max_total_exposure_pct: Decimal = Field(default=Decimal("0.5000"), gt=Decimal("0.0"), le=Decimal("1.00"))
    max_correlated_exposure_pct: Decimal = Field(default=Decimal("0.3000"), gt=Decimal("0.0"), le=Decimal("0.80"))

    daily_loss_warning_pct: Decimal = Field(default=Decimal("0.0100"), ge=Decimal("0.0"))
    max_daily_loss_pct: Decimal = Field(default=Decimal("0.0150"), ge=Decimal("0.0"))
    weekly_loss_warning_pct: Decimal = Field(default=Decimal("0.0250"), ge=Decimal("0.0"))
    max_weekly_loss_pct: Decimal = Field(default=Decimal("0.0350"), ge=Decimal("0.0"))

    warning_drawdown_pct: Decimal = Field(default=Decimal("0.0500"), ge=Decimal("0.0"))
    soft_stop_drawdown_pct: Decimal = Field(default=Decimal("0.0650"), ge=Decimal("0.0"))
    hard_stop_drawdown_pct: Decimal = Field(default=Decimal("0.0800"), ge=Decimal("0.0"))

    min_stop_distance_pct: Decimal = Field(default=Decimal("0.0050"), gt=Decimal("0.0"))
    max_stop_distance_pct: Decimal = Field(default=Decimal("0.1000"), gt=Decimal("0.0"))
    minimum_reward_risk_ratio: Decimal = Field(default=Decimal("1.50"), ge=Decimal("1.0"))

    fee_buffer_bps: Decimal = Field(default=Decimal("10.0"), ge=Decimal("0.0"))
    slippage_buffer_bps: Decimal = Field(default=Decimal("10.0"), ge=Decimal("0.0"))
    reserve_cash_pct: Decimal = Field(default=Decimal("0.0500"), ge=Decimal("0.0"), lt=Decimal("1.0"))

    max_intent_age_seconds: int = Field(default=300, gt=0)
    max_portfolio_snapshot_age_seconds: int = Field(default=120, gt=0)
    max_market_price_age_seconds: int = Field(default=60, gt=0)

    leverage_enabled: bool = False
    short_selling_enabled: bool = False
    margin_enabled: bool = False
    live_trading_enabled: bool = False

    @model_validator(mode="after")
    def validate_safety_boundaries(self) -> "RiskPolicyConfig":
        if self.leverage_enabled or self.short_selling_enabled or self.margin_enabled or self.live_trading_enabled:
            raise ValueError(
                "Safety Violation: leverage, short_selling, margin, and live_trading MUST remain strictly False"
            )

        if self.risk_per_trade_pct > self.max_open_risk_pct:
            raise ValueError("Invalid Risk Policy: risk_per_trade_pct cannot exceed max_open_risk_pct")

        if self.max_open_risk_pct > self.max_total_exposure_pct:
            raise ValueError("Invalid Risk Policy: max_open_risk_pct cannot exceed max_total_exposure_pct")

        if self.daily_loss_warning_pct > self.max_daily_loss_pct:
            raise ValueError("Invalid Risk Policy: daily_loss_warning_pct cannot exceed max_daily_loss_pct")

        if self.soft_stop_drawdown_pct > self.hard_stop_drawdown_pct:
            raise ValueError("Invalid Risk Policy: soft_stop_drawdown_pct cannot exceed hard_stop_drawdown_pct")

        return self


default_risk_policy = RiskPolicyConfig()
