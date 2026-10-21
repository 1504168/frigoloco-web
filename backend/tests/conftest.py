"""Shared fixtures: every test runs as an authenticated admin unless it opts out."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.main import app
from app.models.master import User
from app.security import get_current_user
from tests import TEST_ADMIN_USER


@pytest.fixture(autouse=True)
def authenticated_admin() -> Iterator[User]:
    """Bypass Bearer-token auth; require_admin passes too since it reads this user."""
    app.dependency_overrides[get_current_user] = _return_test_admin
    yield TEST_ADMIN_USER
    app.dependency_overrides.pop(get_current_user, None)


def _return_test_admin() -> User:
    return TEST_ADMIN_USER
