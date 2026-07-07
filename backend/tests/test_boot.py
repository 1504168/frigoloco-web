"""Boot smoke test: the app starts and /health responds even when the DB is
unreachable."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_boots_regardless_of_db() -> None:
    response = client.get("/health")
    assert response.status_code == 200

    body = response.json()
    # DB-unreachable tolerant: status is present and one of the two states.
    assert "status" in body
    assert body["status"] in {"ok", "degraded"}
    assert isinstance(body["db"], bool)
    # Consistency: status reflects reachability.
    assert (body["status"] == "ok") == body["db"]
