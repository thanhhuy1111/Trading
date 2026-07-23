from fastapi.testclient import TestClient


def test_health_services_dynamic_response(client: TestClient):
    response = client.get("/health/services")
    assert response.status_code == 200
    data = response.json()
    assert "postgres" in data
    assert "redis" in data
    assert "event_bus_adapter" in data
    assert "outbox_worker" in data
    assert "audit_repository" in data
    assert "configuration_repository" in data


def test_backend_starts_even_when_optional_services_offline(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
