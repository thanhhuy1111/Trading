from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Set
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.common.logger import logger


class PrincipalType(str, Enum):
    USER = "USER"
    SERVICE_ACCOUNT = "SERVICE_ACCOUNT"
    SYSTEM = "SYSTEM"


class AuthenticatedPrincipal(BaseModel):
    model_config = ConfigDict(frozen=True)

    principal_id: str
    principal_type: PrincipalType = PrincipalType.USER
    roles: Set[str] = Field(default_factory=lambda: {"VIEWER"})
    permissions: Set[str] = Field(default_factory=set)
    authenticated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    auth_context: Dict[str, str] = Field(default_factory=dict)


ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "VIEWER": {"read:dashboard", "read:market_data", "read:positions", "read:recommendations"},
    "ANALYST": {
        "read:dashboard", "read:market_data", "read:positions", "create:backtest", "read:backtest",
        "read:recommendations"
    },
    "OPERATOR": {
        "read:dashboard", "read:market_data", "read:positions", "create:backtest", "read:backtest",
        "manage:paper_session", "read:recommendations", "create:recommendation"
    },
    "RISK_OPERATOR": {
        "read:dashboard", "read:market_data", "read:positions", "manage:paper_session", "manage:risk_governor",
        "read:recommendations", "manage:strategy_portfolio"
    },
    "SECURITY_AUDITOR": {
        "read:dashboard", "read:audit", "read:incidents", "read:security", "manage:security_incidents"
    },
    "ADMINISTRATOR": {
        "read:dashboard", "read:market_data", "read:positions", "create:backtest", "read:backtest",
        "manage:paper_session", "manage:risk_governor", "read:audit", "read:incidents", "read:security",
        "manage:security_incidents", "manage:system_config", "read:recommendations", "create:recommendation",
        "manage:strategy_portfolio"
    },
}


class SecurityManager:
    """Manages role-based access control (RBAC), permission evaluation, and object-level authorization."""

    @staticmethod
    def get_principal_permissions(principal: AuthenticatedPrincipal) -> Set[str]:
        perms = set(principal.permissions)
        for role in principal.roles:
            if role in ROLE_PERMISSIONS:
                perms.update(ROLE_PERMISSIONS[role])
        return perms

    @staticmethod
    def check_permission(principal: AuthenticatedPrincipal, required_permission: str) -> bool:
        user_perms = SecurityManager.get_principal_permissions(principal)
        if required_permission not in user_perms:
            logger.warning(
                "Access denied: Missing required permission",
                extra={"principal_id": principal.principal_id, "required": required_permission}
            )
            return False
        return True

    @staticmethod
    def authorize_object_access(principal: AuthenticatedPrincipal, object_type: str, object_id: UUID) -> bool:
        # Default deny object-level authorization policy
        if "ADMINISTRATOR" in principal.roles or "SECURITY_AUDITOR" in principal.roles:
            return True
        if "VIEWER" in principal.roles or "OPERATOR" in principal.roles or "ANALYST" in principal.roles:
            return True
        logger.warning(
            "Access denied: Object-level authorization failed",
            extra={"principal_id": principal.principal_id, "type": object_type, "id": str(object_id)}
        )
        return False


security_manager = SecurityManager()
