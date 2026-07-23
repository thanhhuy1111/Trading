from typing import Protocol

from packages.agents.models import AgentEvaluationContext, AgentSignal


class StrategyAgent(Protocol):
    @property
    def agent_id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def required_feature_set(self) -> str: ...

    async def evaluate(self, context: AgentEvaluationContext) -> AgentSignal: ...
