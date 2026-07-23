"""Phase 4.5: strategy portfolio sleeves.

A sleeve can exist and be inspectable in RESEARCH_ONLY without ever being eligible for an
approved recommendation — eligibility is decided by evidence_status, not by whether the sleeve
"exists" (Section 9.5).
"""

from typing import List, Optional

from pydantic import BaseModel

from packages.domain.enums import EvidenceStatus


class StrategySleeve(BaseModel):
    strategy_id: str
    symbol: str
    timeframe: str
    regime_scope: List[str]
    risk_budget_pct: float
    allocation_weight: float
    evidence_status: EvidenceStatus
    model_version: str
    drawdown_limit_pct: float
    enabled: bool = True

    @property
    def is_approved_eligible(self) -> bool:
        """Only these two evidence statuses ever make a sleeve eligible for an APPROVED
        recommendation — every other status (including RESEARCH_ONLY) can still generate a
        candidate for shadow tracking, but never an approved proposal."""
        return self.enabled and self.evidence_status in (
            EvidenceStatus.UNIVERSAL_APPROVED, EvidenceStatus.ASSET_SPECIFIC_APPROVED,
        )


class StrategyPortfolio:
    def __init__(self, sleeves: Optional[List[StrategySleeve]] = None) -> None:
        self._sleeves = list(sleeves or [])

    def register(self, sleeve: StrategySleeve) -> None:
        self._sleeves.append(sleeve)

    def eligible_sleeves(self, symbol: str, timeframe: str, regime: str) -> List[StrategySleeve]:
        """Every sleeve matching (symbol, timeframe, regime) that's enabled — including
        RESEARCH_ONLY ones. Callers that need only approved-recommendation-eligible sleeves
        must additionally filter on `.is_approved_eligible` themselves; this method does not
        hide RESEARCH_ONLY sleeves, since shadow tracking needs to see them too."""
        return [
            s for s in self._sleeves
            if s.symbol == symbol and s.timeframe == timeframe and regime in s.regime_scope and s.enabled
        ]

    def approved_sleeves(self, symbol: str, timeframe: str, regime: str) -> List[StrategySleeve]:
        return [s for s in self.eligible_sleeves(symbol, timeframe, regime) if s.is_approved_eligible]

    def all_sleeves(self) -> List[StrategySleeve]:
        return list(self._sleeves)
