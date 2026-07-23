"""Phase 9: the 5 named LLM agent interfaces (Section 9.1) and their default disabled
implementations, built on `packages.llm.framework.BaseLLMAgent`.

`packages.intelligence.market_context.BaselineMarketContextService`'s Phase 4 no-op agents
(`NoOpNewsAgent`, `NoOpMacroAgent`, `NoOpSentimentAgent`, `NoOpRiskCritic`) already satisfy
`NewsAgentPort` / `MacroAgentPort` / `SentimentAgentPort` / `RiskCriticAgentPort` structurally
(same `async def assess(self, symbol, as_of_time) -> MarketContextAssessment` signature) - they
are left untouched rather than duplicated or replaced, per the "preserve existing behavior"
rule. This module adds the fuller contract (Protocols + config + a coordinator) around them,
plus a config-driven set of disabled agents for a caller that wants the Phase 9 framework's
richer `LLMAgentConfig` (prompt_version, timeout, retry, circuit breaker, tool allowlist)
explicitly attached, rather than Phase 4's hardcoded values.
"""

from datetime import datetime
from typing import List, Protocol

from packages.domain.entities import MarketContextAssessment
from packages.llm.framework import DisabledLLMAgent, LLMAgentConfig

PROMPT_VERSION = "market_context_prompt_v1"


class NewsAgentPort(Protocol):
    async def assess(self, symbol: str, as_of_time: datetime) -> MarketContextAssessment: ...


class MacroAgentPort(Protocol):
    async def assess(self, symbol: str, as_of_time: datetime) -> MarketContextAssessment: ...


class SentimentAgentPort(Protocol):
    async def assess(self, symbol: str, as_of_time: datetime) -> MarketContextAssessment: ...


class RiskCriticAgentPort(Protocol):
    async def assess(self, symbol: str, as_of_time: datetime) -> MarketContextAssessment: ...


class CoordinatorAgentPort(Protocol):
    """Aggregates the other four agents' outputs. Per Section 11 ("the LLM layer must never
    override risk/evidence"), a coordinator may only aggregate/summarize what the underlying
    agents already produced - it must never emit its own probability, price, or risk override,
    and structurally cannot: `coordinate` only accepts and returns
    `List[MarketContextAssessment]`, never a candidate, evidence record, or risk decision."""

    async def coordinate(self, assessments: List[MarketContextAssessment]) -> List[MarketContextAssessment]: ...


class NewsAgent(DisabledLLMAgent):
    def __init__(self) -> None:
        super().__init__(LLMAgentConfig(agent_name="news_agent", agent_version="1.0.0", prompt_version=PROMPT_VERSION))


class MacroAgent(DisabledLLMAgent):
    def __init__(self) -> None:
        super().__init__(LLMAgentConfig(agent_name="macro_agent", agent_version="1.0.0", prompt_version=PROMPT_VERSION))


class SentimentAgent(DisabledLLMAgent):
    def __init__(self) -> None:
        super().__init__(
            LLMAgentConfig(agent_name="sentiment_agent", agent_version="1.0.0", prompt_version=PROMPT_VERSION),
        )


class RiskCriticAgent(DisabledLLMAgent):
    def __init__(self) -> None:
        super().__init__(
            LLMAgentConfig(agent_name="risk_critic_agent", agent_version="1.0.0", prompt_version=PROMPT_VERSION),
        )


class PassThroughCoordinatorAgent:
    """The only coordinator implementation in this task: returns every input assessment
    unchanged. A future LLM-backed coordinator may summarize `reason_codes`/`limitations`
    across agents, but must keep passing this same signature and the same "never override
    risk/evidence" invariant."""

    agent_name = "coordinator_agent_passthrough"
    agent_version = "1.0.0"

    async def coordinate(self, assessments: List[MarketContextAssessment]) -> List[MarketContextAssessment]:
        return list(assessments)
