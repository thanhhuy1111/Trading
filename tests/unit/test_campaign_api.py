"""Phase 10 API contract tests without network or configured analysis runtime."""

from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def test_phase10_routes_are_safe_and_complete() -> None:
    response = client.post(
        "/api/v1/analysis/run",
        json={"symbol": "BTC/USDT", "timeframe": "4h", "request_id": "api-test"},
    )
    assert response.status_code == 202
    analysis = response.json()
    assert analysis["status"] == "UNAVAILABLE"
    assert analysis["recommendation"] == "NO_DECISION"
    assert len(analysis["agents"]) == 3
    assert all(agent["status"] == "UNAVAILABLE" for agent in analysis["agents"])
    assert analysis["verification"]["decision"] == "REJECTED"
    assert analysis["risk"]["allow_trade"] is False
    assert client.get("/api/v1/analysis/api-test").status_code == 200
    assert len(client.get("/api/v1/analysis/api-test/agents").json()["items"]) == 3
    assert client.get("/api/v1/analysis/api-test/debate").json()["data"]["status"] == "FAILED"
    assert client.get("/api/v1/analysis/api-test/evidence").json()["items"] == []


def test_market_prediction_health_and_error_contracts() -> None:
    for suffix in ("overview", "candles", "features", "derivatives"):
        response = client.get(f"/api/v1/market/BTCUSDT/{suffix}")
        assert response.status_code == 200
        assert response.json()["status"] == "UNAVAILABLE"
    assert client.get("/api/v1/predictions").json()["items"] == []
    missing = client.get("/api/v1/predictions/missing")
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "PREDICTION_NOT_FOUND"
    health = client.get("/api/v1/system/health").json()
    assert health["live_trading_enabled"] is False
    assert health["private_exchange_api_enabled"] is False


def test_analysis_scope_and_payload_fail_closed() -> None:
    unsupported = client.post(
        "/api/v1/analysis/run",
        json={"symbol": "ETH/USDT", "timeframe": "4h"},
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["error_code"] == "ANALYSIS_SCOPE_UNSUPPORTED"
    assert client.post(
        "/api/v1/analysis/run",
        json={"symbol": "BTC/USDT", "timeframe": "4h", "secret": "x"},
    ).status_code == 422
