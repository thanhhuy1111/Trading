from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "multiagent-trading-api"
    assert "timestamp" in data


def test_services_health_endpoint(client: TestClient):
    response = client.get("/health/services")
    assert response.status_code == 200
    data = response.json()
    assert "postgres" in data
    assert "redis" in data
    assert "status" in data["postgres"]
    assert "status" in data["redis"]


def test_trading_status_endpoint(client: TestClient):
    response = client.get("/trading/status")
    assert response.status_code == 200
    data = response.json()
    assert "is_running" in data
    assert "soft_stop" in data
    assert "hard_stop" in data
