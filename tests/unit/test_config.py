from decimal import Decimal

import pytest
from pydantic import ValidationError

from packages.config_manager.schemas import ConfigStatus, ConfigurationSet, RiskPolicyConfig


def test_risk_policy_config_decimal_precision():
    config = RiskPolicyConfig(
        max_risk_per_trade_pct=Decimal("0.0025"),
        max_open_risk_pct=Decimal("0.015"),
        max_daily_loss_pct=Decimal("0.015"),
        warning_drawdown_pct=Decimal("0.05"),
        hard_stop_drawdown_pct=Decimal("0.08"),
        leverage_enabled=False
    )
    assert isinstance(config.max_risk_per_trade_pct, Decimal)
    assert config.max_risk_per_trade_pct == Decimal("0.0025")


def test_risk_policy_config_rejects_leverage():
    with pytest.raises(ValidationError, match="Leverage must remain disabled in Spot MVP"):
        RiskPolicyConfig(leverage_enabled=True)


def test_configuration_set_sha256_checksum():
    values = {"setting_a": 100, "setting_b": "active"}
    config_set = ConfigurationSet(
        namespace="trading",
        name="speed_params",
        version=1,
        status=ConfigStatus.DRAFT,
        values=values
    )
    assert config_set.checksum != ""
    assert len(config_set.checksum) == 64  # SHA-256 hex string length
