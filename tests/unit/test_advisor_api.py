"""API-layer tests for the AI Trading Advisor endpoints.

Fully offline: every service dependency is overridden with an in-memory test double via
`app.dependency_overrides`, so these never touch the network (no live Binance calls) and
never require a real GEMINI_API_KEY.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from apps.api.dependencies import require_advisor_api_key
from apps.api.main import app
from apps.api.routers.chat import get_orchestrator
from apps.api.routers.recommendations import get_evidence_service, get_proposal_store, get_recommendation_service
from packages.chat_agent.conversation_service import InMemoryConversationRepository
from packages.chat_agent.orchestrator import TradingAdvisorOrchestrator
from packages.chat_agent.provider import FakeLLMProvider
from packages.chat_agent.tool_registry import ToolRegistry
from packages.prediction.direction_model import LogisticRegressionDirectionModel, LogisticRegressionWeights
from packages.prediction.meta_label_model import ThresholdMetaLabelModel
from packages.prediction.registry import ModelArtifact, ModelRegistry
from packages.prediction.return_model import LinearRegressionWeights, LinearReturnModel
from packages.prediction.service import PredictionService
from packages.prediction.volatility_model import RealizedVolatilityModel
from packages.recommendation.evidence_service import EvidenceRegistry, EvidenceService
from packages.recommendation.models import EvidenceStatus, StrategyEvidence
from packages.recommendation.proposal_store import ProposalStore
from packages.recommendation.service import PIPELINE_STRATEGY_NAME, PIPELINE_STRATEGY_VERSION, RecommendationService
from tests.unit.test_recommendation_service import _UptrendMarketDataProvider


def _approved_service():
    prediction_registry = ModelRegistry()
    up_weights = LogisticRegressionWeights(
        model_version="logreg_v1", feature_names=["ema_20_slope"], up_coefficients=[500.0], up_intercept=0.5,
        down_coefficients=[-500.0], down_intercept=-1.0,
    )
    artifact = ModelArtifact(
        symbol="BTCUSDT", timeframe="1h", horizon_minutes=60,
        model_version="logreg_v1", feature_version="standard_v1",
        direction_model=LogisticRegressionDirectionModel(up_weights),
        return_model=LinearReturnModel(
            LinearRegressionWeights(
                model_version="v1", feature_names=["ema_20_slope"], coefficients=[1000.0], intercept=20.0
            )
        ),
        volatility_model=RealizedVolatilityModel(),
        meta_label_model=ThresholdMetaLabelModel(min_return_to_volatility_ratio=Decimal("0.001")),
        calibration_score=Decimal("0.80"),
    )
    prediction_registry.register(artifact)

    evidence_registry = EvidenceRegistry()
    evidence_registry.register(
        StrategyEvidence(
            strategy_name=PIPELINE_STRATEGY_NAME, strategy_version=PIPELINE_STRATEGY_VERSION,
            model_version="logreg_v1", feature_version="standard_v1", config_hash="any",
            status=EvidenceStatus.INSUFFICIENT, out_of_sample_trades=250, profit_factor=Decimal("1.35"),
            sharpe=Decimal("1.10"), maximum_drawdown_pct=Decimal("6.0"), expectancy_bps=Decimal("12.0"),
            walk_forward_windows=4, created_at=datetime.now(timezone.utc),
        )
    )
    store = ProposalStore()
    service = RecommendationService(
        market_data_provider=_UptrendMarketDataProvider(),
        prediction_svc=PredictionService(registry=prediction_registry),
        evidence_svc=EvidenceService(registry=evidence_registry),
        store=store,
    )
    return service, store


@pytest.fixture
def client():
    service, store = _approved_service()
    fake_tools = ToolRegistry(recommendation_svc=service, evidence_svc=service._evidence_service, store=store)  # noqa: SLF001
    fake_orchestrator = TradingAdvisorOrchestrator(
        provider=FakeLLMProvider(), tools=fake_tools, conversations=InMemoryConversationRepository()
    )

    app.dependency_overrides[get_recommendation_service] = lambda: service
    app.dependency_overrides[get_evidence_service] = lambda: service._evidence_service  # noqa: SLF001
    app.dependency_overrides[get_proposal_store] = lambda: store
    app.dependency_overrides[get_orchestrator] = lambda: fake_orchestrator
    app.dependency_overrides[require_advisor_api_key] = lambda: None

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


def test_scan_endpoint_returns_real_proposals(client):
    resp = client.post(
        "/api/v1/recommendations/scan", json={"symbols": ["BTCUSDT"], "timeframes": ["1h"], "maximum_results": 3}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "PROPOSALS_AVAILABLE"
    assert len(body["proposals"]) >= 1


def test_get_recommendation_by_id_roundtrips(client):
    scan_resp = client.post("/api/v1/recommendations/scan", json={"symbols": ["BTCUSDT"], "timeframes": ["1h"]})
    proposal_id = scan_resp.json()["proposals"][0]["proposal_id"]

    resp = client.get(f"/api/v1/recommendations/{proposal_id}")
    assert resp.status_code == 200
    assert resp.json()["proposal_id"] == proposal_id


def test_get_recommendation_unknown_id_returns_404(client):
    resp = client.get("/api/v1/recommendations/unknown-id")
    assert resp.status_code == 404


def test_market_overview_endpoint(client):
    resp = client.get("/api/v1/market/overview", params={"symbols": "BTCUSDT", "timeframes": "1h"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbols"][0]["symbol"] == "BTCUSDT"


def test_strategy_evidence_endpoint(client):
    resp = client.get(f"/api/v1/strategies/{PIPELINE_STRATEGY_VERSION}/evidence")
    assert resp.status_code == 200
    assert resp.json()["status"] in {"APPROVED", "RESEARCH_ONLY", "INSUFFICIENT", "REJECTED", "STALE"}


def test_chat_endpoint_returns_grounded_answer(client):
    resp = client.post("/api/v1/chat", json={"message": "Bây giờ tôi có thể đặt lệnh nào?"})
    assert resp.status_code == 200
    body = resp.json()
    assert "BTCUSDT" in body["answer"]
    assert body["proposal_ids"]
    assert body["model"] == "fake-provider-v1"


def test_chat_endpoint_without_gemini_key_returns_503_when_using_real_dependency():
    """Without overriding get_orchestrator, the real dependency must fail closed (503),
    never silently fabricate a response, when GEMINI_API_KEY is unset."""
    app.dependency_overrides[require_advisor_api_key] = lambda: None
    try:
        with TestClient(app) as c:
            resp = c.post("/api/v1/chat", json={"message": "Bây giờ tôi có thể đặt lệnh nào?"})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 503


def test_advisor_api_key_required_when_configured(client, monkeypatch):
    from packages.chat_agent.config import orchestrator_settings

    app.dependency_overrides.pop(require_advisor_api_key, None)
    monkeypatch.setattr(orchestrator_settings, "ADVISOR_API_KEY", "secret-key")
    try:
        resp_no_key = client.get("/api/v1/market/overview")
        assert resp_no_key.status_code == 401

        resp_wrong_key = client.get("/api/v1/market/overview", headers={"X-API-Key": "wrong"})
        assert resp_wrong_key.status_code == 401

        resp_correct_key = client.get("/api/v1/market/overview", headers={"X-API-Key": "secret-key"})
        assert resp_correct_key.status_code == 200
    finally:
        app.dependency_overrides[require_advisor_api_key] = lambda: None
