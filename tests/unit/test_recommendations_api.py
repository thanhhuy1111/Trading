"""Phase 8: the 11 recommendation API endpoints - exercised entirely offline (fixture candles,
fresh in-memory evidence/portfolio stores per test), with dependency overrides standing in for
the default (cache-file-backed, singleton) wiring so tests never touch the filesystem cache or
share state across test files."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List

from fastapi.testclient import TestClient

from apps.api.deps import (
    get_current_principal,
    get_evidence_store,
    get_recommendation_service,
    get_strategy_portfolio,
)
from apps.api.main import app
from packages.agents.strategy_config import default_strategy_config
from packages.evidence.models import EvidenceStatus
from packages.evidence.store import EvidenceStore
from packages.governance.security import AuthenticatedPrincipal
from packages.intelligence.strategy_portfolio import StrategyPortfolio
from packages.market_data.models import Candle, Timeframe
from packages.registries.models import RegistryEntry
from packages.runtime.recommendation_service import BaselineRecommendationService

T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
SYMBOL = "BTC/USDT"


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


def _client_with_overrides(evidence_store: EvidenceStore, strategy_portfolio: StrategyPortfolio) -> TestClient:
    service = BaselineRecommendationService(
        candles_provider=_candles_provider, evidence_service=evidence_store, strategy_portfolio=strategy_portfolio,
    )
    app.dependency_overrides[get_recommendation_service] = lambda: service
    app.dependency_overrides[get_evidence_store] = lambda: evidence_store
    app.dependency_overrides[get_strategy_portfolio] = lambda: strategy_portfolio
    app.dependency_overrides[get_current_principal] = _admin_principal
    return TestClient(app)


def _reset_overrides() -> None:
    app.dependency_overrides.clear()


def test_recommendation_health_never_touches_db_or_network() -> None:
    with _client_with_overrides(EvidenceStore(), StrategyPortfolio()) as client:
        response = client.get("/recommendations/health")
        assert response.status_code == 200
        assert response.json()["status"] == "OK"
        assert response.json()["live_trading_enabled"] is False
    _reset_overrides()


def test_analyze_endpoint_returns_research_proposal_with_empty_evidence() -> None:
    with _client_with_overrides(EvidenceStore(), StrategyPortfolio()) as client:
        response = client.post("/recommendations/analyze", json={
            "symbol": SYMBOL, "timeframe": "1h", "as_of_time": _ALL_CANDLES[-1].close_time.isoformat(),
        })
        assert response.status_code == 200
        body = response.json()
        assert body["application_result_state"] == "RESEARCH_PROPOSAL"
        assert len(body["proposals"]) == 1
        assert body["readiness_status"]["live_readiness"] == "DISABLED"
    _reset_overrides()


def test_analyze_endpoint_no_market_data_yields_no_candidate() -> None:
    with _client_with_overrides(EvidenceStore(), StrategyPortfolio()) as client:
        response = client.post("/recommendations/analyze", json={
            "symbol": "DOGE/USDT", "timeframe": "1h", "as_of_time": _ALL_CANDLES[-1].close_time.isoformat(),
        })
        assert response.status_code == 200
        assert response.json()["application_result_state"] == "NO_CANDIDATE"
        assert response.json()["proposals"] == []
    _reset_overrides()


def test_scan_endpoint_aggregates_multiple_symbols() -> None:
    with _client_with_overrides(EvidenceStore(), StrategyPortfolio()) as client:
        response = client.post("/recommendations/scan", json={
            "symbols": [SYMBOL, "ETH/USDT"], "timeframe": "1h",
            "as_of_time": _ALL_CANDLES[-1].close_time.isoformat(),
        })
        assert response.status_code == 200
        body = response.json()
        assert len(body["proposals"]) == 1
        assert any("ETH/USDT:NO_MARKET_DATA_AVAILABLE" in c for c in body["reason_codes"])
    _reset_overrides()


def test_get_proposal_round_trips_after_analyze() -> None:
    with _client_with_overrides(EvidenceStore(), StrategyPortfolio()) as client:
        analyze_response = client.post("/recommendations/analyze", json={
            "symbol": SYMBOL, "timeframe": "1h", "as_of_time": _ALL_CANDLES[-1].close_time.isoformat(),
        })
        proposal_id = analyze_response.json()["proposals"][0]["proposal_id"]
        fetch_response = client.get(f"/recommendations/{proposal_id}")
        assert fetch_response.status_code == 200
        assert fetch_response.json()["proposal_id"] == proposal_id
    _reset_overrides()


def test_get_unknown_proposal_is_404_not_500() -> None:
    with _client_with_overrides(EvidenceStore(), StrategyPortfolio()) as client:
        response = client.get("/recommendations/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404
        assert response.json()["detail"]
    _reset_overrides()


def test_readiness_endpoint_reflects_empty_evidence_registry() -> None:
    with _client_with_overrides(EvidenceStore(), StrategyPortfolio()) as client:
        response = client.get("/readiness")
        assert response.status_code == 200
        body = response.json()
        assert body["architecture_readiness"] == "READY"
        assert body["live_readiness"] == "DISABLED"
        assert body["evidence_readiness"] == "EMPTY_REGISTRY"
    _reset_overrides()


def test_evidence_lookup_endpoint_missing_result() -> None:
    with _client_with_overrides(EvidenceStore(), StrategyPortfolio()) as client:
        response = client.post("/evidence/lookup", json={
            "strategy_name": "baseline", "strategy_version": "1.0.0", "symbol": SYMBOL, "timeframe": "1h",
            "model_type": "PASS_THROUGH", "model_version": "n/a", "feature_version": "standard_v1",
            "label_version": "meta_label_v1", "dataset_checksum": "n/a", "gate_version": "gate_v1",
            "config_hash": default_strategy_config.config_hash, "code_commit": "n/a",
        })
        assert response.status_code == 200
        assert response.json()["result"] == "MISSING"
        assert response.json()["record"] is None
    _reset_overrides()


def test_strategy_sleeve_registration_round_trips() -> None:
    with _client_with_overrides(EvidenceStore(), StrategyPortfolio()) as client:
        sleeve = {
            "strategy_id": "baseline_btc_1h", "symbol": SYMBOL, "timeframe": "1h", "regime_scope": ["TREND_UP"],
            "risk_budget_pct": 0.25, "allocation_weight": 0.1, "evidence_status": "RESEARCH_ONLY",
            "model_version": "n/a", "drawdown_limit_pct": 8.0,
        }
        post_response = client.post("/strategy-portfolio/sleeves", json=sleeve)
        assert post_response.status_code == 201
        get_response = client.get("/strategy-portfolio/sleeves")
        assert get_response.status_code == 200
        assert len(get_response.json()) == 1
        assert get_response.json()[0]["strategy_id"] == "baseline_btc_1h"
    _reset_overrides()


def test_registry_entries_endpoint_lists_and_filters() -> None:
    from packages.registries.instances import strategy_registry

    strategy_registry.register(RegistryEntry(
        name="test_registry_api_entry", version="1.0.0", compatible_symbols=[SYMBOL],
        compatible_timeframes=["1h"],
    ))
    with _client_with_overrides(EvidenceStore(), StrategyPortfolio()) as client:
        all_response = client.get("/registries/strategy/entries")
        assert all_response.status_code == 200
        assert any(e["name"] == "test_registry_api_entry" for e in all_response.json())

        filtered_response = client.get("/registries/strategy/entries", params={"symbol": "ETH/USDT"})
        assert all(
            e["name"] != "test_registry_api_entry" or "ETH/USDT" in e["compatible_symbols"]
            for e in filtered_response.json()
        )

        unknown_response = client.get("/registries/not_a_real_registry/entries")
        assert unknown_response.status_code == 404
    _reset_overrides()


def test_portfolio_risk_evaluate_endpoint_missing_state_halts() -> None:
    with _client_with_overrides(EvidenceStore(), StrategyPortfolio()) as client:
        candidate = {
            "session_id": "11111111-1111-1111-1111-111111111111", "symbol": SYMBOL, "timeframe": "1h",
            "decision_timestamp": T0.isoformat(), "direction": "LONG", "agent_source": "trend_agent_v1",
            "agent_confidence": "0.75", "supporting_agents": ["trend_agent_v1"], "opposing_agents": [],
            "consensus_score": "0.75", "critic_result": "trend_agent_v1:APPROVED",
            "allocator_result": "TRADE_INTENT_CREATED", "strategy_name": "baseline", "strategy_version": "1.0.0",
            "strategy_config_hash": "hash1", "market_regime": "TREND_UP", "feature_snapshot": {},
            "entry_reference": "50000", "estimated_fee_bps": "10", "estimated_spread_bps": "2",
            "estimated_slippage_bps": "5", "status": "PROPOSED",
        }
        response = client.post("/portfolio-risk/evaluate", json={
            "candidate": candidate, "requested_risk_pct": "0.25",
            "portfolio": {"available": False}, "evidence_actionable": True,
        })
        assert response.status_code == 200
        assert response.json()["decision"] == "HALT"
        assert "PORTFOLIO_STATE_UNAVAILABLE" in response.json()["reason_codes"]
    _reset_overrides()


def test_architecture_status_endpoint_reports_eleven_endpoints() -> None:
    with _client_with_overrides(EvidenceStore(), StrategyPortfolio()) as client:
        response = client.get("/system/architecture-status")
        assert response.status_code == 200
        assert response.json()["endpoints_implemented"] == 11
        assert response.json()["live_readiness"] == "DISABLED"
    _reset_overrides()


def test_endpoints_reject_unauthenticated_caller_without_permission() -> None:
    app.dependency_overrides[get_current_principal] = lambda: AuthenticatedPrincipal(
        principal_id="anonymous", roles=set(),
    )
    with TestClient(app) as client:
        response = client.get("/readiness")
        assert response.status_code == 403
    _reset_overrides()


def test_evidence_registered_as_approved_is_reflected_in_readiness() -> None:
    from packages.evidence.models import EvidenceKey, EvidenceRecord

    evidence_service = EvidenceStore()
    key = EvidenceKey(
        strategy_name="baseline", strategy_version="1.0.0", symbol=SYMBOL, timeframe="1h",
        model_type="PASS_THROUGH", model_version="n/a", feature_version="standard_v1",
        label_version="meta_label_v1", dataset_checksum="n/a", gate_version="gate_v1",
        config_hash="hash1", code_commit="n/a",
    )
    evidence_service.register(EvidenceRecord(
        key=key, status=EvidenceStatus.ASSET_SPECIFIC_APPROVED, generated_at=T0, total_oos_trades=50,
    ))
    with _client_with_overrides(evidence_service, StrategyPortfolio()) as client:
        response = client.get("/readiness")
        assert response.json()["evidence_readiness"] == "ASSET_SPECIFIC_EVIDENCE"
        assert response.json()["strategy_readiness"] == "ASSET_SPECIFIC_APPROVED"
    _reset_overrides()
