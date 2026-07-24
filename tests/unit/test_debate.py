"""Offline bounded debate tests."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TypeVar

import pytest
from pydantic import BaseModel, ValidationError

from packages.agents.analysis_evidence import (
    AnalysisEvidenceCategory,
    AnalysisEvidenceRecord,
    AnalysisEvidenceRegistry,
    AnalysisEvidenceStatus,
)
from packages.agents.debate import (
    BullBearDebateOrchestrator,
    DebateStatus,
    DebateTranscript,
    DebateTranscriptStore,
    DebateTurn,
    DebateTurnStatus,
)
from packages.agents.specialists import NumericEvidenceClaim, SpecialistLLMOutput
from packages.llm.structured_provider import (
    LLMCallTelemetry,
    LLMProviderStatus,
    StructuredLLMRequest,
    StructuredLLMResult,
)
from packages.retraining.xgboost_contracts import TargetClass

T0 = datetime(2026, 7, 24, 8, tzinfo=timezone.utc)
OutputT = TypeVar("OutputT", bound=BaseModel)


class QueueProvider:
    def __init__(self, outputs: list[SpecialistLLMOutput | None], raises: bool = False):
        self.outputs = outputs
        self.raises = raises
        self.calls = 0
        self.requests: list[StructuredLLMRequest] = []

    async def generate(self, request: StructuredLLMRequest, output_model: type[OutputT]):
        self.calls += 1
        self.requests.append(request)
        if self.raises:
            raise RuntimeError("offline failure")
        output = self.outputs[min(self.calls - 1, len(self.outputs) - 1)]
        return StructuredLLMResult(
            status=LLMProviderStatus.SUCCESS if output else LLMProviderStatus.UNAVAILABLE,
            output=output,
            telemetry=LLMCallTelemetry(
                request_id=request.request_id,
                provider="mock",
                model_id="configured",
                served_model_version="served",
                prompt_name=request.prompt_name,
                prompt_version=request.prompt_version,
                prompt_checksum="a" * 64,
                attempts=1,
                input_tokens=10,
                output_tokens=5,
                latency_ms=2,
            ),
            reason_codes=() if output else ("OFFLINE",),
        )


def _evidence(status: AnalysisEvidenceStatus = AnalysisEvidenceStatus.VALID):
    registry = AnalysisEvidenceRegistry()
    registry.register(
        AnalysisEvidenceRecord(
            evidence_id="analysis-1:technical:rsi",
            analysis_id="analysis-1",
            category=AnalysisEvidenceCategory.TECHNICAL,
            feature_set="standard_v1",
            feature_set_version="1.0.0",
            name="rsi_14",
            numeric_value=Decimal("52"),
            unit="index",
            observed_at=T0 - timedelta(minutes=1),
            available_at=T0,
            source_id="snapshot:technical",
            status=status,
        )
    )
    return registry


def _output(side: TargetClass, summary: str) -> SpecialistLLMOutput:
    return SpecialistLLMOutput(
        stance=side,
        summary=summary,
        evidence_ids=("analysis-1:technical:rsi",),
        numeric_claims=(
            NumericEvidenceClaim(
                name="rsi_14",
                value=Decimal("52"),
                unit="index",
                evidence_id="analysis-1:technical:rsi",
            ),
        ),
        invalidating_conditions=("Momentum reverses.",),
    )


async def test_debate_is_bounded_evidence_only_and_persisted() -> None:
    bull = QueueProvider([_output(TargetClass.BULLISH, "Momentum supports buyers.")])
    bear = QueueProvider([_output(TargetClass.BEARISH, "Momentum can still reverse.")])
    store = DebateTranscriptStore()
    transcript = await BullBearDebateOrchestrator(
        evidence=_evidence(),
        bull_provider=bull,
        bear_provider=bear,
        store=store,
    ).run(
        analysis_id="analysis-1",
        as_of_time=T0,
        evidence_ids=("analysis-1:technical:rsi",),
    )
    assert transcript.status == DebateStatus.COMPLETE
    assert len(transcript.turns) == 4
    assert bull.calls == bear.calls == 2
    assert all(turn.input_tokens == 10 for turn in transcript.turns)
    assert store.get("analysis-1") == transcript
    assert bull.requests[0].variables["assigned_side"] == "BULL"
    assert bear.requests[0].variables["assigned_side"] == "BEAR"
    repeated = await BullBearDebateOrchestrator(
        evidence=_evidence(),
        bull_provider=bull,
        bear_provider=bear,
        store=store,
    ).run(
        analysis_id="analysis-1",
        as_of_time=T0,
        evidence_ids=("analysis-1:technical:rsi",),
    )
    assert repeated == transcript
    assert bull.calls == bear.calls == 2
    with pytest.raises(ValueError, match="DEBATE_REQUEST_MISMATCH"):
        await BullBearDebateOrchestrator(
            evidence=_evidence(),
            bull_provider=bull,
            bear_provider=bear,
            store=store,
        ).run(
            analysis_id="analysis-1",
            as_of_time=T0 + timedelta(days=1),
            evidence_ids=("missing",),
        )


async def test_duplicate_wrong_side_and_missing_evidence_are_rejected() -> None:
    duplicate = _output(TargetClass.BULLISH, "Same thesis.")
    transcript = await BullBearDebateOrchestrator(
        evidence=_evidence(),
        bull_provider=QueueProvider([duplicate]),
        bear_provider=QueueProvider([duplicate]),
        store=DebateTranscriptStore(),
    ).run(
        analysis_id="analysis-1",
        as_of_time=T0,
        evidence_ids=("analysis-1:technical:rsi",),
    )
    assert transcript.turns[1].reason_codes == ("DEBATE_ARGUMENT_INVALID",)
    assert transcript.turns[2].reason_codes == ("DEBATE_ARGUMENT_DUPLICATE",)
    assert transcript.status == DebateStatus.PARTIAL

    failed = await BullBearDebateOrchestrator(
        evidence=_evidence(),
        bull_provider=QueueProvider([duplicate]),
        bear_provider=QueueProvider([duplicate]),
        store=DebateTranscriptStore(),
    ).run(analysis_id="analysis-1", as_of_time=T0, evidence_ids=("missing",))
    assert failed.status == DebateStatus.FAILED
    assert failed.reason_codes == ("EVIDENCE_NOT_FOUND",)


async def test_provider_failure_and_stale_evidence_fail_safely() -> None:
    transcript = await BullBearDebateOrchestrator(
        evidence=_evidence(),
        bull_provider=QueueProvider([], raises=True),
        bear_provider=QueueProvider([], raises=True),
        store=DebateTranscriptStore(),
        maximum_rounds=1,
    ).run(
        analysis_id="analysis-1",
        as_of_time=T0,
        evidence_ids=("analysis-1:technical:rsi",),
    )
    assert transcript.status == DebateStatus.FAILED
    assert all(turn.status == DebateTurnStatus.FAILED for turn in transcript.turns)

    stale = await BullBearDebateOrchestrator(
        evidence=_evidence(AnalysisEvidenceStatus.STALE),
        bull_provider=QueueProvider([], raises=True),
        bear_provider=QueueProvider([], raises=True),
        store=DebateTranscriptStore(),
    ).run(
        analysis_id="analysis-1",
        as_of_time=T0,
        evidence_ids=("analysis-1:technical:rsi",),
    )
    assert stale.status == DebateStatus.FAILED
    assert stale.reason_codes == ("EVIDENCE_INVALID",)

    naive = await BullBearDebateOrchestrator(
        evidence=_evidence(),
        bull_provider=QueueProvider([], raises=True),
        bear_provider=QueueProvider([], raises=True),
        store=DebateTranscriptStore(),
    ).run(
        analysis_id="analysis-1",
        as_of_time=T0.replace(tzinfo=None),
        evidence_ids=("analysis-1:technical:rsi",),
    )
    assert naive.status == DebateStatus.FAILED
    assert naive.as_of_time is None
    assert naive.reason_codes == ("ANALYSIS_AS_OF_INVALID",)


async def test_empty_invalidating_conditions_are_rejected() -> None:
    invalid = SpecialistLLMOutput(
        stance=TargetClass.BULLISH,
        summary="Momentum supports buyers.",
        evidence_ids=("analysis-1:technical:rsi",),
        numeric_claims=(
            NumericEvidenceClaim(
                name="rsi_14",
                value=Decimal("52"),
                unit="index",
                evidence_id="analysis-1:technical:rsi",
            ),
        ),
    )
    transcript = await BullBearDebateOrchestrator(
        evidence=_evidence(),
        bull_provider=QueueProvider([invalid]),
        bear_provider=QueueProvider([], raises=True),
        store=DebateTranscriptStore(),
        maximum_rounds=1,
    ).run(
        analysis_id="analysis-1",
        as_of_time=T0,
        evidence_ids=("analysis-1:technical:rsi",),
    )
    assert transcript.status == DebateStatus.FAILED
    assert transcript.turns[0].reason_codes == ("DEBATE_ARGUMENT_INVALID",)


async def test_cancelled_run_releases_reservation() -> None:
    class CancelProvider:
        async def generate(self, request, output_model):
            raise asyncio.CancelledError

    store = DebateTranscriptStore()
    with pytest.raises(asyncio.CancelledError):
        await BullBearDebateOrchestrator(
            evidence=_evidence(),
            bull_provider=CancelProvider(),
            bear_provider=CancelProvider(),
            store=store,
            maximum_rounds=1,
        ).run(
            analysis_id="analysis-1",
            as_of_time=T0,
            evidence_ids=("analysis-1:technical:rsi",),
        )
    recovered = await BullBearDebateOrchestrator(
        evidence=_evidence(),
        bull_provider=QueueProvider([_output(TargetClass.BULLISH, "Buyers recover.")]),
        bear_provider=QueueProvider([_output(TargetClass.BEARISH, "Sellers recover.")]),
        store=store,
        maximum_rounds=1,
    ).run(
        analysis_id="analysis-1",
        as_of_time=T0,
        evidence_ids=("analysis-1:technical:rsi",),
    )
    assert recovered.status == DebateStatus.COMPLETE


def test_transcript_rejects_noncanonical_round_structure() -> None:
    turn = DebateTurn(
        round_number=1,
        side="BULL",
        status=DebateTurnStatus.FAILED,
        prompt_version="1.0.0",
        reason_codes=("FAILED",),
    )
    with pytest.raises(ValidationError, match="canonical round"):
        DebateTranscript(
            analysis_id="analysis-1",
            request_fingerprint="a" * 64,
            as_of_time=T0,
            status=DebateStatus.FAILED,
            maximum_rounds=1,
            turns=(turn, turn),
            reason_codes=("FAILED",),
        )
