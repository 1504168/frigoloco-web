"""Auth stays enforced: without the conftest override, API routes reject anonymous calls."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.security import get_current_user

PROTECTED_PATH = "/api/v1/users"


def test_protected_route_without_token_returns_401() -> None:
    app.dependency_overrides.pop(get_current_user)
    client = TestClient(app)

    response = client.get(PROTECTED_PATH)

    assert response.status_code == 401


def test_health_stays_open_without_token() -> None:
    app.dependency_overrides.pop(get_current_user)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
