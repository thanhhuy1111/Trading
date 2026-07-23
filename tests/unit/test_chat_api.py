"""POST /api/v1/chat -- exercised entirely offline via `get_orchestrator` dependency override
(a FakeLLMProvider-backed orchestrator, never a real Gemini call) and `get_current_principal`
override, matching the pattern `tests/unit/test_recommendations_api.py` uses for the rest of
the recommendation-architecture endpoints."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List

from fastapi.testclient import TestClient

from apps.api.deps import get_current_principal
from apps.api.main import app
from apps.api.routers.chat import get_orchestrator
from packages.chat_agent.conversation_service import InMemoryConversationRepository
from packages.chat_agent.orchestrator import TradingAdvisorOrchestrator
from packages.chat_agent.provider import FakeLLMProvider
from packages.chat_agent.tool_registry import ToolRegistry
from packages.evidence.models import EvidenceKey, EvidenceRecord, EvidenceStatus
from packages.evidence.store import EvidenceStore
from packages.governance.security import AuthenticatedPrincipal
from packages.market_data.models import Candle, Timeframe
from packages.ports.interfaces import PortfolioSnapshot
from packages.runtime.proposal_store import ProposalStore
from packages.runtime.recommendation_service import BaselineRecommendationService

T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
SYMBOL = "BTCUSDT"


def _rising_candles(n: int = 120) -> List[Candle]:
    candles = []
    price = Decimal("50000")
    for i in range(n):
        ct = T0 + timedelta(hours=i)
        step = price * Decimal("0.01")
        candles.append(Candle(
            exchange="binance", symbol=SYMBOL, exchange_timestamp=ct, open_time=ct,
            close_time=ct + timedelta(minutes=59, seconds=59), timeframe=Timeframe.H1, open_price=price,
            high_price=price + step + Decimal("10"), low_price=price - Decimal("10"),
            close_price=price + step, volume=Decimal("100"), trades_count=100, is_closed=True,
        ))
        price += step
    return candles


_ALL_CANDLES = _rising_candles(120)


def _candles_provider(symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> List[Candle]:
    if symbol != SYMBOL:
        return []
    return [c for c in _ALL_CANDLES if start <= c.close_time <= end]


def _admin_principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(principal_id="test_admin", roles={"ADMINISTRATOR"})


def _fake_orchestrator() -> TradingAdvisorOrchestrator:
    from packages.agents.strategy_config import default_strategy_config
    from packages.domain.enums import ModelType

    evidence_service = EvidenceStore()
    evidence_service.register(
        EvidenceRecord(
            key=EvidenceKey(
                strategy_name="checkpoint2_pipeline_demo", strategy_version="1.0.0", symbol=SYMBOL, timeframe="1h",
                model_type=ModelType.PASS_THROUGH.value, model_version="n/a", feature_version="standard_v1",
                label_version="meta_label_v1", dataset_checksum="n/a", gate_version="gate_v1",
                config_hash=default_strategy_config.config_hash, code_commit="n/a",
            ),
            status=EvidenceStatus.ASSET_SPECIFIC_APPROVED, generated_at=T0, total_oos_trades=250,
        )
    )
    portfolio_snapshot = PortfolioSnapshot(
        available=True, nav=Decimal("100000"), open_risk_pct=Decimal("0"), open_position_count=0,
        daily_realized_pnl_pct=Decimal("0"), weekly_realized_pnl_pct=Decimal("0"),
        current_drawdown_pct=Decimal("0"), kill_switch_active=False, positions_by_symbol={},
    )
    service = BaselineRecommendationService(
        candles_provider=_candles_provider, evidence_service=evidence_service,
        portfolio_snapshot_provider=lambda: portfolio_snapshot,
    )
    tools = ToolRegistry(
        recommendation_svc=service, evidence_svc=evidence_service, store=ProposalStore(),
        now_provider=lambda: _ALL_CANDLES[-1].close_time,
    )
    return TradingAdvisorOrchestrator(
        provider=FakeLLMProvider(), tools=tools, conversations=InMemoryConversationRepository()
    )


def test_chat_endpoint_rejects_unauthenticated_caller_without_permission() -> None:
    app.dependency_overrides[get_current_principal] = lambda: AuthenticatedPrincipal(
        principal_id="anonymous", roles=set()
    )
    app.dependency_overrides[get_orchestrator] = _fake_orchestrator
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/chat", json={"message": "Bây giờ tôi có thể đặt lệnh nào?"})
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_chat_endpoint_golden_path_returns_grounded_answer() -> None:
    app.dependency_overrides[get_current_principal] = _admin_principal
    app.dependency_overrides[get_orchestrator] = _fake_orchestrator
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/chat", json={"message": "Bây giờ tôi có thể đặt lệnh nào?"})
        assert response.status_code == 200
        body = response.json()
        assert "BTCUSDT" in body["answer"]
        assert body["proposal_ids"]
        assert body["conversation_id"]
    finally:
        app.dependency_overrides.clear()


def test_chat_endpoint_rejects_empty_message() -> None:
    app.dependency_overrides[get_current_principal] = _admin_principal
    app.dependency_overrides[get_orchestrator] = _fake_orchestrator
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/chat", json={"message": ""})
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_chat_endpoint_returns_503_when_gemini_not_configured() -> None:
    app.dependency_overrides[get_current_principal] = _admin_principal
    app.dependency_overrides.pop(get_orchestrator, None)
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/chat", json={"message": "Bây giờ tôi có thể đặt lệnh nào?"})
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()
