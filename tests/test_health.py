from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_home():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Campus Emergency Response System"
    assert data["docs"] == "/docs"
    assert data["health"] == "/health"


def test_metrics():
    response = client.get("/metrics")
    assert response.status_code == 200
    # Should return Prometheus metrics format (plain text with # HELP and # TYPE)
    assert "# HELP" in response.text
    assert "# TYPE" in response.text
