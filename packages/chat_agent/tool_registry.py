"""Allowlisted tool registry: the ONLY surface the LLM can act through.

No arbitrary Python execution, shell execution, SQL execution, filesystem access,
exchange execution, or generic HTTP request is exposed here or anywhere else in
packages/chat_agent. Every tool call is validated against a typed input schema before
execution and every tool output is a `.model_dump(mode="json")` of a typed
packages.recommendation / packages.prediction model -- never a raw dict assembled ad hoc.

`horizons_minutes` / `side` / `minimum_probability` / `minimum_risk_reward` on
`ScanTradeOpportunitiesInput` are accepted (for forward-compatible tool schema stability)
but deliberately NOT applied per-request: opportunity gate thresholds are config-driven
(packages/recommendation/config.py), not user- or model-overridable, otherwise a user (or
an injected instruction) could ask the model to loosen the probability/RR bar to force a
proposal through. `side` is always LONG_ONLY in this repository regardless of input --
spot short is blocked at the allocator (packages/governance/allocator.py) independent of
this layer.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from pydantic import ValidationError

from packages.chat_agent.exceptions import ToolValidationError, UnsupportedToolError
from packages.chat_agent.models import AgentToolDefinition
from packages.chat_agent.tool_schemas import (
    TOOL_INPUT_SCHEMAS,
    AnalyzeTradeProposalInput,
    GetMarketOverviewInput,
    GetStrategyEvidenceInput,
    ScanTradeOpportunitiesInput,
    ValidateTradeProposalInput,
    json_schema_for,
)
from packages.recommendation.evidence_service import EvidenceService, evidence_service
from packages.recommendation.proposal_store import ProposalStore, proposal_store
from packages.recommendation.proposal_validator import validate_proposal
from packages.recommendation.service import PIPELINE_STRATEGY_NAME, RecommendationService, recommendation_service

TOOL_DESCRIPTIONS: Dict[str, str] = {
    "get_market_overview": (
        "Kiểm tra trạng thái, độ mới (freshness) và market regime đa khung thời gian cho các symbol. "
        "Không tạo tín hiệu giao dịch."
    ),
    "scan_trade_opportunities": (
        "Chạy pipeline định lượng đầy đủ (feature -> agent -> critic -> consensus -> allocator -> "
        "prediction -> evidence -> risk gates -> ranking) và trả về tối đa N đề xuất giao dịch hoặc NO_TRADE."
    ),
    "analyze_trade_proposal": (
        "Lấy lại một TradeProposal đã tồn tại theo proposal_id, kèm decision lineage đầy đủ. "
        "Không tính toán lại bằng dữ liệu hiện tại."
    ),
    "get_strategy_evidence": (
        "Trả về bằng chứng out-of-sample (OOS) của một strategy/model version. "
        "Không dùng in-sample metrics để quảng bá."
    ),
    "validate_trade_proposal": (
        "Kiểm tra lại một proposal đã tồn tại (freshness, expiry, cost, net return, risk/reward, "
        "regime, calibration...) trước khi hiển thị. Không đặt lệnh."
    ),
}

ALLOWED_TOOL_NAMES = frozenset(TOOL_DESCRIPTIONS.keys())


class ToolRegistry:
    def __init__(
        self,
        recommendation_svc: RecommendationService = recommendation_service,
        evidence_svc: EvidenceService = evidence_service,
        store: ProposalStore = proposal_store,
    ) -> None:
        self._recommendation_service = recommendation_svc
        self._evidence_service = evidence_svc
        self._store = store

    def definitions(self) -> list[AgentToolDefinition]:
        return [
            AgentToolDefinition(name=name, description=desc, parameters_schema=json_schema_for(name))
            for name, desc in TOOL_DESCRIPTIONS.items()
        ]

    async def execute(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if name not in ALLOWED_TOOL_NAMES:
            raise UnsupportedToolError(f"Tool '{name}' is not in the allowlisted registry")

        schema = TOOL_INPUT_SCHEMAS[name]
        try:
            validated = schema.model_validate(arguments)
        except ValidationError as exc:
            raise ToolValidationError(f"Invalid arguments for tool '{name}': {exc}") from exc

        handler = getattr(self, f"_handle_{name}")
        result = await handler(validated)
        return result

    async def _handle_get_market_overview(self, input_: GetMarketOverviewInput) -> Dict[str, Any]:
        overview = await self._recommendation_service.get_market_overview(input_.symbols, input_.timeframes)
        return overview.model_dump(mode="json")

    async def _handle_scan_trade_opportunities(self, input_: ScanTradeOpportunitiesInput) -> Dict[str, Any]:
        result = await self._recommendation_service.scan_trade_opportunities(
            symbols=input_.symbols, timeframes=input_.timeframes, max_results=input_.maximum_results
        )
        return result.model_dump(mode="json")

    async def _handle_analyze_trade_proposal(self, input_: AnalyzeTradeProposalInput) -> Dict[str, Any]:
        proposal = self._store.get(input_.proposal_id)
        if proposal is None:
            return {"found": False, "proposal_id": input_.proposal_id, "reason": "PROPOSAL_NOT_FOUND"}
        return {"found": True, **proposal.model_dump(mode="json")}

    async def _handle_get_strategy_evidence(self, input_: GetStrategyEvidenceInput) -> Dict[str, Any]:
        evidence = self._evidence_service.get_evidence(
            strategy_name=PIPELINE_STRATEGY_NAME,
            strategy_version=input_.strategy_version,
            config_hash="",
            feature_version="standard_v1",
            now=datetime.now(timezone.utc),
        )
        return evidence.model_dump(mode="json")

    async def _handle_validate_trade_proposal(self, input_: ValidateTradeProposalInput) -> Dict[str, Any]:
        proposal = self._store.get(input_.proposal_id)
        if proposal is None:
            return {"found": False, "proposal_id": input_.proposal_id, "reason": "PROPOSAL_NOT_FOUND"}
        result = validate_proposal(proposal)
        return {"found": True, **result.model_dump(mode="json")}


tool_registry = ToolRegistry()
