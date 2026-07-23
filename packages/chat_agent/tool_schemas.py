"""Typed input schemas for every allowlisted tool.

Arguments coming back from the LLM are untrusted input: they are validated against these
Pydantic models before any tool handler runs. Anything that fails validation never
reaches RecommendationService/EvidenceService.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from packages.recommendation.config import recommendation_config


class GetMarketOverviewInput(BaseModel):
    symbols: List[str] = Field(default_factory=lambda: list(recommendation_config.symbols_list))
    timeframes: List[str] = Field(default_factory=lambda: list(recommendation_config.timeframes_list))


class ScanTradeOpportunitiesInput(BaseModel):
    symbols: List[str] = Field(default_factory=lambda: list(recommendation_config.symbols_list))
    timeframes: List[str] = Field(default_factory=lambda: list(recommendation_config.timeframes_list))
    horizons_minutes: List[int] = Field(default_factory=list)
    side: str = "LONG_ONLY"
    minimum_probability: Optional[float] = None
    minimum_risk_reward: Optional[float] = None
    maximum_results: int = Field(default=3, ge=1, le=10)


class AnalyzeTradeProposalInput(BaseModel):
    proposal_id: str


class GetStrategyEvidenceInput(BaseModel):
    strategy_version: str
    symbol: Optional[str] = None
    timeframe: Optional[str] = None


class ValidateTradeProposalInput(BaseModel):
    proposal_id: str


TOOL_INPUT_SCHEMAS = {
    "get_market_overview": GetMarketOverviewInput,
    "scan_trade_opportunities": ScanTradeOpportunitiesInput,
    "analyze_trade_proposal": AnalyzeTradeProposalInput,
    "get_strategy_evidence": GetStrategyEvidenceInput,
    "validate_trade_proposal": ValidateTradeProposalInput,
}


def json_schema_for(name: str) -> Dict[str, Any]:
    model = TOOL_INPUT_SCHEMAS[name]
    schema: Dict[str, Any] = model.model_json_schema()
    schema.pop("title", None)
    return schema
