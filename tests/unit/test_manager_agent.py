"""Phase 9 deterministic manager tests."""

from decimal import Decimal

from packages.agents.manager import (
    ManagerAgent,
    ManagerRecommendation,
    ManagerSnapshotStore,
)
from packages.agents.specialists import SpecialistAgentName
from packages.agents.verification_risk import AnalysisRiskEngine, VerificationAgent
from packages.retraining.xgboost_contracts import TargetClass
from tests.unit.test_verification_risk import (
    T0,
    _assessments,
    _debate,
    _registry,
    _risk_request,
)


def _inputs():
    assessments = _assessments()
    debate = _debate()
    verifier = VerificationAgent(_registry())
    verification = verifier.verify(
        analysis_id="analysis-1",
        as_of_time=T0,
        assessments=assessments,
        debate=debate,
    )
    risk_engine = AnalysisRiskEngine(verifier)
    risk_request = _risk_request()
    risk = risk_engine.evaluate(risk_request, verification)
    return (
        assessments,
        debate,
        verifier,
        risk_engine,
        verification,
        risk_request,
        risk,
    )


def test_manager_emits_persisted_long_from_verified_inputs() -> None:
    (
        assessments,
        debate,
        verifier,
        risk_engine,
        verification,
        risk_request,
        risk,
    ) = _inputs()
    store = ManagerSnapshotStore()
    manager = ManagerAgent(store, verifier, risk_engine)
    snapshot = manager.decide(
        analysis_id="analysis-1",
        as_of_time=T0,
        assessments=assessments,
        debate=debate,
        verification=verification,
        risk=risk,
        risk_request=risk_request,
    )
    assert snapshot.recommendation == ManagerRecommendation.LONG
    assert snapshot.confidence == 0.7
    assert store.get("analysis-1") == snapshot
    assert manager.decide(
        analysis_id="analysis-1",
        as_of_time=T0,
        assessments=assessments,
        debate=debate,
        verification=verification,
        risk=risk,
        risk_request=risk_request,
    ) == snapshot
    assert manager.decide(
        analysis_id="analysis-1",
        as_of_time=T0,
        assessments=tuple(reversed(assessments)),
        debate=debate,
        verification=verification,
        risk=risk,
        risk_request=risk_request,
    ) == snapshot


def test_manager_never_bypasses_verification_or_risk() -> None:
    (
        assessments,
        debate,
        verifier,
        risk_engine,
        verification,
        risk_request,
        risk,
    ) = _inputs()
    rejected_risk = risk.model_copy(
        update={
            "allow_trade": False,
            "approved_quantity": Decimal("0"),
            "approved_notional": Decimal("0"),
            "reason_codes": ("RISK_REJECTED",),
        }
    )
    no_decision = ManagerAgent(
        ManagerSnapshotStore(),
        verifier,
        risk_engine,
    ).decide(
        analysis_id="analysis-1",
        as_of_time=T0,
        assessments=assessments,
        debate=debate,
        verification=verification,
        risk=rejected_risk,
        risk_request=risk_request,
    )
    assert no_decision.recommendation == ManagerRecommendation.NO_DECISION
    assert no_decision.confidence is None
    assert no_decision.evidence_ids == ()
    replayed_request = ManagerAgent(
        ManagerSnapshotStore(),
        verifier,
        risk_engine,
    ).decide(
        analysis_id="analysis-1",
        as_of_time=T0,
        assessments=assessments,
        debate=debate,
        verification=verification,
        risk=risk,
        risk_request=risk_request.model_copy(
            update={"entry_price": Decimal("200")}
        ),
    )
    assert replayed_request.recommendation == ManagerRecommendation.NO_DECISION
    assert "RISK_REJECTED" in replayed_request.reason_codes


def test_bearish_quantitative_tie_cannot_create_unapproved_short() -> None:
    (
        assessments,
        debate,
        verifier,
        risk_engine,
        verification,
        risk_request,
        risk,
    ) = _inputs()
    bearish = tuple(
        assessment.model_copy(
            update={"direction": TargetClass.BEARISH}
        )
        if assessment.agent_name == SpecialistAgentName.QUANTITATIVE
        else assessment
        for assessment in assessments
    )
    snapshot = ManagerAgent(
        ManagerSnapshotStore(),
        verifier,
        risk_engine,
    ).decide(
        analysis_id="analysis-1",
        as_of_time=T0,
        assessments=bearish,
        debate=debate,
        verification=verification,
        risk=risk,
        risk_request=risk_request,
    )
    assert snapshot.recommendation in {
        ManagerRecommendation.LONG,
        ManagerRecommendation.NO_DECISION,
    }
    assert snapshot.recommendation != ManagerRecommendation.SHORT
    assert snapshot.recommendation == ManagerRecommendation.NO_DECISION


def test_manager_naive_time_fails_closed_without_crashing() -> None:
    (
        assessments,
        debate,
        verifier,
        risk_engine,
        verification,
        risk_request,
        risk,
    ) = _inputs()
    snapshot = ManagerAgent(
        ManagerSnapshotStore(),
        verifier,
        risk_engine,
    ).decide(
        analysis_id="analysis-1",
        as_of_time=T0.replace(tzinfo=None),
        assessments=assessments,
        debate=debate,
        verification=verification,
        risk=risk,
        risk_request=risk_request,
    )
    assert snapshot.recommendation == ManagerRecommendation.NO_DECISION
    assert snapshot.as_of_time is None
    assert snapshot.reason_codes == ("ANALYSIS_AS_OF_INVALID",)
