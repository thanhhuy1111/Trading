"""Phase 6 evidence-only Technical, Derivatives and Quantitative specialist agents."""

from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.agents.analysis_evidence import (
    DERIVATIVES_EVIDENCE_NAMES,
    QUANTITATIVE_EVIDENCE_NAMES,
    TECHNICAL_EVIDENCE_NAMES,
    AnalysisEvidenceCategory,
    AnalysisEvidenceRecord,
    AnalysisEvidenceRegistry,
)
from packages.common.immutable import FrozenMapping
from packages.llm.prompt_registry import PromptDefinition, PromptRegistry
from packages.llm.structured_provider import (
    LLMProviderStatus,
    StructuredLLMProvider,
    StructuredLLMRequest,
)
from packages.retraining.xgboost_contracts import TargetClass
from packages.retraining.xgboost_runtime import (
    PredictionAvailability,
    XGBoostRuntime,
    XGBoostRuntimeRequest,
)
from packages.retraining.xgboost_training import validate_probabilities


class SpecialistAgentName(str, Enum):
    TECHNICAL = "technical_agent"
    DERIVATIVES = "derivatives_agent"
    QUANTITATIVE = "quantitative_agent"


class SpecialistStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class NumericEvidenceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    value: Decimal
    unit: str
    evidence_id: str


class SpecialistLLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stance: TargetClass
    summary: str = Field(min_length=1, max_length=2000)
    evidence_ids: Tuple[str, ...]
    numeric_claims: Tuple[NumericEvidenceClaim, ...] = ()
    risk_factors: Tuple[str, ...] = ()
    invalidating_conditions: Tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_evidence_only_text(self) -> "SpecialistLLMOutput":
        free_text = (
            self.summary,
            *self.risk_factors,
            *self.invalidating_conditions,
        )
        numeric_words = re.compile(
            r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
            r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
            r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
            r"eighty|ninety|hundred|thousand|million|billion|first|second|"
            r"third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|half|"
            r"quarter|dozen|point)\b",
            re.IGNORECASE,
        )
        if any(
            any(character.isnumeric() for character in text)
            or numeric_words.search(text)
            for text in free_text
        ):
            raise ValueError("numeric values must use numeric_claims, not free text")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence references must be unique")
        claim_keys = tuple(
            (claim.name, claim.evidence_id)
            for claim in self.numeric_claims
        )
        if len(set(claim_keys)) != len(claim_keys):
            raise ValueError("numeric claims must be unique")
        return self


class SpecialistAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str
    agent_name: SpecialistAgentName
    status: SpecialistStatus
    direction: Optional[TargetClass] = None
    probabilities: Optional[Tuple[float, float, float]] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    confidence_source: Optional[str] = None
    summary: Optional[str] = None
    evidence_ids: Tuple[str, ...] = ()
    numeric_claims: Tuple[NumericEvidenceClaim, ...] = ()
    risk_factors: Tuple[str, ...] = ()
    invalidating_conditions: Tuple[str, ...] = ()
    model_id: Optional[str] = None
    as_of_time: Optional[datetime] = None
    reason_codes: Tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_status(self) -> "SpecialistAssessment":
        if self.status == SpecialistStatus.AVAILABLE:
            if (
                self.direction is None
                or self.summary is None
                or self.as_of_time is None
                or not self.evidence_ids
                or self.reason_codes
            ):
                raise ValueError("available specialist assessment is incomplete")
            if self.as_of_time.tzinfo is None:
                raise ValueError("specialist as_of_time must be timezone-aware")
            if self.agent_name in {
                SpecialistAgentName.TECHNICAL,
                SpecialistAgentName.DERIVATIVES,
            } and (
                self.probabilities is not None
                or self.confidence is not None
                or self.confidence_source is not None
                or self.model_id is None
            ):
                raise ValueError("LLM specialist cannot fabricate quantitative fields")
            if self.agent_name == SpecialistAgentName.QUANTITATIVE:
                if (
                    self.probabilities is None
                    or self.confidence is None
                    or self.confidence_source is None
                    or self.model_id is None
                    or len(self.numeric_claims) != len(QUANTITATIVE_EVIDENCE_NAMES)
                    or {claim.name for claim in self.numeric_claims}
                    != QUANTITATIVE_EVIDENCE_NAMES
                ):
                    raise ValueError("quantitative assessment is incomplete")
                validate_probabilities((self.probabilities,))
                if self.confidence != max(self.probabilities):
                    raise ValueError("quantitative confidence must equal max probability")
                expected_direction = (
                    TargetClass.BEARISH,
                    TargetClass.NEUTRAL,
                    TargetClass.BULLISH,
                )[max(range(3), key=self.probabilities.__getitem__)]
                claims_by_name = {
                    claim.name: claim for claim in self.numeric_claims
                }
                expected_values = {
                    "bearish_probability": Decimal(str(self.probabilities[0])),
                    "neutral_probability": Decimal(str(self.probabilities[1])),
                    "bullish_probability": Decimal(str(self.probabilities[2])),
                    "confidence": Decimal(str(self.confidence)),
                }
                if (
                    self.direction != expected_direction
                    or set(self.evidence_ids)
                    != {claim.evidence_id for claim in self.numeric_claims}
                    or self.confidence_source
                    != claims_by_name["confidence"].evidence_id
                    or any(
                        claims_by_name[name].value != value
                        or claims_by_name[name].unit != "probability"
                        or claims_by_name[name].evidence_id not in self.evidence_ids
                        for name, value in expected_values.items()
                    )
                ):
                    raise ValueError("quantitative assessment evidence is contradictory")
        elif any(
            value is not None
            for value in (
                self.direction,
                self.probabilities,
                self.confidence,
                self.confidence_source,
                self.summary,
                self.model_id,
                self.as_of_time,
            )
        ) or (
            self.evidence_ids
            or self.numeric_claims
            or self.risk_factors
            or self.invalidating_conditions
            or not self.reason_codes
        ):
            raise ValueError("unavailable assessment cannot fabricate analysis fields")
        return self


class SpecialistRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str = Field(min_length=1)
    symbol: str
    timeframe: str
    as_of_time: datetime
    evidence_ids: Tuple[str, ...]
    quantitative_evidence_ids: Tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_request(self) -> "SpecialistRequest":
        if self.as_of_time.tzinfo is None:
            raise ValueError("specialist request timestamp must be timezone-aware")
        if self.symbol != "BTC/USDT" or self.timeframe != "4h":
            raise ValueError("specialist request identity is unsupported")
        return self


class EvidenceInterpretationAgent:
    def __init__(
        self,
        *,
        agent_name: SpecialistAgentName,
        category: AnalysisEvidenceCategory,
        prompt_name: str,
        prompt_version: str,
        evidence: AnalysisEvidenceRegistry,
        provider: StructuredLLMProvider,
    ) -> None:
        expected_mapping = {
            SpecialistAgentName.TECHNICAL: AnalysisEvidenceCategory.TECHNICAL,
            SpecialistAgentName.DERIVATIVES: AnalysisEvidenceCategory.DERIVATIVES,
        }
        if expected_mapping.get(agent_name) != category:
            raise ValueError("SPECIALIST_AGENT_CATEGORY_MISMATCH")
        self._agent_name = agent_name
        self._category = category
        self._prompt_name = prompt_name
        self._prompt_version = prompt_version
        self._evidence = evidence
        self._provider = provider

    async def assess(self, request: SpecialistRequest) -> SpecialistAssessment:
        records, reason = self._evidence.resolve(
            analysis_id=request.analysis_id,
            evidence_ids=request.evidence_ids,
            category=self._category,
            as_of_time=request.as_of_time,
        )
        if records is None:
            return _unavailable(request.analysis_id, self._agent_name, reason or "EVIDENCE_INVALID")
        required_names = (
            TECHNICAL_EVIDENCE_NAMES
            if self._category == AnalysisEvidenceCategory.TECHNICAL
            else DERIVATIVES_EVIDENCE_NAMES
        )
        if (
            len(records) != len(required_names)
            or {record.name for record in records} != required_names
            or len({record.source_id for record in records}) != 1
        ):
            return _unavailable(
                request.analysis_id,
                self._agent_name,
                "EVIDENCE_SCHEMA_INCOMPLETE",
            )
        all_records = records
        allowed_ids = request.evidence_ids
        if self._category == AnalysisEvidenceCategory.TECHNICAL:
            quantitative, quantitative_reason = self._evidence.resolve(
                analysis_id=request.analysis_id,
                evidence_ids=request.quantitative_evidence_ids,
                category=AnalysisEvidenceCategory.QUANTITATIVE,
                as_of_time=request.as_of_time,
            )
            if quantitative is None:
                return _unavailable(
                    request.analysis_id,
                    self._agent_name,
                    quantitative_reason or "QUANTITATIVE_CONTEXT_REQUIRED",
                )
            expected_quantitative_ids = {
                f"{request.analysis_id}:quantitative:{name}"
                for name in QUANTITATIVE_EVIDENCE_NAMES
            }
            if (
                len(quantitative) != len(QUANTITATIVE_EVIDENCE_NAMES)
                or {record.name for record in quantitative}
                != QUANTITATIVE_EVIDENCE_NAMES
                or set(request.quantitative_evidence_ids)
                != expected_quantitative_ids
            ):
                return _unavailable(
                    request.analysis_id,
                    self._agent_name,
                    "QUANTITATIVE_CONTEXT_INCOMPLETE",
                )
            quantitative_by_name = {
                record.name: record.numeric_value for record in quantitative
            }
            probabilities = tuple(
                quantitative_by_name[name]
                for name in (
                    "bearish_probability",
                    "neutral_probability",
                    "bullish_probability",
                )
            )
            try:
                validate_probabilities(
                    (tuple(float(value) for value in probabilities),)
                )
            except ValueError:
                probabilities_valid = False
            else:
                probabilities_valid = True
            if (
                not probabilities_valid
                or quantitative_by_name["confidence"] != max(probabilities)
                or len({record.source_id for record in quantitative}) != 1
                or not quantitative[0].source_id.startswith("approved_runtime:")
            ):
                return _unavailable(
                    request.analysis_id,
                    self._agent_name,
                    "QUANTITATIVE_CONTEXT_INVALID",
                )
            all_records = (*records, *quantitative)
            allowed_ids = (*request.evidence_ids, *request.quantitative_evidence_ids)
        elif request.quantitative_evidence_ids:
            return _unavailable(
                request.analysis_id,
                self._agent_name,
                "DERIVATIVES_CONTEXT_INVALID",
            )
        evidence_json = _canonical_evidence_json(all_records)
        try:
            result = await self._provider.generate(
                StructuredLLMRequest(
                    request_id=f"{request.analysis_id}:{self._agent_name.value}",
                    prompt_name=self._prompt_name,
                    prompt_version=self._prompt_version,
                    variables=FrozenMapping({"evidence_json": evidence_json}),
                ),
                SpecialistLLMOutput,
            )
        except Exception:  # noqa: BLE001
            return _unavailable(
                request.analysis_id,
                self._agent_name,
                "LLM_PROVIDER_CALL_FAILED",
            )
        if result.status != LLMProviderStatus.SUCCESS or result.output is None:
            return _unavailable(
                request.analysis_id,
                self._agent_name,
                result.reason_codes[0] if result.reason_codes else "LLM_PROVIDER_UNAVAILABLE",
            )
        if not _claims_match_evidence(result.output, all_records, allowed_ids):
            return _unavailable(
                request.analysis_id,
                self._agent_name,
                "LLM_EVIDENCE_CLAIM_INVALID",
            )
        return SpecialistAssessment(
            analysis_id=request.analysis_id,
            agent_name=self._agent_name,
            status=SpecialistStatus.AVAILABLE,
            direction=result.output.stance,
            confidence=None,
            confidence_source=None,
            summary=result.output.summary,
            evidence_ids=result.output.evidence_ids,
            numeric_claims=result.output.numeric_claims,
            risk_factors=result.output.risk_factors,
            invalidating_conditions=result.output.invalidating_conditions,
            model_id=(
                result.telemetry.served_model_version
                or result.telemetry.model_id
            ),
            as_of_time=request.as_of_time,
        )


class TechnicalSpecialistAgent(EvidenceInterpretationAgent):
    def __init__(
        self,
        *,
        evidence: AnalysisEvidenceRegistry,
        provider: StructuredLLMProvider,
    ) -> None:
        super().__init__(
            agent_name=SpecialistAgentName.TECHNICAL,
            category=AnalysisEvidenceCategory.TECHNICAL,
            prompt_name="technical_interpretation",
            prompt_version="1.0.0",
            evidence=evidence,
            provider=provider,
        )


class DerivativesSpecialistAgent(EvidenceInterpretationAgent):
    def __init__(
        self,
        *,
        evidence: AnalysisEvidenceRegistry,
        provider: StructuredLLMProvider,
    ) -> None:
        super().__init__(
            agent_name=SpecialistAgentName.DERIVATIVES,
            category=AnalysisEvidenceCategory.DERIVATIVES,
            prompt_name="derivatives_interpretation",
            prompt_version="1.0.0",
            evidence=evidence,
            provider=provider,
        )


class QuantitativeSpecialistAgent:
    def __init__(
        self,
        evidence: AnalysisEvidenceRegistry,
        runtime: XGBoostRuntime,
    ) -> None:
        if type(runtime) is not XGBoostRuntime:
            raise TypeError("APPROVED_XGBOOST_RUNTIME_REQUIRED")
        self._evidence = evidence
        self._runtime = runtime

    def assess(
        self,
        *,
        analysis_id: str,
        as_of_time: datetime,
        runtime_request: XGBoostRuntimeRequest,
    ) -> SpecialistAssessment:
        prediction = self._runtime.predict(runtime_request)
        if prediction.status != PredictionAvailability.AVAILABLE:
            return _unavailable(
                analysis_id,
                SpecialistAgentName.QUANTITATIVE,
                prediction.reason_codes[0] if prediction.reason_codes else "QUANT_MODEL_UNAVAILABLE",
            )
        if (
            prediction.prediction_time != as_of_time
            or runtime_request.snapshot.as_of_time != as_of_time
        ):
            return _unavailable(
                analysis_id,
                SpecialistAgentName.QUANTITATIVE,
                "QUANT_PREDICTION_TIME_MISMATCH",
            )
        if prediction.probabilities is None:
            return _unavailable(
                analysis_id,
                SpecialistAgentName.QUANTITATIVE,
                "QUANT_MODEL_OUTPUT_INVALID",
            )
        expected = {
            "bearish_probability": Decimal(str(prediction.probabilities["bearish"])),
            "neutral_probability": Decimal(str(prediction.probabilities["neutral"])),
            "bullish_probability": Decimal(str(prediction.probabilities["bullish"])),
            "confidence": Decimal(str(prediction.confidence)),
        }
        expected_source = f"approved_runtime:{prediction.model_id}:{prediction.feature_snapshot_id}"
        records: list[AnalysisEvidenceRecord] = []
        for name, value in expected.items():
            record = AnalysisEvidenceRecord(
                evidence_id=f"{analysis_id}:quantitative:{name}",
                analysis_id=analysis_id,
                category=AnalysisEvidenceCategory.QUANTITATIVE,
                feature_set="xgboost_direction",
                feature_set_version="1.0.0",
                name=name,
                numeric_value=value,
                unit="probability",
                observed_at=as_of_time,
                available_at=as_of_time,
                source_id=expected_source,
            )
            try:
                self._evidence.register(record)
            except ValueError:
                existing = self._evidence.get(record.evidence_id)
                if existing != record:
                    return _unavailable(
                        analysis_id,
                        SpecialistAgentName.QUANTITATIVE,
                        "QUANT_EVIDENCE_CONFLICT",
                    )
            records.append(record)
        by_name = {record.name: record for record in records}
        evidence_ids = tuple(record.evidence_id for record in records)
        claims = tuple(
            NumericEvidenceClaim(
                name=name,
                value=value,
                unit="probability",
                evidence_id=by_name[name].evidence_id,
            )
            for name, value in expected.items()
        )
        return SpecialistAssessment(
            analysis_id=analysis_id,
            agent_name=SpecialistAgentName.QUANTITATIVE,
            status=SpecialistStatus.AVAILABLE,
            direction=prediction.direction,
            probabilities=(
                prediction.probabilities["bearish"],
                prediction.probabilities["neutral"],
                prediction.probabilities["bullish"],
            ),
            confidence=prediction.confidence,
            confidence_source=by_name["confidence"].evidence_id,
            summary="Approved quantitative model prediction.",
            evidence_ids=evidence_ids,
            numeric_claims=claims,
            model_id=prediction.model_id,
            as_of_time=as_of_time,
        )


def _canonical_evidence_json(records: Tuple[AnalysisEvidenceRecord, ...]) -> str:
    payload = [
        {
            "evidence_id": record.evidence_id,
            "name": record.name,
            "numeric_value": str(record.numeric_value),
            "unit": record.unit,
            "observed_at": record.observed_at.isoformat(),
            "available_at": record.available_at.isoformat(),
            "source_id": record.source_id,
        }
        for record in records
    ]
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _claims_match_evidence(
    output: SpecialistLLMOutput,
    records: Tuple[AnalysisEvidenceRecord, ...],
    requested_ids: Tuple[str, ...],
) -> bool:
    if (
        not output.evidence_ids
        or len(set(output.evidence_ids)) != len(output.evidence_ids)
        or not set(output.evidence_ids).issubset(requested_ids)
    ):
        return False
    by_id = {record.evidence_id: record for record in records}
    return all(
        claim.evidence_id in output.evidence_ids
        and claim.evidence_id in by_id
        and by_id[claim.evidence_id].name == claim.name
        and by_id[claim.evidence_id].numeric_value == claim.value
        and by_id[claim.evidence_id].unit == claim.unit
        for claim in output.numeric_claims
    )


def _unavailable(
    analysis_id: str,
    agent_name: SpecialistAgentName,
    reason: str,
) -> SpecialistAssessment:
    return SpecialistAssessment(
        analysis_id=analysis_id,
        agent_name=agent_name,
        status=SpecialistStatus.UNAVAILABLE,
        reason_codes=(reason,),
    )


def register_specialist_prompts(registry: PromptRegistry) -> None:
    common = (
        "Use only the supplied evidence JSON. Do not calculate indicators from raw data. "
        "Put every numeric statement in numeric_claims with its exact evidence_id. "
        "Do not include numeric values in free text. Evidence: {evidence_json}"
    )
    registry.register(
        PromptDefinition(
            name="technical_interpretation",
            version="1.0.0",
            template=common,
            required_variables=("evidence_json",),
        )
    )
    registry.register(
        PromptDefinition(
            name="derivatives_interpretation",
            version="1.0.0",
            template=common,
            required_variables=("evidence_json",),
        )
    )
