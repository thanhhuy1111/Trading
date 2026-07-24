"""Offline Phase 6 specialist-agent evidence and failure-boundary tests."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import TypeVar

import pytest
from pydantic import BaseModel, ValidationError

from packages.agents.analysis_evidence import (
    DERIVATIVES_EVIDENCE_NAMES,
    QUANTITATIVE_EVIDENCE_NAMES,
    TECHNICAL_EVIDENCE_NAMES,
    AnalysisEvidenceCategory,
    AnalysisEvidenceRecord,
    AnalysisEvidenceRegistry,
    AnalysisEvidenceStatus,
)
from packages.agents.specialists import (
    DerivativesSpecialistAgent,
    EvidenceInterpretationAgent,
    NumericEvidenceClaim,
    QuantitativeSpecialistAgent,
    SpecialistAgentName,
    SpecialistAssessment,
    SpecialistLLMOutput,
    SpecialistRequest,
    SpecialistStatus,
    TechnicalSpecialistAgent,
    register_specialist_prompts,
)
from packages.llm.prompt_registry import PromptRegistry
from packages.llm.structured_provider import (
    LLMCallTelemetry,
    LLMProviderStatus,
    StructuredLLMRequest,
    StructuredLLMResult,
)
from packages.registries.registry import ArtifactRegistry
from packages.retraining.xgboost_approval import XGBoostApprovalService
from packages.retraining.xgboost_contracts import TargetClass
from packages.retraining.xgboost_runtime import (
    ApprovedModelRepository,
    XGBoostRuntime,
    XGBoostRuntimeRequest,
)
from tests.unit.test_xgboost_approval import EVALUATED_AT, _dataset_and_training
from tests.unit.test_xgboost_runtime import _snapshot

T0 = datetime(2026, 7, 24, 8, tzinfo=timezone.utc)
OutputT = TypeVar("OutputT", bound=BaseModel)


class StaticProvider:
    def __init__(
        self,
        *,
        output: SpecialistLLMOutput | None,
        status: LLMProviderStatus = LLMProviderStatus.SUCCESS,
        reasons: tuple[str, ...] = (),
        raises: bool = False,
    ) -> None:
        self.output = output
        self.status = status
        self.reasons = reasons
        self.raises = raises
        self.requests: list[StructuredLLMRequest] = []

    async def generate(
        self,
        request: StructuredLLMRequest,
        output_model: type[OutputT],
    ) -> StructuredLLMResult[OutputT]:
        self.requests.append(request)
        if self.raises:
            raise RuntimeError("simulated provider failure")
        return StructuredLLMResult[OutputT](
            status=self.status,
            output=self.output,  # type: ignore[arg-type]
            telemetry=LLMCallTelemetry(
                request_id=request.request_id,
                provider="mock",
                model_id="configured-model",
                served_model_version="served-model-v1",
                prompt_name=request.prompt_name,
                prompt_version=request.prompt_version,
                prompt_checksum="a" * 64,
                attempts=1,
                latency_ms=2.0,
            ),
            reason_codes=self.reasons,
        )


def _record(
    evidence_id: str,
    *,
    category: AnalysisEvidenceCategory,
    name: str,
    value: str = "1",
    analysis_id: str = "analysis-1",
    status: AnalysisEvidenceStatus = AnalysisEvidenceStatus.VALID,
    available_at: datetime = T0,
    source_id: str = "feature_snapshot:1",
) -> AnalysisEvidenceRecord:
    feature_set, feature_set_version = {
        AnalysisEvidenceCategory.TECHNICAL: ("standard_v1", "1.0.0"),
        AnalysisEvidenceCategory.DERIVATIVES: ("derivatives_v1", "1.0.0"),
        AnalysisEvidenceCategory.QUANTITATIVE: ("xgboost_direction", "1.0.0"),
    }[category]
    unit = {
        AnalysisEvidenceCategory.TECHNICAL: {
            "return_1p": "ratio",
            "return_3p": "ratio",
            "return_5p": "ratio",
            "high_low_range": "ratio",
            "ema_20_slope": "ratio",
            "adx_14": "index",
            "rsi_14": "index",
            "atr_14": "quote_currency",
            "volatility_20": "ratio",
            "relative_volume_20": "ratio",
            "zscore_20": "index",
            "bollinger_pos_20": "ratio",
            "donchian_breakout_20": "signal",
        },
        AnalysisEvidenceCategory.DERIVATIVES: {
            "funding_rate": "ratio",
            "open_interest": "base_asset",
            "long_short_account_ratio": "ratio",
            "taker_buy_sell_ratio": "ratio",
            "futures_basis_bps": "basis_points",
            "funding_rate_zscore_20": "index",
            "open_interest_roc_12": "ratio",
            "futures_basis_momentum_6": "basis_points",
        },
        AnalysisEvidenceCategory.QUANTITATIVE: {
            name: "probability" for name in QUANTITATIVE_EVIDENCE_NAMES
        },
    }[category][name]
    return AnalysisEvidenceRecord(
        evidence_id=evidence_id,
        analysis_id=analysis_id,
        category=category,
        feature_set=feature_set,
        feature_set_version=feature_set_version,
        name=name,
        numeric_value=Decimal(value),
        unit=unit,
        observed_at=T0 - timedelta(minutes=1),
        available_at=available_at,
        source_id=source_id,
        status=status,
    )


def _register_complete(
    registry: AnalysisEvidenceRegistry,
    category: AnalysisEvidenceCategory,
) -> tuple[str, ...]:
    names = {
        AnalysisEvidenceCategory.TECHNICAL: TECHNICAL_EVIDENCE_NAMES,
        AnalysisEvidenceCategory.DERIVATIVES: DERIVATIVES_EVIDENCE_NAMES,
        AnalysisEvidenceCategory.QUANTITATIVE: QUANTITATIVE_EVIDENCE_NAMES,
    }[category]
    ids: list[str] = []
    for name in sorted(names):
        evidence_id = (
            f"analysis-1:quantitative:{name}"
            if category == AnalysisEvidenceCategory.QUANTITATIVE
            else f"{category.value.lower()}:{name}"
        )
        registry.register(
            _record(
                evidence_id,
                category=category,
                name=name,
                value=(
                    {
                        "bearish_probability": "0.3333333333333333",
                        "neutral_probability": "0.3333333333333333",
                        "bullish_probability": "0.3333333333333333",
                        "confidence": "0.3333333333333333",
                    }[name]
                    if category == AnalysisEvidenceCategory.QUANTITATIVE
                    else "1"
                ),
                source_id=(
                    "approved_runtime:xgb:snapshot"
                    if category == AnalysisEvidenceCategory.QUANTITATIVE
                    else f"feature_snapshot:{category.value.lower()}"
                ),
            )
        )
        ids.append(evidence_id)
    return tuple(ids)


def _request(
    evidence_ids: tuple[str, ...],
    quantitative_ids: tuple[str, ...] = (),
) -> SpecialistRequest:
    return SpecialistRequest(
        analysis_id="analysis-1",
        symbol="BTC/USDT",
        timeframe="4h",
        as_of_time=T0,
        evidence_ids=evidence_ids,
        quantitative_evidence_ids=quantitative_ids,
    )


def test_specialist_prompts_and_evidence_schemas_are_exact() -> None:
    prompts = PromptRegistry()
    register_specialist_prompts(prompts)
    assert {prompt.name for prompt in prompts.all()} == {
        "technical_interpretation",
        "derivatives_interpretation",
    }
    with pytest.raises(ValidationError, match="not allowed"):
        AnalysisEvidenceRecord(
            evidence_id="raw",
            analysis_id="analysis-1",
            category=AnalysisEvidenceCategory.TECHNICAL,
            feature_set="standard_v1",
            feature_set_version="1.0.0",
            name="raw_candles",
            numeric_value=Decimal("1"),
            unit="index",
            observed_at=T0,
            available_at=T0,
            source_id="feature_snapshot:1",
        )
    with pytest.raises(ValidationError):
        AnalysisEvidenceRecord(
            evidence_id="empty",
            analysis_id="analysis-1",
            category=AnalysisEvidenceCategory.TECHNICAL,
            name="rsi_14",
            numeric_value=Decimal("1"),
            unit=" ",
            observed_at=T0,
            available_at=T0,
            source_id="source",
        )


async def test_technical_requires_complete_features_and_quantitative_context() -> None:
    registry = AnalysisEvidenceRegistry()
    technical_ids = _register_complete(registry, AnalysisEvidenceCategory.TECHNICAL)
    quantitative_ids = _register_complete(
        registry,
        AnalysisEvidenceCategory.QUANTITATIVE,
    )
    rsi_id = "technical:rsi_14"
    output = SpecialistLLMOutput(
        stance=TargetClass.BULLISH,
        summary="Momentum is positive but not overbought.",
        evidence_ids=(rsi_id,),
        numeric_claims=(
            NumericEvidenceClaim(
                name="rsi_14",
                value=Decimal("1"),
                unit="index",
                evidence_id=rsi_id,
            ),
        ),
        invalidating_conditions=("rsi_below_threshold",),
    )
    provider = StaticProvider(output=output)
    result = await TechnicalSpecialistAgent(
        evidence=registry,
        provider=provider,
    ).assess(_request(technical_ids, quantitative_ids))
    assert result.status == SpecialistStatus.AVAILABLE
    assert result.confidence is None
    assert "raw_candles" not in provider.requests[0].variables["evidence_json"]

    missing_quant = await TechnicalSpecialistAgent(
        evidence=registry,
        provider=provider,
    ).assess(_request(technical_ids))
    assert missing_quant.status == SpecialistStatus.UNAVAILABLE
    assert provider.requests.__len__() == 1


async def test_derivatives_requires_complete_schema_and_rejects_fabricated_claim() -> None:
    registry = AnalysisEvidenceRegistry()
    derivatives_ids = _register_complete(
        registry,
        AnalysisEvidenceCategory.DERIVATIVES,
    )
    forged = StaticProvider(
        output=SpecialistLLMOutput(
            stance=TargetClass.BEARISH,
            summary="Positioning is bearish.",
            evidence_ids=("derivatives:funding_rate",),
            numeric_claims=(
                NumericEvidenceClaim(
                    name="funding_rate",
                    value=Decimal("0.9"),
                    unit="index",
                    evidence_id="derivatives:funding_rate",
                ),
            ),
        )
    )
    result = await DerivativesSpecialistAgent(
        evidence=registry,
        provider=forged,
    ).assess(_request(derivatives_ids))
    assert result.reason_codes == ("LLM_EVIDENCE_CLAIM_INVALID",)
    with pytest.raises(ValidationError, match="numeric values"):
        SpecialistLLMOutput(
            stance=TargetClass.BEARISH,
            summary="funding_09 v2 iso8601 1e3",
            evidence_ids=("derivatives:funding_rate",),
        )
    for bypass in (
        "Positioning is ½ bearish.",
        "Regime is Ⅳ.",
        "Signal is 四.",
        "one half",
        "eleven percent",
        "seventy percent",
        "fourteen basis points",
    ):
        with pytest.raises(ValidationError, match="numeric values"):
            SpecialistLLMOutput(
                stance=TargetClass.BEARISH,
                summary=bypass,
                evidence_ids=("derivatives:funding_rate",),
            )


async def test_invalid_evidence_provider_failure_and_mapping_fail_closed() -> None:
    for record, reason in (
        (
            _record(
                "stale",
                category=AnalysisEvidenceCategory.TECHNICAL,
                name="rsi_14",
                status=AnalysisEvidenceStatus.STALE,
            ),
            "EVIDENCE_STALE",
        ),
        (
            _record(
                "future",
                category=AnalysisEvidenceCategory.TECHNICAL,
                name="rsi_14",
                available_at=T0 + timedelta(seconds=1),
            ),
            "EVIDENCE_LOOKAHEAD_VIOLATION",
        ),
    ):
        registry = AnalysisEvidenceRegistry()
        registry.register(record)
        provider = StaticProvider(output=None, status=LLMProviderStatus.ERROR, reasons=("x",))
        result = await TechnicalSpecialistAgent(
            evidence=registry,
            provider=provider,
        ).assess(_request((record.evidence_id,)))
        assert result.reason_codes == (reason,)
        assert provider.requests == []

    registry = AnalysisEvidenceRegistry()
    derivative_ids = _register_complete(
        registry,
        AnalysisEvidenceCategory.DERIVATIVES,
    )
    exploding = StaticProvider(output=None, raises=True)
    failed = await DerivativesSpecialistAgent(
        evidence=registry,
        provider=exploding,
    ).assess(_request(derivative_ids))
    assert failed.reason_codes == ("LLM_PROVIDER_CALL_FAILED",)
    with pytest.raises(ValueError, match="SPECIALIST_AGENT_CATEGORY_MISMATCH"):
        EvidenceInterpretationAgent(
            agent_name=SpecialistAgentName.TECHNICAL,
            category=AnalysisEvidenceCategory.DERIVATIVES,
            prompt_name="x",
            prompt_version="1",
            evidence=registry,
            provider=exploding,
        )
    with pytest.raises(ValidationError, match="cannot fabricate"):
        SpecialistAssessment(
            analysis_id="analysis-1",
            agent_name=SpecialistAgentName.TECHNICAL,
            status=SpecialistStatus.UNAVAILABLE,
            risk_factors=("fabricated",),
            reason_codes=("SAFE",),
        )
    with pytest.raises(ValidationError, match="contradictory"):
        SpecialistAssessment(
            analysis_id="analysis-1",
            agent_name=SpecialistAgentName.QUANTITATIVE,
            status=SpecialistStatus.AVAILABLE,
            direction=TargetClass.BEARISH,
            probabilities=(0.1, 0.2, 0.7),
            confidence=0.7,
            confidence_source="missing",
            summary="Contradictory output.",
            evidence_ids=("other",),
            numeric_claims=tuple(
                NumericEvidenceClaim(
                    name=name,
                    value=Decimal("0"),
                    unit="wrong",
                    evidence_id="missing",
                )
                for name in sorted(QUANTITATIVE_EVIDENCE_NAMES)
            ),
            model_id="model",
            as_of_time=T0,
        )


@pytest.fixture(scope="module")
def approved_runtime(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("phase6-runtime")
    dataset, training = _dataset_and_training(strong=True)
    service = XGBoostApprovalService(ArtifactRegistry("phase6"), root)
    published = service.evaluate_and_publish(
        model_name="xgb_btcusdt_4h",
        model_version="1",
        dataset=dataset,
        training=training,
        evaluated_at=EVALUATED_AT,
        code_commit="phase6-test",
    )
    assert published.receipt.status.value == "APPROVED"
    runtime = XGBoostRuntime(ApprovedModelRepository(service))
    request = XGBoostRuntimeRequest(
        model_name="xgb_btcusdt_4h",
        model_version="1",
        snapshot=_snapshot(dataset),
    )
    return runtime, request


def test_quantitative_agent_invokes_approved_runtime_and_publishes_bound_evidence(
    approved_runtime: tuple[XGBoostRuntime, XGBoostRuntimeRequest],
) -> None:
    runtime, request = approved_runtime
    evidence = AnalysisEvidenceRegistry()
    result = QuantitativeSpecialistAgent(evidence, runtime).assess(
        analysis_id="analysis-quant",
        as_of_time=request.snapshot.as_of_time,
        runtime_request=request,
    )
    assert result.status == SpecialistStatus.AVAILABLE
    assert result.confidence_source == "analysis-quant:quantitative:confidence"
    assert len(result.numeric_claims) == 4
    for evidence_id in result.evidence_ids:
        record = evidence.get(evidence_id)
        assert record is not None
        assert record.source_id.startswith("approved_runtime:")


def test_quantitative_forged_runtime_and_unapproved_source_are_rejected(
    tmp_path: Path,
    approved_runtime: tuple[XGBoostRuntime, XGBoostRuntimeRequest],
) -> None:
    runtime, request = approved_runtime

    class ForgedRuntime(XGBoostRuntime):
        pass

    with pytest.raises(TypeError, match="APPROVED_XGBOOST_RUNTIME_REQUIRED"):
        QuantitativeSpecialistAgent(
            AnalysisEvidenceRegistry(),
            ForgedRuntime(runtime._repository),  # type: ignore[attr-defined]
        )

    class FakeRepository:
        def resolve(self, model_name: str, model_version: str | None):
            raise AssertionError("must never be called")

    with pytest.raises(TypeError, match="APPROVED_MODEL_REPOSITORY_REQUIRED"):
        XGBoostRuntime(FakeRepository())  # type: ignore[arg-type]

    direct_registry = ArtifactRegistry("unapproved")
    service = XGBoostApprovalService(direct_registry, tmp_path)
    unavailable_runtime = XGBoostRuntime(ApprovedModelRepository(service))
    result = QuantitativeSpecialistAgent(
        AnalysisEvidenceRegistry(),
        unavailable_runtime,
    ).assess(
        analysis_id="analysis-quant",
        as_of_time=request.snapshot.as_of_time,
        runtime_request=request,
    )
    assert result.status == SpecialistStatus.UNAVAILABLE
    assert result.reason_codes == ("NO_APPROVED_MODEL",)
