"""Phase 4.3: deterministic baseline opportunity ranking.

Not a machine-learned ranker — a documented, versioned linear scoring formula over inputs the
rest of the pipeline already produced. Given the same inputs, `rank()` always returns the same
order (Section 9.3 test requirement: "deterministic output").
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from packages.domain.entities import CorrelationSnapshot, EvidenceRecord, RankingResult
from packages.domain.enums import RankingStatus
from packages.evidence.models import EvidenceStatus

RANKING_VERSION = "ranking_v1"

# Weights are declared up front, not tuned to any backtest result — this is a research
# instrument for ordering candidates, not a claim about profitability (Master Plan objective:
# "do not optimize toward profitable backtest results in this task").
WEIGHT_EXPECTED_EDGE = Decimal("1.0")
WEIGHT_EVIDENCE = Decimal("0.5")
WEIGHT_LIQUIDITY = Decimal("0.2")
WEIGHT_FRESHNESS = Decimal("0.2")
WEIGHT_COST_PENALTY = Decimal("1.0")
WEIGHT_CORRELATION_PENALTY = Decimal("0.5")
WEIGHT_RISK_PENALTY = Decimal("0.5")

_EVIDENCE_WEIGHT_BY_STATUS = {
    EvidenceStatus.UNIVERSAL_APPROVED: Decimal("1.0"),
    EvidenceStatus.ASSET_SPECIFIC_APPROVED: Decimal("0.8"),
    EvidenceStatus.RESEARCH_ONLY: Decimal("0.2"),
    EvidenceStatus.DEGRADED: Decimal("0.1"),
}


@dataclass(frozen=True)
class RankingInput:
    candidate_id: UUID
    symbol: str
    expected_net_edge_bps: Optional[Decimal]
    calibrated_probability: Optional[Decimal]
    evidence: Optional[EvidenceRecord]
    liquidity_score: Decimal  # 0..1, caller-supplied (e.g. from 24h quote volume normalization)
    data_freshness_score: Decimal  # 0..1, 1.0 = current bar, decays with staleness
    cost_bps: Decimal
    correlated_exposure_score: Decimal  # 0..1, 0 = uncorrelated with open/candidate exposure
    risk_score: Decimal  # 0..1, higher = riskier (e.g. drawdown proximity)


class BaselineRankingService:
    def rank(
        self, inputs: List[RankingInput], correlation_snapshots: Optional[List[CorrelationSnapshot]] = None,
    ) -> List[RankingResult]:
        results = [self._score_one(i) for i in inputs]
        # Deterministic tie-break: score desc, then candidate_id asc (stable, no randomness).
        ordered = sorted(results, key=lambda r: (-(r.ranking_score or Decimal("-999999")), str(r.candidate_id)))
        for rank, r in enumerate(ordered, start=1):
            r.rank = rank
        return ordered

    def _score_one(self, i: RankingInput) -> RankingResult:
        reason_codes: List[str] = []
        evidence_weight = Decimal("0")
        if i.evidence is not None:
            evidence_weight = _EVIDENCE_WEIGHT_BY_STATUS.get(i.evidence.status, Decimal("0"))
        else:
            reason_codes.append("NO_EVIDENCE_RECORD")

        has_edge_and_probability = i.expected_net_edge_bps is not None and i.calibrated_probability is not None
        if not has_edge_and_probability:
            reason_codes.append("MISSING_EDGE_OR_PROBABILITY_RESEARCH_FALLBACK")

        cost_penalty = i.cost_bps / Decimal("100")  # normalize bps to a comparable 0..~1 scale

        if i.expected_net_edge_bps is not None and i.calibrated_probability is not None:
            edge_term = (i.expected_net_edge_bps / Decimal("100")) * i.calibrated_probability
            status = RankingStatus.EVIDENCE_BACKED if evidence_weight >= Decimal("0.5") else RankingStatus.RESEARCH_ONLY
        else:
            # Documented research-only fallback: rank purely on evidence/liquidity/freshness,
            # zero credit for an edge that isn't actually known.
            edge_term = Decimal("0")
            status = RankingStatus.RESEARCH_ONLY

        score = (
            WEIGHT_EXPECTED_EDGE * edge_term
            + WEIGHT_EVIDENCE * evidence_weight
            + WEIGHT_LIQUIDITY * i.liquidity_score
            + WEIGHT_FRESHNESS * i.data_freshness_score
            - WEIGHT_COST_PENALTY * cost_penalty
            - WEIGHT_CORRELATION_PENALTY * i.correlated_exposure_score
            - WEIGHT_RISK_PENALTY * i.risk_score
        )

        return RankingResult(
            ranking_version=RANKING_VERSION,
            candidate_id=i.candidate_id,
            ranking_score=score,
            ranking_status=status,
            expected_net_edge_bps=i.expected_net_edge_bps,
            evidence_weight=evidence_weight,
            liquidity_weight=i.liquidity_score,
            data_freshness_weight=i.data_freshness_score,
            cost_penalty=cost_penalty,
            correlation_penalty=i.correlated_exposure_score,
            risk_penalty=i.risk_score,
            reason_codes=reason_codes,
        )
