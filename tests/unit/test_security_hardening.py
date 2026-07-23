from decimal import Decimal
from uuid import uuid4

import pytest

from packages.common.config import settings
from packages.governance.backup import dr_service
from packages.governance.sbom import sbom_generator
from packages.governance.security import (
    AuthenticatedPrincipal,
    security_manager,
)
from packages.governance.validation import input_validator, output_sanitizer


def test_rbac_authorization_matrix() -> None:
    viewer = AuthenticatedPrincipal(principal_id="viewer_1", roles={"VIEWER"})
    operator = AuthenticatedPrincipal(principal_id="operator_1", roles={"OPERATOR"})
    admin = AuthenticatedPrincipal(principal_id="admin_1", roles={"ADMINISTRATOR"})

    assert security_manager.check_permission(viewer, "read:dashboard") is True
    assert security_manager.check_permission(viewer, "manage:paper_session") is False

    assert security_manager.check_permission(operator, "manage:paper_session") is True
    assert security_manager.check_permission(operator, "manage:system_config") is False

    assert security_manager.check_permission(admin, "manage:system_config") is True


def test_object_level_authorization() -> None:
    principal = AuthenticatedPrincipal(principal_id="user_1", roles={"OPERATOR"})
    obj_id = uuid4()
    assert security_manager.authorize_object_access(principal, "paper_session", obj_id) is True


def test_input_validation_boundary_enforcement() -> None:
    # Valid positive decimal
    assert input_validator.validate_decimal_amount(Decimal("100.50")) == Decimal("100.50")

    # NaN or Infinity raises ValueError
    with pytest.raises(ValueError, match="VALIDATION_ERROR"):
        input_validator.validate_decimal_amount(Decimal("NaN"))

    with pytest.raises(ValueError, match="VALIDATION_ERROR"):
        input_validator.validate_decimal_amount(Decimal("-10.00"), allow_zero=False)

    # Oversized payload raises ValueError
    with pytest.raises(ValueError, match="VALIDATION_ERROR"):
        input_validator.validate_payload_size(b"x" * 2_000_000, max_bytes=1_000_000)


def test_output_sanitizer_redacts_credentials_and_tracebacks() -> None:
    raw_response = {
        "status": "SUCCESS",
        "api_key": "SECRET_KEY_123",
        "traceback": "Traceback (most recent call last)...",
        "nested": {"password": "PASSWORD123"}
    }
    sanitized = output_sanitizer.sanitize_response_dto(raw_response)

    assert sanitized["status"] == "SUCCESS"
    assert sanitized["api_key"] == "[REDACTED]"
    assert "traceback" not in sanitized
    assert sanitized["nested"]["password"] == "[REDACTED]"


def test_sbom_generation_cyclonedx_format() -> None:
    sbom = sbom_generator.generate_sbom()
    assert sbom.format == "CycloneDX"
    assert sbom.total_packages > 0
    assert len(sbom.sbom_checksum) == 64


def test_disaster_recovery_backup_and_restore_drill() -> None:
    from packages.positions.ledger import portfolio_ledger
    from packages.positions.manager import position_manager

    portfolio_ledger.reset()
    position_manager.positions.clear()

    backup = dr_service.create_encrypted_backup()
    assert backup.status == "SUCCESS"

    restore = dr_service.run_restore_drill(backup.backup_id)
    assert restore.is_reconciliation_passed is True


def test_live_trading_kill_boundary_invariants() -> None:
    assert settings.LIVE_TRADING_ENABLED is False
    assert settings.PRIVATE_EXCHANGE_API_ENABLED is False
    assert settings.SYSTEM_MODE in ["SIMULATION", "MINIMAL", "PAPER_TRADING", "DEVELOPMENT", "TEST"]
