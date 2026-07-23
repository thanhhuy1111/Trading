"""Phase 4.2: baseline market-context (LLM) agents. Every adapter here is a no-op — the real
News/Macro/Sentiment/RiskCritic LLM-backed agents are Phase 9's job. These exist so the
recommendation runtime has something to call today that behaves exactly like a disabled LLM
layer will behave in production, proving the pipeline never depends on the LLM layer being
present.
"""

from datetime import datetime, timezone
from typing import List, Optional

from packages.domain.entities import MarketContextAssessment
from packages.domain.enums import MarketContextStatus


class _NoOpContextAgent:
    agent_name = "unset"
    agent_version = "1.0.0"

    async def assess(self, symbol: str, as_of_time: datetime) -> MarketContextAssessment:
        return MarketContextAssessment(
            agent_name=self.agent_name,
            agent_version=self.agent_version,
            analysis_timestamp=datetime.now(timezone.utc),
            decision_timestamp=as_of_time,
            source_ids=[],
            source_timestamps=[],
            view=None,
            confidence=None,
            risk_level=None,
            status=MarketContextStatus.NOT_AVAILABLE,
            reason_codes=["MARKET_CONTEXT_DISABLED"],
            limitations=["This adapter is a no-op baseline; no LLM/news/macro/sentiment provider is wired up."],
        )


class NoOpNewsAgent(_NoOpContextAgent):
    agent_name = "news_agent_noop"


class NoOpMacroAgent(_NoOpContextAgent):
    agent_name = "macro_agent_noop"


class NoOpSentimentAgent(_NoOpContextAgent):
    agent_name = "sentiment_agent_noop"


class NoOpRiskCritic(_NoOpContextAgent):
    agent_name = "risk_critic_noop"


class BaselineMarketContextService:
    """Aggregates whatever agents it's given (DI, not a hardcoded set) — with the four no-op
    adapters above, this IS the "disabled market-context layer" the runtime must tolerate."""

    DEFAULT_TIMEOUT_SECONDS = 10.0

    def __init__(self, agents: Optional[List[_NoOpContextAgent]] = None) -> None:
        self._agents = agents if agents is not None else [
            NoOpNewsAgent(), NoOpMacroAgent(), NoOpSentimentAgent(), NoOpRiskCritic(),
        ]

    async def assess(self, symbol: str, as_of_time: datetime) -> List[MarketContextAssessment]:
        return [await agent.assess(symbol, as_of_time) for agent in self._agents]
