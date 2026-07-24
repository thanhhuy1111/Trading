"""Deterministic Phase 9 manager and immutable analysis snapshot."""

from datetime import datetime
from enum import Enum
from hashlib import sha256
from typing import Dict, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.agents.debate import DebateStatus, DebateTranscript
from packages.agents.specialists import (
    SpecialistAgentName,
    SpecialistAssessment,
    SpecialistStatus,
)
from packages.agents.verification_risk import (
    AnalysisRiskEngine,
    AnalysisRiskRequest,
    AnalysisRiskResult,
    VerificationAgent,
    VerificationDecision,
    VerificationResult,
)
from packages.retraining.xgboost_contracts import TargetClass


class ManagerRecommendation(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    HOLD = "HOLD"
    NO_DECISION = "NO_DECISION"


class ManagerSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str
    recommendation: ManagerRecommendation
    direction: Optional[TargetClass] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    risk_level: Optional[str] = None
    evidence_ids: Tuple[str, ...] = ()
    invalidating_conditions: Tuple[str, ...] = ()
    reason_codes: Tuple[str, ...] = ()
    as_of_time: Optional[datetime] = None
    manager_version: str = "1.0.0"
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_snapshot(self) -> "ManagerSnapshot":
        if self.as_of_time is not None and self.as_of_time.tzinfo is None:
            raise ValueError("manager timestamp must be timezone-aware")
        if self.recommendation == ManagerRecommendation.NO_DECISION:
            if (
                self.direction is not None
                or self.confidence is not None
                or self.risk_level is not None
                or self.evidence_ids
                or self.invalidating_conditions
                or not self.reason_codes
            ):
                raise ValueError("NO_DECISION cannot fabricate analysis")
        elif (
            self.as_of_time is None
            or
            self.direction is None
            or self.confidence is None
            or self.risk_level is None
            or not self.evidence_ids
            or self.reason_codes
        ):
            raise ValueError("manager decision is incomplete")
        if self.recommendation == ManagerRecommendation.SHORT:
            raise ValueError("SHORT is disabled until short risk contract is approved")
        return self


class ManagerSnapshotStore:
    def __init__(self) -> None:
        self._snapshots: Dict[str, ManagerSnapshot] = {}

    def persist(self, snapshot: ManagerSnapshot) -> ManagerSnapshot:
        existing = self._snapshots.get(snapshot.analysis_id)
        if existing is not None:
            if existing.input_fingerprint != snapshot.input_fingerprint:
                raise ValueError("MANAGER_ANALYSIS_CONFLICT")
            return existing
        self._snapshots[snapshot.analysis_id] = snapshot
        return snapshot

    def get(self, analysis_id: str) -> Optional[ManagerSnapshot]:
        return self._snapshots.get(analysis_id)


class ManagerAgent:
    def __init__(
        self,
        store: ManagerSnapshotStore,
        verifier: VerificationAgent,
        risk_engine: AnalysisRiskEngine,
    ) -> None:
        if type(verifier) is not VerificationAgent:
            raise TypeError("VERIFICATION_AUTHORITY_REQUIRED")
        if type(risk_engine) is not AnalysisRiskEngine:
            raise TypeError("RISK_AUTHORITY_REQUIRED")
        if not risk_engine.uses_verifier(verifier):
            raise TypeError("RISK_VERIFICATION_AUTHORITY_MISMATCH")
        self._store = store
        self._verifier = verifier
        self._risk_engine = risk_engine

    def decide(
        self,
        *,
        analysis_id: str,
        as_of_time: datetime,
        assessments: Tuple[SpecialistAssessment, ...],
        debate: DebateTranscript,
        verification: VerificationResult,
        risk: AnalysisRiskResult,
        risk_request: AnalysisRiskRequest,
    ) -> ManagerSnapshot:
        fingerprint = _fingerprint(
            analysis_id,
            as_of_time,
            assessments,
            debate,
            verification,
            risk,
            risk_request,
        )
        reasons = self._validate_inputs(
            analysis_id,
            as_of_time,
            assessments,
            debate,
            verification,
            risk,
            risk_request,
        )
        if reasons:
            return self._store.persist(
                ManagerSnapshot(
                    analysis_id=analysis_id,
                    recommendation=ManagerRecommendation.NO_DECISION,
                    reason_codes=tuple(dict.fromkeys(reasons)),
                    as_of_time=as_of_time if as_of_time.tzinfo is not None else None,
                    input_fingerprint=fingerprint,
                )
            )
        directions = tuple(
            assessment.direction
            for assessment in assessments
            if assessment.direction is not None
        )
        quantitative = next(
            assessment
            for assessment in assessments
            if assessment.agent_name == SpecialistAgentName.QUANTITATIVE
        )
        counts = {target: directions.count(target) for target in TargetClass}
        maximum = max(counts.values())
        winners = tuple(target for target, count in counts.items() if count == maximum)
        direction = (
            winners[0]
            if len(winners) == 1
            else quantitative.direction
        )
        assert direction is not None
        recommendation = {
            TargetClass.BULLISH: ManagerRecommendation.LONG,
            TargetClass.NEUTRAL: ManagerRecommendation.HOLD,
            TargetClass.BEARISH: ManagerRecommendation.NO_DECISION,
        }[direction]
        if recommendation == ManagerRecommendation.NO_DECISION:
            return self._store.persist(
                ManagerSnapshot(
                    analysis_id=analysis_id,
                    recommendation=recommendation,
                    reason_codes=("SHORT_RISK_CONTRACT_DISABLED",),
                    as_of_time=as_of_time,
                    input_fingerprint=fingerprint,
                )
            )
        invalidating = tuple(
            sorted(
                {
                    *(
                        condition
                        for assessment in assessments
                        for condition in assessment.invalidating_conditions
                    ),
                    *(
                        condition
                        for turn in debate.turns
                        if turn.output is not None
                        for condition in turn.output.invalidating_conditions
                    ),
                }
            )
        )
        if not invalidating:
            return self._store.persist(
                ManagerSnapshot(
                    analysis_id=analysis_id,
                    recommendation=ManagerRecommendation.NO_DECISION,
                    reason_codes=("INVALIDATING_CONDITIONS_MISSING",),
                    as_of_time=as_of_time,
                    input_fingerprint=fingerprint,
                )
            )
        return self._store.persist(
            ManagerSnapshot(
                analysis_id=analysis_id,
                recommendation=recommendation,
                direction=direction,
                confidence=float(verification.quantitative_confidence),
                risk_level=risk.risk_level,
                evidence_ids=verification.evidence_ids,
                invalidating_conditions=invalidating,
                as_of_time=as_of_time,
                input_fingerprint=fingerprint,
            )
        )

    def _validate_inputs(
        self,
        analysis_id: str,
        as_of_time: datetime,
        assessments: Tuple[SpecialistAssessment, ...],
        debate: DebateTranscript,
        verification: VerificationResult,
        risk: AnalysisRiskResult,
        risk_request: AnalysisRiskRequest,
    ) -> list[str]:
        reasons: list[str] = []
        if as_of_time.tzinfo is None:
            return ["ANALYSIS_AS_OF_INVALID"]
        reverified = self._verifier.verify(
            analysis_id=analysis_id,
            as_of_time=as_of_time,
            assessments=tuple(
                sorted(assessments, key=lambda item: item.agent_name.value)
            ),
            debate=debate,
        )
        if (
            not self._verifier.is_issued(verification)
            or
            verification != reverified
            or
            verification.analysis_id != analysis_id
            or verification.verified_at != as_of_time
            or verification.decision != VerificationDecision.VERIFIED
        ):
            reasons.append("VERIFICATION_REJECTED")
        if (
            not self._risk_engine.is_issued(risk)
            or
            not self._risk_engine.matches_verification(risk, verification)
            or
            not self._risk_engine.matches_request(risk, risk_request)
            or
            risk.analysis_id != analysis_id
            or risk.evaluated_at != as_of_time
            or not risk.allow_trade
        ):
            reasons.append("RISK_REJECTED")
        if (
            debate.analysis_id != analysis_id
            or debate.as_of_time != as_of_time
            or debate.status != DebateStatus.COMPLETE
        ):
            reasons.append("DEBATE_INVALID")
        if (
            len(assessments) != 3
            or {assessment.agent_name for assessment in assessments}
            != set(SpecialistAgentName)
            or any(
                assessment.analysis_id != analysis_id
                or assessment.as_of_time != as_of_time
                or assessment.status != SpecialistStatus.AVAILABLE
                for assessment in assessments
            )
        ):
            reasons.append("SPECIALIST_INPUT_INVALID")
        return reasons


def _fingerprint(
    analysis_id: str,
    as_of_time: datetime,
    assessments: Tuple[SpecialistAssessment, ...],
    debate: DebateTranscript,
    verification: VerificationResult,
    risk: AnalysisRiskResult,
    risk_request: AnalysisRiskRequest,
) -> str:
    payload = "|".join(
        (
            analysis_id,
            as_of_time.isoformat(),
            *(
                assessment.model_dump_json()
                for assessment in sorted(
                    assessments,
                    key=lambda item: item.agent_name.value,
                )
            ),
            debate.model_dump_json(),
            verification.model_dump_json(),
            risk.model_dump_json(),
            risk_request.model_dump_json(),
            "manager:1.0.0",
        )
    )
    return sha256(payload.encode()).hexdigest()
