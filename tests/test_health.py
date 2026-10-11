"""
Tests for FastAPI health check and root endpoints.
"""


def test_health_endpoint(client):
    """Verifica que GET /health responda status 200 y reporte la conectividad a Sheets."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "sheets" in data
    assert data["timezone"] == "America/La_Paz"


def test_root_endpoint(client):
    """Verifica que GET / responda status 200."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["app"] == "Supervisor Planner"
    assert data["status"] == "online"
