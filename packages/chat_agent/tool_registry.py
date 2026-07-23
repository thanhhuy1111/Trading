"""Allowlisted tool registry: the ONLY surface the LLM can act through.

No arbitrary Python execution, shell execution, SQL execution, filesystem access, exchange
execution, or generic HTTP request is exposed here or anywhere else in packages/chat_agent.
Every tool call is validated against a typed input schema before execution and every tool
output is a `.model_dump(mode="json")` of a typed domain/evidence model -- never a raw dict
assembled ad hoc.

`horizons_minutes` / `side` / `minimum_probability` / `minimum_risk_reward` on
`ScanTradeOpportunitiesInput` are accepted (for forward-compatible tool schema stability) but
deliberately NOT applied per-request: this baseline architecture's opportunity gates
(evidence approval, portfolio risk) are config- and evidence-driven, not user- or
model-overridable, otherwise a user (or an injected instruction) could ask the model to
loosen the bar to force a proposal through. `side` is always LONG_ONLY in this repository
regardless of input.

Every tool here calls `BaselineRecommendationService` / `EvidenceStore` -- the exact same
services `apps/api/routers/recommendations.py` uses -- never a separate, more forgiving
code path.
"""

from datetime import datetime, timezone
from typing import Any, Callable, Dict
from uuid import uuid4

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
from packages.evidence.store import EvidenceStore, evidence_store
from packages.market_data.models import Timeframe
from packages.ports.interfaces import RecommendationRequest
from packages.runtime.candles_cache import cached_candles_provider
from packages.runtime.proposal_store import ProposalStore, proposal_store
from packages.runtime.recommendation_service import BaselineRecommendationService

TOOL_DESCRIPTIONS: Dict[str, str] = {
    "get_market_overview": (
        "Kiểm tra trạng thái, độ mới (freshness) và kết quả pipeline hiện tại cho các symbol. "
        "Không trả về chi tiết đề xuất giao dịch, chỉ trạng thái tổng quan."
    ),
    "scan_trade_opportunities": (
        "Chạy pipeline định lượng đầy đủ (feature -> agent -> critic -> consensus -> allocator -> "
        "meta-label -> evidence -> ranking -> correlation -> portfolio risk) và trả về tối đa N đề "
        "xuất giao dịch hoặc trạng thái non-trade."
    ),
    "analyze_trade_proposal": (
        "Lấy lại một TradeProposal đã tồn tại theo proposal_id. Không tính toán lại bằng dữ liệu hiện tại."
    ),
    "get_strategy_evidence": (
        "Trả về bằng chứng out-of-sample (OOS) đã đăng ký cho một strategy/model version. "
        "Không dùng in-sample metrics để quảng bá."
    ),
    "validate_trade_proposal": (
        "Kiểm tra lại một proposal đã tồn tại (hết hạn hay chưa, trạng thái evidence, "
        "application_result_state hiện tại). Không đặt lệnh."
    ),
}

ALLOWED_TOOL_NAMES = frozenset(TOOL_DESCRIPTIONS.keys())

_NO_DATA_STATES = frozenset({"NO_CANDIDATE", "DATA_QUALITY_FAILED", "STALE_DATA"})

_DEFAULT_RECOMMENDATION_SERVICE = BaselineRecommendationService(candles_provider=cached_candles_provider)


class ToolRegistry:
    def __init__(
        self,
        recommendation_svc: BaselineRecommendationService = _DEFAULT_RECOMMENDATION_SERVICE,
        evidence_svc: EvidenceStore = evidence_store,
        store: ProposalStore = proposal_store,
        now_provider: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._recommendation_service = recommendation_svc
        self._evidence_service = evidence_svc
        self._store = store
        self._now_provider = now_provider

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
        result: Dict[str, Any] = await handler(validated)
        return result

    async def _handle_get_market_overview(self, input_: GetMarketOverviewInput) -> Dict[str, Any]:
        timeframe = _parse_timeframe(input_.timeframe)
        now = self._now_provider()
        symbols_overview = []
        for symbol in input_.symbols:
            request = RecommendationRequest(request_id=uuid4(), symbols=[symbol], timeframe=timeframe, as_of_time=now)
            result = await self._recommendation_service.analyze(request, symbol)
            symbols_overview.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe.value,
                    "market_data_timestamp": (
                        result.market_data_timestamp.isoformat() if result.market_data_timestamp else None
                    ),
                    "application_result_state": result.application_result_state,
                    "readiness_status": result.readiness_status.model_dump(mode="json"),
                    "reason_codes": result.reason_codes,
                    "limitations": result.limitations,
                }
            )
        overall_market_status = (
            "UNAVAILABLE"
            if symbols_overview and all(s["application_result_state"] in _NO_DATA_STATES for s in symbols_overview)
            else "AVAILABLE"
        )
        return {
            "generated_at": now.isoformat(),
            "overall_market_status": overall_market_status,
            "symbols": symbols_overview,
        }

    async def _handle_scan_trade_opportunities(self, input_: ScanTradeOpportunitiesInput) -> Dict[str, Any]:
        timeframe = _parse_timeframe(input_.timeframe)
        now = self._now_provider()
        request = RecommendationRequest(
            request_id=uuid4(), symbols=input_.symbols, timeframe=timeframe, as_of_time=now,
        )
        result = await self._recommendation_service.scan(request)
        self._store.remember(result.proposals)
        proposals = result.proposals[: input_.maximum_results]
        return {
            "request_id": str(result.request_id),
            "generated_at": result.generated_at.isoformat(),
            "application_result_state": result.application_result_state,
            "readiness_status": result.readiness_status.model_dump(mode="json"),
            "reason_codes": result.reason_codes,
            "limitations": result.limitations,
            "proposals": [p.model_dump(mode="json") for p in proposals],
        }

    async def _handle_analyze_trade_proposal(self, input_: AnalyzeTradeProposalInput) -> Dict[str, Any]:
        proposal = self._store.get_by_str(input_.proposal_id)
        if proposal is None:
            return {"found": False, "proposal_id": input_.proposal_id, "reason": "PROPOSAL_NOT_FOUND"}
        return {"found": True, **proposal.model_dump(mode="json")}

    async def _handle_get_strategy_evidence(self, input_: GetStrategyEvidenceInput) -> Dict[str, Any]:
        records = [r for r in self._evidence_service.all_records() if r.key.strategy_version == input_.strategy_version]
        if input_.symbol is not None:
            records = [r for r in records if r.key.symbol == input_.symbol]
        if input_.timeframe is not None:
            records = [r for r in records if r.key.timeframe == input_.timeframe]
        if not records:
            return {"found": False, "strategy_version": input_.strategy_version, "reason": "EVIDENCE_NOT_FOUND"}
        return {"found": True, "records": [r.model_dump(mode="json") for r in records]}

    async def _handle_validate_trade_proposal(self, input_: ValidateTradeProposalInput) -> Dict[str, Any]:
        proposal = self._store.get_by_str(input_.proposal_id)
        if proposal is None:
            return {"found": False, "proposal_id": input_.proposal_id, "reason": "PROPOSAL_NOT_FOUND"}
        now = self._now_provider()
        is_expired = now > proposal.proposal_expiry
        return {
            "found": True,
            "proposal_id": input_.proposal_id,
            "is_expired": is_expired,
            "proposal_expiry": proposal.proposal_expiry.isoformat(),
            "application_result_state": proposal.application_result_state.value,
            "evidence_status": proposal.evidence_status,
            "reason_codes": proposal.reason_codes,
        }


def _parse_timeframe(value: str) -> Timeframe:
    try:
        return Timeframe(value)
    except ValueError:
        return Timeframe.H1


tool_registry = ToolRegistry()
