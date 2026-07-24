"""Phase 8 deterministic verification and risk tests."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.agents.analysis_evidence import (
    AnalysisEvidenceCategory,
    AnalysisEvidenceRecord,
    AnalysisEvidenceRegistry,
)
from packages.agents.debate import (
    DebateSide,
    DebateStatus,
    DebateTranscript,
    DebateTurn,
    DebateTurnStatus,
)
from packages.agents.specialists import (
    NumericEvidenceClaim,
    SpecialistAgentName,
    SpecialistAssessment,
    SpecialistLLMOutput,
    SpecialistStatus,
)
from packages.agents.verification_risk import (
    AnalysisRiskEngine,
    AnalysisRiskRequest,
    VerificationAgent,
    VerificationDecision,
)
from packages.retraining.xgboost_contracts import TargetClass

T0 = datetime(2026, 7, 24, 8, tzinfo=timezone.utc)
EVIDENCE_ID = "analysis-1:technical:rsi"


def _registry(
    available_at: datetime = T0,
    volatility: str = "0.03",
) -> AnalysisEvidenceRegistry:
    registry = AnalysisEvidenceRegistry()
    registry.register(
        AnalysisEvidenceRecord(
            evidence_id=EVIDENCE_ID,
            analysis_id="analysis-1",
            category=AnalysisEvidenceCategory.TECHNICAL,
            feature_set="standard_v1",
            feature_set_version="1.0.0",
            name="rsi_14",
            numeric_value=Decimal("52"),
            unit="index",
            observed_at=T0 - timedelta(minutes=1),
            available_at=available_at,
            source_id="snapshot",
        )
    )
    registry.register(
        AnalysisEvidenceRecord(
            evidence_id="analysis-1:technical:volatility",
            analysis_id="analysis-1",
            category=AnalysisEvidenceCategory.TECHNICAL,
            feature_set="standard_v1",
            feature_set_version="1.0.0",
            name="volatility_20",
            numeric_value=Decimal(volatility),
            unit="ratio",
            observed_at=T0 - timedelta(minutes=1),
            available_at=available_at,
            source_id="snapshot",
        )
    )
    registry.register(
        AnalysisEvidenceRecord(
            evidence_id="analysis-1:derivatives:funding",
            analysis_id="analysis-1",
            category=AnalysisEvidenceCategory.DERIVATIVES,
            feature_set="derivatives_v1",
            feature_set_version="1.0.0",
            name="funding_rate",
            numeric_value=Decimal("0.001"),
            unit="ratio",
            observed_at=T0 - timedelta(minutes=1),
            available_at=available_at,
            source_id="snapshot:derivatives",
        )
    )
    for name, value in (
        ("bearish_probability", "0.1"),
        ("neutral_probability", "0.2"),
        ("bullish_probability", "0.7"),
        ("confidence", "0.7"),
    ):
        registry.register(
            AnalysisEvidenceRecord(
                evidence_id=f"analysis-1:quantitative:{name}",
                analysis_id="analysis-1",
                category=AnalysisEvidenceCategory.QUANTITATIVE,
                feature_set="xgboost_direction",
                feature_set_version="1.0.0",
                name=name,
                numeric_value=Decimal(value),
                unit="probability",
                observed_at=T0 - timedelta(minutes=1),
                available_at=available_at,
                source_id="approved_runtime:model:snapshot",
            )
        )
    return registry


def _assessment(direction: TargetClass = TargetClass.BULLISH) -> SpecialistAssessment:
    return SpecialistAssessment(
        analysis_id="analysis-1",
        agent_name=SpecialistAgentName.TECHNICAL,
        status=SpecialistStatus.AVAILABLE,
        direction=direction,
        summary="Momentum is constructive.",
        evidence_ids=(EVIDENCE_ID, "analysis-1:technical:volatility"),
        numeric_claims=(
            NumericEvidenceClaim(
                name="rsi_14",
                value=Decimal("52"),
                unit="index",
                evidence_id=EVIDENCE_ID,
            ),
            NumericEvidenceClaim(
                name="volatility_20",
                value=Decimal("0.03"),
                unit="ratio",
                evidence_id="analysis-1:technical:volatility",
            ),
        ),
        model_id="served",
        as_of_time=T0,
    )


def _assessments() -> tuple[SpecialistAssessment, ...]:
    technical = _assessment()
    derivatives = SpecialistAssessment(
        analysis_id="analysis-1",
        agent_name=SpecialistAgentName.DERIVATIVES,
        status=SpecialistStatus.AVAILABLE,
        direction=TargetClass.BULLISH,
        summary="Positioning is constructive.",
        evidence_ids=("analysis-1:derivatives:funding",),
        numeric_claims=(
            NumericEvidenceClaim(
                name="funding_rate",
                value=Decimal("0.001"),
                unit="ratio",
                evidence_id="analysis-1:derivatives:funding",
            ),
        ),
        model_id="served",
        as_of_time=T0,
    )
    probabilities = (0.1, 0.2, 0.7)
    quant_ids = tuple(
        f"analysis-1:quantitative:{name}"
        for name in (
            "bearish_probability",
            "neutral_probability",
            "bullish_probability",
            "confidence",
        )
    )
    quantitative = SpecialistAssessment(
        analysis_id="analysis-1",
        agent_name=SpecialistAgentName.QUANTITATIVE,
        status=SpecialistStatus.AVAILABLE,
        direction=TargetClass.BULLISH,
        probabilities=probabilities,
        confidence=0.7,
        confidence_source="analysis-1:quantitative:confidence",
        summary="Approved quantitative model prediction.",
        evidence_ids=quant_ids,
        numeric_claims=tuple(
            NumericEvidenceClaim(
                name=name,
                value=Decimal(value),
                unit="probability",
                evidence_id=f"analysis-1:quantitative:{name}",
            )
            for name, value in (
                ("bearish_probability", "0.1"),
                ("neutral_probability", "0.2"),
                ("bullish_probability", "0.7"),
                ("confidence", "0.7"),
            )
        ),
        model_id="approved",
        as_of_time=T0,
    )
    return technical, derivatives, quantitative


def _debate() -> DebateTranscript:
    turns = []
    for side, stance in (
        (DebateSide.BULL, TargetClass.BULLISH),
        (DebateSide.BEAR, TargetClass.BEARISH),
    ):
        turns.append(
            DebateTurn(
                round_number=1,
                side=side,
                status=DebateTurnStatus.ACCEPTED,
                output=SpecialistLLMOutput(
                    stance=stance,
                    summary="Momentum thesis remains conditional.",
                    evidence_ids=(EVIDENCE_ID,),
                    numeric_claims=(
                        NumericEvidenceClaim(
                            name="rsi_14",
                            value=Decimal("52"),
                            unit="index",
                            evidence_id=EVIDENCE_ID,
                        ),
                    ),
                    invalidating_conditions=("Momentum reverses.",),
                ),
                prompt_version="1.0.0",
            )
        )
    return DebateTranscript(
        analysis_id="analysis-1",
        request_fingerprint="a" * 64,
        as_of_time=T0,
        status=DebateStatus.COMPLETE,
        maximum_rounds=1,
        turns=tuple(turns),
    )


def _risk_request(**updates) -> AnalysisRiskRequest:
    values = {
        "analysis_id": "analysis-1",
        "as_of_time": T0,
        "nav": Decimal("10000"),
        "available_cash": Decimal("10000"),
        "entry_price": Decimal("100"),
        "stop_price": Decimal("95"),
        "take_profit_price": Decimal("110"),
        "current_symbol_exposure": Decimal("0"),
        "current_gross_exposure": Decimal("0"),
        "drawdown": Decimal("0.01"),
    }
    values.update(updates)
    return AnalysisRiskRequest(**values)


def test_verification_and_risk_can_approve_only_valid_inputs() -> None:
    verification = VerificationAgent(_registry()).verify(
        analysis_id="analysis-1",
        as_of_time=T0,
        assessments=_assessments(),
        debate=_debate(),
    )
    assert verification.decision == VerificationDecision.VERIFIED
    risk = AnalysisRiskEngine().evaluate(_risk_request(), verification)
    assert risk.allow_trade is True
    assert risk.approved_quantity > 0


def test_future_or_fabricated_evidence_is_rejected() -> None:
    future = VerificationAgent(
        _registry(T0 + timedelta(seconds=1))
    ).verify(
        analysis_id="analysis-1",
        as_of_time=T0,
        assessments=_assessments(),
        debate=_debate(),
    )
    assert future.decision == VerificationDecision.REJECTED
    assert "ASSESSMENT_EVIDENCE_INVALID" in future.reason_codes
    naive = VerificationAgent(_registry()).verify(
        analysis_id="analysis-1",
        as_of_time=T0.replace(tzinfo=None),
        assessments=_assessments(),
        debate=_debate(),
    )
    assert naive.decision == VerificationDecision.REJECTED
    assert naive.verified_at is None
    assert naive.reason_codes == ("ANALYSIS_AS_OF_INVALID",)


def test_verification_and_each_risk_gate_have_veto_authority() -> None:
    verified = VerificationAgent(_registry()).verify(
        analysis_id="analysis-1",
        as_of_time=T0,
        assessments=_assessments(),
        debate=_debate(),
    )
    rejected = VerificationAgent(_registry()).verify(
        analysis_id="analysis-1",
        as_of_time=T0,
        assessments=(),
        debate=_debate(),
    )
    for verification, request, reason in (
        (rejected, _risk_request(), "VERIFICATION_REJECTED"),
        (verified, _risk_request(stop_price=Decimal("101")), "STOP_INVALID"),
        (
            verified,
            _risk_request(take_profit_price=Decimal("102")),
            "REWARD_RISK_INSUFFICIENT",
        ),
        (
            verified,
            _risk_request(drawdown=Decimal("0.08")),
            "DRAWDOWN_LIMIT_EXCEEDED",
        ),
        (
            verified,
            _risk_request(current_gross_exposure=Decimal("5000")),
            "EXPOSURE_LIMIT_EXCEEDED",
        ),
    ):
        result = AnalysisRiskEngine().evaluate(request, verification)
        assert result.allow_trade is False
        assert result.approved_quantity == 0
        assert reason in result.reason_codes

    high_vol_verification = VerificationAgent(
        _registry(volatility="0.11")
    ).verify(
        analysis_id="analysis-1",
        as_of_time=T0,
        assessments=(
            _assessment().model_copy(
                update={
                    "numeric_claims": (
                        _assessment().numeric_claims[0],
                        NumericEvidenceClaim(
                            name="volatility_20",
                            value=Decimal("0.11"),
                            unit="ratio",
                            evidence_id="analysis-1:technical:volatility",
                        ),
                    )
                }
            ),
            *_assessments()[1:],
        ),
        debate=_debate(),
    )
    high_vol = AnalysisRiskEngine().evaluate(
        _risk_request(),
        high_vol_verification,
    )
    assert high_vol.allow_trade is False
    assert "VOLATILITY_LIMIT_EXCEEDED" in high_vol.reason_codes
