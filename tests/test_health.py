from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


def test_home():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Get medical help" in response.text


def test_metrics():
    response = client.get("/metrics")
    assert response.status_code == 200
    # Should return Prometheus metrics format (plain text with # HELP and # TYPE)
    assert "# HELP" in response.text
    assert "# TYPE" in response.text
