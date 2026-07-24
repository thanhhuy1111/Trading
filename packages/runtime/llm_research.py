"""Research-only multi-LLM context runtime for the public analysis surface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from packages.chat_agent.config import GeminiSettings
from packages.domain.entities import MarketContextAssessment
from packages.domain.enums import MarketContextStatus
from packages.llm.context_debate import ContextDebateService
from packages.llm.grounded_context import GroundedMarketContextService


@dataclass(frozen=True)
class LLMResearchResult:
    status: str
    as_of_time: datetime | None
    agents: tuple[dict[str, object], ...]
    evidence: tuple[dict[str, object], ...]
    debate: dict[str, object]
    verification: dict[str, object]
    risk_reason_codes: tuple[str, ...]


class PublicLLMResearchRuntime:
    def __init__(
        self,
        *,
        settings: GeminiSettings,
        context_service: GroundedMarketContextService | None = None,
        debate_service: ContextDebateService | None = None,
    ) -> None:
        self._settings = settings
        self._context = context_service or GroundedMarketContextService.from_settings(
            settings
        )
        self._debate = debate_service or ContextDebateService(settings=settings)

    @classmethod
    def from_environment(cls) -> PublicLLMResearchRuntime:
        return cls(settings=GeminiSettings())

    @property
    def configured(self) -> bool:
        return (
            self._settings.is_configured
            and self._settings.GEMINI_CONTEXT_ENABLED
        )

    async def analyze(
        self,
        *,
        analysis_id: str,
        symbol: str,
        analysis_time: datetime,
    ) -> LLMResearchResult:
        assessments = tuple(await self._context.assess(symbol, analysis_time))
        available = tuple(
            item
            for item in assessments
            if item.status == MarketContextStatus.AVAILABLE
        )
        debate = await self._debate.run(
            analysis_id=analysis_id,
            assessments=assessments,
        )
        agents = tuple(_agent_view(item) for item in assessments)
        aggregate_status = (
            "AVAILABLE"
            if len(available) == 4
            else "PARTIAL"
            if available
            else "UNAVAILABLE"
        )
        aggregate_reasons = sorted(
            {
                reason
                for item in assessments
                if item.status != MarketContextStatus.AVAILABLE
                for reason in item.reason_codes
            }
        )
        agents = (
            *agents,
            {
                "agent_name": "llm_specialists",
                "status": aggregate_status,
                "provider": "google_gemini",
                "model_id": self._settings.GEMINI_MODEL or None,
                "available_count": len(available),
                "required_count": 4,
                "reason_codes": aggregate_reasons,
                "as_of_time": analysis_time.isoformat(),
            },
        )
        evidence = tuple(
            _source_evidence(analysis_id, item, source_id)
            for item in available
            for source_id in item.source_ids
        )
        llm_as_of_time = (
            max(
                timestamp
                for item in available
                for timestamp in item.source_timestamps
            )
            if available
            else None
        )

        verification: dict[str, object]
        risk_reasons: tuple[str, ...]
        if not self.configured:
            verification = {
                "decision": "NOT_RUN",
                "context_verification": "NOT_RUN",
                "reason_codes": ["LLM_SPECIALIST_RUNTIME_NOT_CONFIGURED"],
            }
            risk_reasons = ("RESEARCH_ONLY_NO_EXECUTION_AUTHORITY",)
        elif len(available) != 4:
            verification = {
                "decision": "REJECTED",
                "context_verification": "REJECTED",
                "reason_codes": ["GROUNDED_SPECIALIST_SET_INCOMPLETE"],
            }
            risk_reasons = (
                "GROUNDED_SPECIALIST_SET_INCOMPLETE",
                "RESEARCH_ONLY_NO_EXECUTION_AUTHORITY",
            )
        elif debate.status != "COMPLETE":
            verification = {
                "decision": "REJECTED",
                "context_verification": "REJECTED",
                "reason_codes": ["DEBATE_NOT_COMPLETE"],
            }
            risk_reasons = (
                "DEBATE_NOT_COMPLETE",
                "RESEARCH_ONLY_NO_EXECUTION_AUTHORITY",
            )
        elif not _grounding_is_valid(assessments, debate.model_dump()):
            verification = {
                "decision": "REJECTED",
                "context_verification": "REJECTED",
                "reason_codes": ["CONTEXT_SOURCE_VERIFICATION_FAILED"],
            }
            risk_reasons = (
                "CONTEXT_SOURCE_VERIFICATION_FAILED",
                "RESEARCH_ONLY_NO_EXECUTION_AUTHORITY",
            )
        else:
            # Context is structurally verified, but the existing trade Verification authority
            # requires Technical + Derivatives + approved Quantitative specialists. That
            # authority is deliberately not weakened merely because four context LLMs ran.
            verification = {
                "decision": "REJECTED",
                "context_verification": "VERIFIED",
                "reason_codes": [
                    "CONTEXT_SOURCES_VERIFIED",
                    "QUANTITATIVE_RUNTIME_NOT_BOUND",
                    "TRADE_SPECIALIST_SET_INCOMPLETE",
                ],
            }
            risk_reasons = (
                "TRADE_VERIFICATION_REJECTED",
                "RESEARCH_ONLY_NO_EXECUTION_AUTHORITY",
            )

        return LLMResearchResult(
            status=aggregate_status,
            as_of_time=llm_as_of_time,
            agents=agents,
            evidence=evidence,
            debate=debate.model_dump(),
            verification=verification,
            risk_reason_codes=risk_reasons,
        )


def _agent_view(item: MarketContextAssessment) -> dict[str, object]:
    return {
        "agent_name": item.agent_name,
        "agent_version": item.agent_version,
        "status": (
            "AVAILABLE"
            if item.status == MarketContextStatus.AVAILABLE
            else "UNAVAILABLE"
        ),
        "view": item.view,
        "heuristic_score": (
            str(item.confidence) if item.confidence is not None else None
        ),
        "score_type": (
            "LLM_HEURISTIC_SCORE" if item.confidence is not None else None
        ),
        "risk_level": item.risk_level,
        "risk_adjustment": "0",
        "source_ids": item.source_ids,
        "source_timestamps": [
            timestamp.isoformat() for timestamp in item.source_timestamps
        ],
        "reason_codes": item.reason_codes,
        "limitations": item.limitations,
        "as_of_time": (
            item.decision_timestamp.isoformat()
            if item.decision_timestamp is not None
            else None
        ),
    }


def _source_evidence(
    analysis_id: str,
    assessment: MarketContextAssessment,
    source_id: str,
) -> dict[str, object]:
    digest = sha256(source_id.encode()).hexdigest()[:16]
    return {
        "evidence_id": (
            f"{analysis_id}:context:{assessment.agent_name}:{digest}"
        ),
        "category": assessment.agent_name.removesuffix("_agent").upper(),
        "name": "grounded_public_source",
        "status": "VALID",
        "source_id": source_id,
        "observed_at": assessment.analysis_timestamp.isoformat(),
        "available_at": assessment.analysis_timestamp.isoformat(),
        "provenance": "gemini_google_search_url_citation",
    }


def _grounding_is_valid(
    assessments: tuple[MarketContextAssessment, ...],
    debate: dict[str, object],
) -> bool:
    source_ids = {
        source_id for assessment in assessments for source_id in assessment.source_ids
    }
    if not source_ids:
        return False
    for assessment in assessments:
        if (
            assessment.status != MarketContextStatus.AVAILABLE
            or not assessment.source_ids
            or len(assessment.source_ids) != len(assessment.source_timestamps)
            or any(
                timestamp > assessment.analysis_timestamp
                for timestamp in assessment.source_timestamps
            )
        ):
            return False
    turns = debate.get("turns")
    if not isinstance(turns, list) or len(turns) != 2:
        return False
    return all(
        isinstance(turn, dict)
        and turn.get("status") == "ACCEPTED"
        and isinstance(turn.get("source_ids"), list)
        and bool(turn["source_ids"])
        and set(turn["source_ids"]).issubset(source_ids)
        for turn in turns
    )
