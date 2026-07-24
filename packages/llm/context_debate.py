"""Bounded Bull/Bear debate over already-grounded context assessments."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.chat_agent.config import GeminiSettings
from packages.common.immutable import FrozenMapping
from packages.domain.entities import MarketContextAssessment
from packages.domain.enums import MarketContextStatus
from packages.llm.framework import detect_prompt_injection
from packages.llm.gemini_structured import (
    GeminiStructuredProvider,
    GeminiStructuredSettings,
)
from packages.llm.prompt_registry import PromptDefinition, PromptRegistry
from packages.llm.structured_provider import (
    LLMProviderStatus,
    StructuredLLMRequest,
    StructuredLLMResult,
)


class ContextDebateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    argument: str = Field(min_length=1, max_length=1600)
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=16)
    risk_factors: tuple[str, ...] = Field(default=(), max_length=8)
    invalidating_conditions: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def validate_output(self) -> ContextDebateOutput:
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("debate source references must be unique")
        numeric = re.compile(r"\d")
        if any(
            numeric.search(text)
            for text in (
                self.argument,
                *self.risk_factors,
                *self.invalidating_conditions,
            )
        ):
            raise ValueError("debate prose cannot introduce numeric claims")
        free_text = " ".join(
            (
                self.argument,
                *self.risk_factors,
                *self.invalidating_conditions,
            )
        )
        if detect_prompt_injection(free_text):
            raise ValueError("debate output contains prompt-injection markers")
        lowered = free_text.lower()
        if any(
            marker in lowered
            for marker in (
                "api key",
                "private key",
                "place the order",
                "enable live trading",
                "go all in",
            )
        ):
            raise ValueError("debate output contains prohibited instructions")
        return self


_PROMPT_VERSION = "1.0.0"
_PROMPT_NAMES = {
    "BULL": "grounded_context_bull",
    "BEAR": "grounded_context_bear",
}


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    common = (
        "You are the {side} side of a bounded, research-only debate. "
        "Use only the supplied independently grounded specialist assessments. "
        "Every conclusion must reference source_ids that already exist in the input. "
        "Do not invent facts, prices, probabilities, numeric claims or sources. "
        "Do not give trading instructions and do not override Verification or Risk. "
        "Grounded assessments: {assessments_json}"
    )
    for side in ("BULL", "BEAR"):
        registry.register(
            PromptDefinition(
                name=_PROMPT_NAMES[side],
                version=_PROMPT_VERSION,
                template=common.replace("{side}", side),
                required_variables=("assessments_json",),
            )
        )
    return registry


@dataclass(frozen=True)
class ContextDebateResult:
    status: str
    reason_codes: tuple[str, ...]
    turns: tuple[dict[str, object], ...]

    def model_dump(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "turns": list(self.turns),
        }


class ContextDebateService:
    def __init__(
        self,
        *,
        settings: GeminiSettings,
        provider: GeminiStructuredProvider | None = None,
    ) -> None:
        structured_settings = GeminiStructuredSettings.model_validate(
            {
                "LLM_PROVIDER": "google",
                "GEMINI_MODEL": settings.GEMINI_MODEL,
                "GEMINI_API_KEY": settings.GEMINI_API_KEY,
                "LLM_TEMPERATURE": 0.1,
                "LLM_MAX_RETRIES": settings.GEMINI_CONTEXT_MAX_RETRIES,
                "LLM_TIMEOUT_SECONDS": settings.GEMINI_REQUEST_TIMEOUT_SECONDS,
                "LLM_STRUCTURED_OUTPUT": True,
            }
        )
        self._provider = provider or GeminiStructuredProvider(
            settings=structured_settings,
            prompts=_prompt_registry(),
        )
        self._configured = (
            settings.is_configured and settings.GEMINI_CONTEXT_ENABLED
        )

    async def run(
        self,
        *,
        analysis_id: str,
        assessments: tuple[MarketContextAssessment, ...],
    ) -> ContextDebateResult:
        if not self._configured:
            return ContextDebateResult(
                status="NOT_RUN",
                reason_codes=("LLM_SPECIALIST_RUNTIME_NOT_CONFIGURED",),
                turns=(),
            )
        required = {
            "news_agent",
            "macro_agent",
            "sentiment_agent",
            "risk_critic_agent",
        }
        available = tuple(
            item
            for item in assessments
            if item.status == MarketContextStatus.AVAILABLE
        )
        if (
            len(available) != 4
            or {item.agent_name for item in available} != required
        ):
            return ContextDebateResult(
                status="NOT_RUN",
                reason_codes=("GROUNDED_SPECIALIST_SET_INCOMPLETE",),
                turns=(),
            )

        allowed_sources = {
            source_id for item in available for source_id in item.source_ids
        }
        assessments_json = json.dumps(
            [
                {
                    "agent_name": item.agent_name,
                    "view": item.view,
                    "risk_level": item.risk_level,
                    "source_ids": item.source_ids,
                    "limitations": item.limitations,
                }
                for item in available
            ],
            sort_keys=True,
            separators=(",", ":"),
        )

        async def _run_side(
            side: Literal["BULL", "BEAR"],
        ) -> tuple[
            Literal["BULL", "BEAR"],
            StructuredLLMResult[ContextDebateOutput],
        ]:
            return side, await self._provider.generate(
                StructuredLLMRequest(
                    request_id=f"{analysis_id}:context_debate:{side.lower()}",
                    prompt_name=_PROMPT_NAMES[side],
                    prompt_version=_PROMPT_VERSION,
                    variables=FrozenMapping(
                        {"assessments_json": assessments_json}
                    ),
                ),
                ContextDebateOutput,
            )

        results = await asyncio.gather(_run_side("BULL"), _run_side("BEAR"))
        turns: list[dict[str, object]] = []
        reasons: list[str] = []
        for side, result in results:
            output = result.output
            if (
                result.status != LLMProviderStatus.SUCCESS
                or output is None
                or not set(output.source_ids).issubset(allowed_sources)
            ):
                reason = (
                    "DEBATE_SOURCE_REFERENCE_INVALID"
                    if output is not None
                    else (
                        result.reason_codes[0]
                        if result.reason_codes
                        else "DEBATE_PROVIDER_UNAVAILABLE"
                    )
                )
                reasons.append(f"{side}:{reason}")
                turns.append(
                    {
                        "round_number": 1,
                        "side": side,
                        "status": "FAILED",
                        "reason_codes": [reason],
                    }
                )
                continue
            turns.append(
                {
                    "round_number": 1,
                    "side": side,
                    "status": "ACCEPTED",
                    "argument": output.argument,
                    "source_ids": list(output.source_ids),
                    "risk_factors": list(output.risk_factors),
                    "invalidating_conditions": list(
                        output.invalidating_conditions
                    ),
                    "model_id": (
                        result.telemetry.served_model_version
                        or result.telemetry.model_id
                    ),
                    "prompt_version": result.telemetry.prompt_version,
                    "latency_ms": result.telemetry.latency_ms,
                    "input_tokens": result.telemetry.input_tokens,
                    "output_tokens": result.telemetry.output_tokens,
                }
            )

        accepted = sum(turn["status"] == "ACCEPTED" for turn in turns)
        status = "COMPLETE" if accepted == 2 else "PARTIAL" if accepted else "FAILED"
        return ContextDebateResult(
            status=status,
            reason_codes=tuple(reasons),
            turns=tuple(turns),
        )
