"""Phase 8: shared FastAPI dependencies for the recommendation API - request ID, principal
extraction/RBAC, and the recommendation service singleton.

Auth here is intentionally a minimal, honest abstraction, not a real identity provider: it
reads a `X-Principal-Id` / `X-Roles` header pair and defaults to an anonymous VIEWER when
absent. This matches the rest of the architecture's baseline pattern (PassThroughMetaLabel,
no-op LLM agents) - a real OAuth/JWT provider can be swapped in later without changing any
endpoint's permission checks, because those check `SecurityManager`, not this module.
"""

from typing import Callable, Optional

from fastapi import Depends, Header, HTTPException, Request, status

from apps.api.error_schema import get_or_create_request_id
from packages.evidence.store import EvidenceStore, evidence_store
from packages.governance.security import AuthenticatedPrincipal, SecurityManager, security_manager
from packages.intelligence.strategy_portfolio import StrategyPortfolio
from packages.registries.instances import (
    evidence_registry,
    feature_artifact_registry,
    label_registry,
    model_registry,
    policy_registry,
    strategy_registry,
    universe_registry,
)
from packages.registries.registry import ArtifactRegistry
from packages.risk.portfolio_governor import BaselinePortfolioRiskGovernor
from packages.runtime.candles_cache import cached_candles_provider
from packages.runtime.recommendation_service import BaselineRecommendationService

REGISTRIES_BY_NAME: dict[str, ArtifactRegistry] = {
    "strategy": strategy_registry,
    "model": model_registry,
    "evidence": evidence_registry,
    "feature_set": feature_artifact_registry,
    "label": label_registry,
    "universe": universe_registry,
    "policy": policy_registry,
}

_strategy_portfolio = StrategyPortfolio()
_recommendation_service = BaselineRecommendationService(
    candles_provider=cached_candles_provider,
    evidence_service=evidence_store,
    strategy_portfolio=_strategy_portfolio,
)


def get_request_id(request: Request) -> str:
    return get_or_create_request_id(request)


def get_evidence_store() -> EvidenceStore:
    return evidence_store


def get_strategy_portfolio() -> StrategyPortfolio:
    return _strategy_portfolio


def get_portfolio_risk_governor() -> BaselinePortfolioRiskGovernor:
    return BaselinePortfolioRiskGovernor()


def get_recommendation_service() -> BaselineRecommendationService:
    return _recommendation_service


def get_current_principal(
    x_principal_id: Optional[str] = Header(default=None),
    x_roles: Optional[str] = Header(default=None),
) -> AuthenticatedPrincipal:
    roles = {r.strip() for r in x_roles.split(",")} if x_roles else {"VIEWER"}
    return AuthenticatedPrincipal(principal_id=x_principal_id or "anonymous", roles=roles)


def require_permission(permission: str) -> Callable[[AuthenticatedPrincipal], AuthenticatedPrincipal]:
    def _check(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> AuthenticatedPrincipal:
        if not SecurityManager.check_permission(principal, permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        return principal

    return _check


__all__ = [
    "REGISTRIES_BY_NAME",
    "get_current_principal",
    "get_evidence_store",
    "get_portfolio_risk_governor",
    "get_recommendation_service",
    "get_request_id",
    "get_strategy_portfolio",
    "require_permission",
    "security_manager",
]
