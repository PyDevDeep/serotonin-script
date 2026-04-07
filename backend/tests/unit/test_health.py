from fastapi.testclient import TestClient

from backend.api.main import app

client = TestClient(app)


def test_health_check():
    """Test that the health endpoint returns 200 with status ok."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_check():
    """Test that the readiness endpoint returns 200 with status ready."""
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
