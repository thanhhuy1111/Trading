"""Deterministic Phase 8 verification authority and analysis risk engine."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.agents.analysis_evidence import (
    AnalysisEvidenceCategory,
    AnalysisEvidenceRegistry,
    AnalysisEvidenceStatus,
)
from packages.agents.debate import DebateStatus, DebateTranscript
from packages.agents.specialists import (
    SpecialistAgentName,
    SpecialistAssessment,
    SpecialistStatus,
)
from packages.retraining.xgboost_contracts import TargetClass
from packages.risk.calculator import PositionSizingCalculator


class VerificationDecision(str, Enum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class VerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str
    decision: VerificationDecision
    evidence_ids: Tuple[str, ...] = ()
    contradictions: bool = False
    quantitative_confidence: Optional[Decimal] = Field(default=None, ge=0, le=1)
    confidence_evidence_id: Optional[str] = None
    technical_volatility: Optional[Decimal] = Field(default=None, ge=0)
    volatility_evidence_id: Optional[str] = None
    reason_codes: Tuple[str, ...] = ()
    verified_at: Optional[datetime] = None
    verifier_version: str = "1.0.0"

    @model_validator(mode="after")
    def validate_result(self) -> "VerificationResult":
        if self.verified_at is not None and self.verified_at.tzinfo is None:
            raise ValueError("verification timestamp must be timezone-aware")
        if self.decision == VerificationDecision.VERIFIED:
            if (
                not self.evidence_ids
                or self.reason_codes
                or self.verified_at is None
                or self.quantitative_confidence is None
                or self.confidence_evidence_id not in self.evidence_ids
                or self.technical_volatility is None
                or self.volatility_evidence_id not in self.evidence_ids
            ):
                raise ValueError("verified result requires evidence and no rejection")
        elif (
            not self.reason_codes
            or self.quantitative_confidence is not None
            or self.confidence_evidence_id is not None
            or self.technical_volatility is not None
            or self.volatility_evidence_id is not None
        ):
            raise ValueError("rejected verification requires reason codes")
        return self


class VerificationAgent:
    """Code-only verification with absolute rejection authority."""

    def __init__(self, evidence: AnalysisEvidenceRegistry) -> None:
        self._evidence = evidence

    def verify(
        self,
        *,
        analysis_id: str,
        as_of_time: datetime,
        assessments: Tuple[SpecialistAssessment, ...],
        debate: DebateTranscript,
    ) -> VerificationResult:
        reasons: list[str] = []
        if as_of_time.tzinfo is None:
            return VerificationResult(
                analysis_id=analysis_id,
                decision=VerificationDecision.REJECTED,
                reason_codes=("ANALYSIS_AS_OF_INVALID",),
            )
        if debate.analysis_id != analysis_id or debate.as_of_time != as_of_time:
            reasons.append("DEBATE_ANALYSIS_MISMATCH")
        if debate.status != DebateStatus.COMPLETE:
            reasons.append("DEBATE_NOT_COMPLETE")
        if not assessments:
            reasons.append("ASSESSMENTS_MISSING")
        agent_names = tuple(assessment.agent_name for assessment in assessments)
        if (
            len(assessments) != 3
            or len(set(agent_names)) != 3
            or set(agent_names)
            != {
                SpecialistAgentName.TECHNICAL,
                SpecialistAgentName.DERIVATIVES,
                SpecialistAgentName.QUANTITATIVE,
            }
        ):
            reasons.append("SPECIALIST_SET_INVALID")
        evidence_ids: list[str] = []
        directions: set[TargetClass] = set()
        quantitative_confidence: Optional[Decimal] = None
        confidence_evidence_id: Optional[str] = None
        technical_volatility: Optional[Decimal] = None
        volatility_evidence_id: Optional[str] = None
        for assessment in assessments:
            if (
                assessment.analysis_id != analysis_id
                or assessment.status != SpecialistStatus.AVAILABLE
                or assessment.as_of_time != as_of_time
            ):
                reasons.append("ASSESSMENT_INVALID")
                continue
            if assessment.direction is not None:
                directions.add(assessment.direction)
            evidence_ids.extend(assessment.evidence_ids)
            if assessment.agent_name == SpecialistAgentName.QUANTITATIVE:
                if (
                    assessment.confidence is None
                    or assessment.confidence_source is None
                ):
                    reasons.append("QUANTITATIVE_CONFIDENCE_MISSING")
                else:
                    quantitative_confidence = Decimal(str(assessment.confidence))
                    confidence_evidence_id = assessment.confidence_source
            if assessment.agent_name == SpecialistAgentName.TECHNICAL:
                volatility_records = tuple(
                    self._evidence.get(evidence_id)
                    for evidence_id in assessment.evidence_ids
                    if (
                        self._evidence.get(evidence_id) is not None
                        and self._evidence.get(evidence_id).name == "volatility_20"  # type: ignore[union-attr]
                    )
                )
                if len(volatility_records) != 1 or volatility_records[0] is None:
                    reasons.append("TECHNICAL_VOLATILITY_MISSING")
                else:
                    technical_volatility = volatility_records[0].numeric_value
                    volatility_evidence_id = volatility_records[0].evidence_id
            if not self._claims_valid(assessment, analysis_id, as_of_time):
                reasons.append("ASSESSMENT_EVIDENCE_INVALID")
        for turn in debate.turns:
            if turn.output is not None:
                evidence_ids.extend(turn.output.evidence_ids)
                for evidence_id in turn.output.evidence_ids:
                    record = self._evidence.get(evidence_id)
                    if (
                        record is None
                        or record.analysis_id != analysis_id
                        or record.status != AnalysisEvidenceStatus.VALID
                        or record.observed_at > as_of_time
                        or record.available_at > as_of_time
                    ):
                        reasons.append("DEBATE_EVIDENCE_INVALID")
                for claim in turn.output.numeric_claims:
                    record = self._evidence.get(claim.evidence_id)
                    if (
                        record is None
                        or record.analysis_id != analysis_id
                        or record.status != AnalysisEvidenceStatus.VALID
                        or record.observed_at > as_of_time
                        or record.available_at > as_of_time
                        or record.name != claim.name
                        or record.numeric_value != claim.value
                        or record.unit != claim.unit
                    ):
                        reasons.append("DEBATE_EVIDENCE_INVALID")
        unique_evidence_ids = tuple(dict.fromkeys(evidence_ids))
        if not unique_evidence_ids:
            reasons.append("EVIDENCE_MISSING")
        contradictions = len(directions) > 1
        return VerificationResult(
            analysis_id=analysis_id,
            decision=(
                VerificationDecision.REJECTED
                if reasons
                else VerificationDecision.VERIFIED
            ),
            evidence_ids=unique_evidence_ids if not reasons else (),
            contradictions=contradictions,
            quantitative_confidence=(
                quantitative_confidence if not reasons else None
            ),
            confidence_evidence_id=(
                confidence_evidence_id if not reasons else None
            ),
            technical_volatility=technical_volatility if not reasons else None,
            volatility_evidence_id=volatility_evidence_id if not reasons else None,
            reason_codes=tuple(dict.fromkeys(reasons)),
            verified_at=as_of_time if as_of_time.tzinfo is not None else None,
        )

    def _claims_valid(
        self,
        assessment: SpecialistAssessment,
        analysis_id: str,
        as_of_time: datetime,
    ) -> bool:
        expected_category = {
            SpecialistAgentName.TECHNICAL: AnalysisEvidenceCategory.TECHNICAL,
            SpecialistAgentName.DERIVATIVES: AnalysisEvidenceCategory.DERIVATIVES,
            SpecialistAgentName.QUANTITATIVE: AnalysisEvidenceCategory.QUANTITATIVE,
        }[assessment.agent_name]
        if not assessment.evidence_ids:
            return False
        for evidence_id in assessment.evidence_ids:
            record = self._evidence.get(evidence_id)
            if (
                record is None
                or record.analysis_id != analysis_id
                or record.category != expected_category
                or record.status != AnalysisEvidenceStatus.VALID
                or record.observed_at > as_of_time
                or record.available_at > as_of_time
            ):
                return False
        for claim in assessment.numeric_claims:
            record = self._evidence.get(claim.evidence_id)
            if (
                record is None
                or claim.evidence_id not in assessment.evidence_ids
                or record.name != claim.name
                or record.numeric_value != claim.value
                or record.unit != claim.unit
            ):
                return False
        return True


class AnalysisRiskRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str
    side: Literal["LONG"] = "LONG"
    as_of_time: datetime
    nav: Decimal = Field(gt=0)
    available_cash: Decimal = Field(ge=0)
    entry_price: Decimal = Field(gt=0)
    stop_price: Decimal = Field(gt=0)
    take_profit_price: Decimal = Field(gt=0)
    current_symbol_exposure: Decimal = Field(ge=0)
    current_gross_exposure: Decimal = Field(ge=0)
    drawdown: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_request(self) -> "AnalysisRiskRequest":
        if self.as_of_time.tzinfo is None:
            raise ValueError("risk timestamp must be timezone-aware")
        return self


class AnalysisRiskResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str
    allow_trade: bool
    approved_quantity: Decimal = Field(ge=0)
    approved_notional: Decimal = Field(ge=0)
    reward_risk_ratio: Decimal | None = None
    risk_level: str
    reason_codes: Tuple[str, ...]
    evaluated_at: datetime
    engine_version: str = "1.0.0"

    @model_validator(mode="after")
    def validate_result(self) -> "AnalysisRiskResult":
        if self.evaluated_at.tzinfo is None:
            raise ValueError("risk result timestamp must be timezone-aware")
        if self.allow_trade:
            if (
                self.approved_quantity <= 0
                or self.approved_notional <= 0
                or self.reward_risk_ratio is None
                or self.reason_codes
            ):
                raise ValueError("allowed risk result is incomplete")
        elif self.approved_quantity != 0 or self.approved_notional != 0 or not self.reason_codes:
            raise ValueError("rejected risk result cannot approve exposure")
        return self


class AnalysisRiskEngine:
    def __init__(self) -> None:
        self._sizing = PositionSizingCalculator()

    def evaluate(
        self,
        request: AnalysisRiskRequest,
        verification: VerificationResult,
    ) -> AnalysisRiskResult:
        reasons: list[str] = []
        if (
            verification.analysis_id != request.analysis_id
            or verification.decision != VerificationDecision.VERIFIED
            or verification.verified_at != request.as_of_time
        ):
            reasons.append("VERIFICATION_REJECTED")
        conservative_entry = request.entry_price * Decimal("1.001")
        stop_distance = conservative_entry - request.stop_price
        reward = request.take_profit_price - conservative_entry
        reward_risk = reward / stop_distance if stop_distance > 0 else None
        if stop_distance <= 0:
            reasons.append("STOP_INVALID")
        if reward_risk is None or reward_risk < Decimal("1.5"):
            reasons.append("REWARD_RISK_INSUFFICIENT")
        volatility = verification.technical_volatility
        if volatility is None or volatility > Decimal("0.10"):
            reasons.append("VOLATILITY_LIMIT_EXCEEDED")
        if request.drawdown >= Decimal("0.08"):
            reasons.append("DRAWDOWN_LIMIT_EXCEEDED")
        if request.current_gross_exposure >= request.nav * Decimal("0.50"):
            reasons.append("EXPOSURE_LIMIT_EXCEEDED")
        sizing = None
        if not reasons:
            sizing = self._sizing.calculate_sizing(
                nav=request.nav,
                adjusted_risk_budget=request.nav
                * Decimal("0.0025")
                * Decimal(str(verification.quantitative_confidence)),
                reference_price=request.entry_price,
                stop_price=request.stop_price,
                available_cash=request.available_cash,
                current_symbol_exposure=request.current_symbol_exposure,
                current_gross_exposure=request.current_gross_exposure,
                max_symbol_allocation_pct=Decimal("0.15"),
                max_total_exposure_pct=Decimal("0.50"),
            )
            if not sizing.is_valid:
                reasons.append(sizing.rejection_reason or "SIZING_REJECTED")
        allow = not reasons and sizing is not None and sizing.is_valid
        return AnalysisRiskResult(
            analysis_id=request.analysis_id,
            allow_trade=allow,
            approved_quantity=sizing.approved_quantity if allow and sizing else Decimal("0"),
            approved_notional=sizing.approved_notional if allow and sizing else Decimal("0"),
            reward_risk_ratio=reward_risk,
            risk_level=(
                "HIGH"
                if reasons
                else "MEDIUM"
                if volatility is not None and volatility > Decimal("0.05")
                else "LOW"
            ),
            reason_codes=tuple(dict.fromkeys(reasons)),
            evaluated_at=request.as_of_time,
        )
