"""Bounded, evidence-only Bull–Bear debate orchestration."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from hashlib import sha256
from typing import Dict, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.agents.analysis_evidence import (
    AnalysisEvidenceRecord,
    AnalysisEvidenceRegistry,
    AnalysisEvidenceStatus,
)
from packages.agents.specialists import SpecialistLLMOutput
from packages.common.immutable import FrozenMapping
from packages.llm.prompt_registry import PromptDefinition, PromptRegistry
from packages.llm.structured_provider import (
    LLMProviderStatus,
    StructuredLLMProvider,
    StructuredLLMRequest,
)
from packages.retraining.xgboost_contracts import TargetClass

MAX_DEBATE_ROUNDS = 2


class DebateSide(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"


class DebateTurnStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class DebateStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class DebateTurn(BaseModel):
    model_config = ConfigDict(frozen=True)

    round_number: int = Field(ge=1, le=MAX_DEBATE_ROUNDS)
    side: DebateSide
    status: DebateTurnStatus
    output: Optional[SpecialistLLMOutput] = None
    configured_model_id: Optional[str] = None
    served_model_version: Optional[str] = None
    prompt_version: str
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    latency_ms: Optional[float] = Field(default=None, ge=0)
    reason_codes: Tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_turn(self) -> "DebateTurn":
        if self.status == DebateTurnStatus.ACCEPTED:
            if self.output is None or self.reason_codes:
                raise ValueError("accepted debate turn must contain valid output")
        elif self.output is not None or not self.reason_codes:
            raise ValueError("non-accepted debate turn cannot expose output")
        return self


class DebateTranscript(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    as_of_time: Optional[datetime] = None
    status: DebateStatus
    maximum_rounds: int = Field(ge=1, le=MAX_DEBATE_ROUNDS)
    turns: Tuple[DebateTurn, ...]
    reason_codes: Tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_transcript(self) -> "DebateTranscript":
        if self.as_of_time is not None and self.as_of_time.tzinfo is None:
            raise ValueError("debate timestamp must be timezone-aware")
        accepted_sides = {
            turn.side
            for turn in self.turns
            if turn.status == DebateTurnStatus.ACCEPTED
        }
        keys = tuple((turn.round_number, turn.side) for turn in self.turns)
        expected_order = tuple(
            (round_number, side)
            for round_number in range(1, self.maximum_rounds + 1)
            for side in (DebateSide.BULL, DebateSide.BEAR)
        )
        if (
            len(self.turns) > 2 * self.maximum_rounds
            or len(set(keys)) != len(keys)
            or keys != expected_order[: len(keys)]
        ):
            raise ValueError("debate turns violate bounded canonical round structure")
        if self.status == DebateStatus.COMPLETE and (
            accepted_sides != {DebateSide.BULL, DebateSide.BEAR}
            or self.reason_codes
            or self.as_of_time is None
        ):
            raise ValueError("complete debate requires accepted evidence from both sides")
        if self.status == DebateStatus.PARTIAL and (
            len(accepted_sides) != 1 or not self.reason_codes or self.as_of_time is None
        ):
            raise ValueError("partial debate requires one accepted side and failure reasons")
        if self.status == DebateStatus.FAILED and (accepted_sides or not self.reason_codes):
            raise ValueError("failed debate cannot claim accepted evidence")
        return self


class DebateTranscriptStore:
    def __init__(self) -> None:
        self._transcripts: Dict[str, DebateTranscript] = {}
        self._reservations: Dict[str, str] = {}

    def reserve(
        self,
        analysis_id: str,
        request_fingerprint: str,
    ) -> Optional[DebateTranscript]:
        existing = self._transcripts.get(analysis_id)
        if existing is not None:
            if existing.request_fingerprint != request_fingerprint:
                raise ValueError("DEBATE_REQUEST_MISMATCH")
            return existing
        if analysis_id in self._reservations:
            raise ValueError("DEBATE_ALREADY_IN_PROGRESS")
        self._reservations[analysis_id] = request_fingerprint
        return None

    def persist(self, transcript: DebateTranscript) -> DebateTranscript:
        if transcript.analysis_id in self._transcripts:
            raise ValueError("DEBATE_TRANSCRIPT_EXISTS")
        if self._reservations.get(transcript.analysis_id) != transcript.request_fingerprint:
            raise ValueError("DEBATE_RESERVATION_MISMATCH")
        self._transcripts[transcript.analysis_id] = transcript
        self._reservations.pop(transcript.analysis_id, None)
        return transcript

    def release(self, analysis_id: str) -> None:
        self._reservations.pop(analysis_id, None)

    def get(self, analysis_id: str) -> Optional[DebateTranscript]:
        return self._transcripts.get(analysis_id)


class BullBearDebateOrchestrator:
    def __init__(
        self,
        *,
        evidence: AnalysisEvidenceRegistry,
        bull_provider: StructuredLLMProvider,
        bear_provider: StructuredLLMProvider,
        store: DebateTranscriptStore,
        maximum_rounds: int = MAX_DEBATE_ROUNDS,
    ) -> None:
        if not 1 <= maximum_rounds <= MAX_DEBATE_ROUNDS:
            raise ValueError("DEBATE_ROUND_LIMIT_INVALID")
        self._evidence = evidence
        self._providers = {
            DebateSide.BULL: bull_provider,
            DebateSide.BEAR: bear_provider,
        }
        self._store = store
        self._maximum_rounds = maximum_rounds

    async def run(
        self,
        *,
        analysis_id: str,
        as_of_time: datetime,
        evidence_ids: Tuple[str, ...],
    ) -> DebateTranscript:
        request_fingerprint = _request_fingerprint(
            analysis_id,
            as_of_time,
            evidence_ids,
            self._maximum_rounds,
        )
        existing = self._store.reserve(analysis_id, request_fingerprint)
        if existing is not None:
            return existing
        try:
            return await self._run_reserved(
                analysis_id=analysis_id,
                as_of_time=as_of_time,
                evidence_ids=evidence_ids,
                request_fingerprint=request_fingerprint,
            )
        finally:
            self._store.release(analysis_id)

    async def _run_reserved(
        self,
        *,
        analysis_id: str,
        as_of_time: datetime,
        evidence_ids: Tuple[str, ...],
        request_fingerprint: str,
    ) -> DebateTranscript:
        records, reason = self._resolve_evidence(analysis_id, as_of_time, evidence_ids)
        if records is None:
            return self._persist_failed(
                analysis_id,
                as_of_time if as_of_time.tzinfo is not None else None,
                reason or "EVIDENCE_INVALID",
                request_fingerprint,
            )
        evidence_json = _canonical_evidence_json(records)
        accepted_arguments: set[str] = set()
        accepted_evidence: dict[DebateSide, set[str]] = {
            DebateSide.BULL: set(),
            DebateSide.BEAR: set(),
        }
        turns: list[DebateTurn] = []
        for round_number in range(1, self._maximum_rounds + 1):
            for side in (DebateSide.BULL, DebateSide.BEAR):
                turn = await self._run_turn(
                    analysis_id=analysis_id,
                    round_number=round_number,
                    side=side,
                    evidence_json=evidence_json,
                    records=records,
                    allowed_ids=evidence_ids,
                    accepted_arguments=accepted_arguments,
                    accepted_evidence=accepted_evidence,
                )
                turns.append(turn)
        accepted_sides = {
            turn.side for turn in turns if turn.status == DebateTurnStatus.ACCEPTED
        }
        if accepted_sides == {DebateSide.BULL, DebateSide.BEAR}:
            status = DebateStatus.COMPLETE
        elif accepted_sides:
            status = DebateStatus.PARTIAL
        else:
            status = DebateStatus.FAILED
        failure_reasons = tuple(
            reason
            for turn in turns
            if turn.status != DebateTurnStatus.ACCEPTED
            for reason in turn.reason_codes
        )
        transcript = DebateTranscript(
            analysis_id=analysis_id,
            request_fingerprint=request_fingerprint,
            as_of_time=as_of_time,
            status=status,
            maximum_rounds=self._maximum_rounds,
            turns=tuple(turns),
            reason_codes=(
                ()
                if status == DebateStatus.COMPLETE
                else failure_reasons or ("DEBATE_NO_VALID_ARGUMENT",)
            ),
        )
        return self._store.persist(transcript)

    async def _run_turn(
        self,
        *,
        analysis_id: str,
        round_number: int,
        side: DebateSide,
        evidence_json: str,
        records: Tuple[AnalysisEvidenceRecord, ...],
        allowed_ids: Tuple[str, ...],
        accepted_arguments: set[str],
        accepted_evidence: dict[DebateSide, set[str]],
    ) -> DebateTurn:
        prompt_name = f"{side.value.lower()}_debate"
        request = StructuredLLMRequest(
            request_id=f"{analysis_id}:{round_number}:{side.value}",
            prompt_name=prompt_name,
            prompt_version="1.0.0",
            variables=FrozenMapping(
                {
                    "assigned_side": side.value,
                    "evidence_json": evidence_json,
                    "prior_arguments_json": json.dumps(
                        sorted(accepted_arguments),
                        separators=(",", ":"),
                    ),
                }
            ),
        )
        try:
            result = await self._providers[side].generate(request, SpecialistLLMOutput)
        except Exception:  # noqa: BLE001
            return _failed_turn(round_number, side, "DEBATE_PROVIDER_CALL_FAILED")
        telemetry = result.telemetry
        if result.status != LLMProviderStatus.SUCCESS or result.output is None:
            return _failed_turn(
                round_number,
                side,
                result.reason_codes[0] if result.reason_codes else "DEBATE_PROVIDER_UNAVAILABLE",
                telemetry=telemetry,
            )
        expected_stance = (
            TargetClass.BULLISH if side == DebateSide.BULL else TargetClass.BEARISH
        )
        if (
            result.output.stance != expected_stance
            or not result.output.invalidating_conditions
            or any(not value.strip() for value in result.output.invalidating_conditions)
            or not _output_matches_evidence(result.output, records, allowed_ids)
        ):
            return _failed_turn(
                round_number,
                side,
                "DEBATE_ARGUMENT_INVALID",
                status=DebateTurnStatus.REJECTED,
                telemetry=telemetry,
            )
        fingerprint = " ".join(result.output.summary.casefold().split())
        cited = set(result.output.evidence_ids)
        if (
            fingerprint in accepted_arguments
            or (accepted_evidence[side] and cited.issubset(accepted_evidence[side]))
        ):
            return _failed_turn(
                round_number,
                side,
                "DEBATE_ARGUMENT_DUPLICATE",
                status=DebateTurnStatus.REJECTED,
                telemetry=telemetry,
            )
        accepted_arguments.add(fingerprint)
        accepted_evidence[side].update(cited)
        return DebateTurn(
            round_number=round_number,
            side=side,
            status=DebateTurnStatus.ACCEPTED,
            output=result.output,
            configured_model_id=telemetry.model_id,
            served_model_version=telemetry.served_model_version,
            prompt_version=telemetry.prompt_version,
            input_tokens=telemetry.input_tokens,
            output_tokens=telemetry.output_tokens,
            latency_ms=telemetry.latency_ms,
        )

    def _resolve_evidence(
        self,
        analysis_id: str,
        as_of_time: Optional[datetime],
        evidence_ids: Tuple[str, ...],
    ) -> tuple[Optional[Tuple[AnalysisEvidenceRecord, ...]], Optional[str]]:
        if as_of_time.tzinfo is None:
            return None, "ANALYSIS_AS_OF_INVALID"
        if not evidence_ids or len(set(evidence_ids)) != len(evidence_ids):
            return None, "EVIDENCE_REFERENCE_SET_INVALID"
        records: list[AnalysisEvidenceRecord] = []
        for evidence_id in evidence_ids:
            record = self._evidence.get(evidence_id)
            if record is None:
                return None, "EVIDENCE_NOT_FOUND"
            if record.analysis_id != analysis_id:
                return None, "EVIDENCE_ANALYSIS_MISMATCH"
            if record.status != AnalysisEvidenceStatus.VALID:
                return None, "EVIDENCE_INVALID"
            if record.observed_at > as_of_time or record.available_at > as_of_time:
                return None, "EVIDENCE_LOOKAHEAD_VIOLATION"
            records.append(record)
        return tuple(records), None

    def _persist_failed(
        self,
        analysis_id: str,
        as_of_time: Optional[datetime],
        reason: str,
        request_fingerprint: str,
    ) -> DebateTranscript:
        return self._store.persist(
            DebateTranscript(
                analysis_id=analysis_id,
                request_fingerprint=request_fingerprint,
                as_of_time=as_of_time,
                status=DebateStatus.FAILED,
                maximum_rounds=self._maximum_rounds,
                turns=(),
                reason_codes=(reason,),
            )
        )


def _failed_turn(
    round_number: int,
    side: DebateSide,
    reason: str,
    *,
    status: DebateTurnStatus = DebateTurnStatus.FAILED,
    telemetry: object = None,
) -> DebateTurn:
    return DebateTurn(
        round_number=round_number,
        side=side,
        status=status,
        prompt_version=getattr(telemetry, "prompt_version", "1.0.0"),
        configured_model_id=getattr(telemetry, "model_id", None),
        served_model_version=getattr(telemetry, "served_model_version", None),
        input_tokens=getattr(telemetry, "input_tokens", None),
        output_tokens=getattr(telemetry, "output_tokens", None),
        latency_ms=getattr(telemetry, "latency_ms", None),
        reason_codes=(reason,),
    )


def _canonical_evidence_json(records: Tuple[AnalysisEvidenceRecord, ...]) -> str:
    return json.dumps(
        [record.model_dump(mode="json") for record in records],
        sort_keys=True,
        separators=(",", ":"),
    )


def _request_fingerprint(
    analysis_id: str,
    as_of_time: datetime,
    evidence_ids: Tuple[str, ...],
    maximum_rounds: int,
) -> str:
    payload = json.dumps(
        {
            "analysis_id": analysis_id,
            "as_of_time": as_of_time.isoformat(),
            "evidence_ids": sorted(evidence_ids),
            "maximum_rounds": maximum_rounds,
            "prompt_versions": {"bull": "1.0.0", "bear": "1.0.0"},
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode()).hexdigest()


def _output_matches_evidence(
    output: SpecialistLLMOutput,
    records: Tuple[AnalysisEvidenceRecord, ...],
    allowed_ids: Tuple[str, ...],
) -> bool:
    if not output.evidence_ids or not set(output.evidence_ids).issubset(allowed_ids):
        return False
    by_id = {record.evidence_id: record for record in records}
    return all(
        claim.evidence_id in output.evidence_ids
        and claim.evidence_id in by_id
        and claim.name == by_id[claim.evidence_id].name
        and claim.value == by_id[claim.evidence_id].numeric_value
        and claim.unit == by_id[claim.evidence_id].unit
        for claim in output.numeric_claims
    )


def register_debate_prompts(registry: PromptRegistry) -> None:
    for side in ("bull", "bear"):
        assigned = "BULLISH" if side == "bull" else "BEARISH"
        template = (
            f"You are the {side.upper()} agent. Your stance must be {assigned}. "
            "Use only supplied evidence. Every numeric statement must be an exact "
            "numeric_claim with evidence_id. Include invalidating conditions and add new "
            "evidence in later rounds. Assigned side: {assigned_side}; "
            "evidence: {evidence_json}; prior: {prior_arguments_json}"
        )
        registry.register(
            PromptDefinition(
                name=f"{side}_debate",
                version="1.0.0",
                template=template,
                required_variables=(
                    "assigned_side",
                    "evidence_json",
                    "prior_arguments_json",
                ),
            )
        )
