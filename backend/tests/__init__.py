"""Test package.

Shared DB-compat bridges. The integration tests run against a live database that
may be one or more not-yet-applied migrations behind the ORM models. Each bridge
below runs inside the test's rolled-back outer transaction, so it never persists,
and becomes a no-op once the matching migration has been applied to that database.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from app.models.enums import UserRole
from app.models.master import User

TEST_ADMIN_USER = User(
    id=0,
    email="test-admin@frigoloco.test",
    full_name="Test Admin",
    password_hash="",
    role=UserRole.admin,
    is_active=True,
)


def ensure_dispatches_week_start(connection: Connection) -> None:
    """Add ``dispatches.week_start`` when migration 0011 is not yet applied.

    Mirrors ``_ensure_fridge_stock_table``: idempotent (``ADD COLUMN IF NOT
    EXISTS``), runs in the fixture's outer transaction and is rolled back on
    teardown. The generated expression matches architecture/database/schema.sql
    and migration 0011 exactly (Monday of delivery_date's ISO week).
    """
    connection.execute(
        text(
            "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS week_start DATE "
            "GENERATED ALWAYS AS "
            "(delivery_date - (EXTRACT(ISODOW FROM delivery_date)::int - 1)) STORED"
        )
    )


def ensure_test_admin_user(connection: Connection) -> None:
    """Insert the conftest test admin so audit_log / created_by FKs to users resolve.

    Routers now pass the authenticated user's id into stock movements and audit
    rows; the test admin is not a real users row, so it is added (id kept via
    OVERRIDING SYSTEM VALUE) inside the rolled-back outer transaction.
    """
    connection.execute(
        text(
            "INSERT INTO users (id, email, full_name, password_hash, role) "
            "OVERRIDING SYSTEM VALUE "
            "VALUES (:id, :email, :full_name, :password_hash, :role) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": TEST_ADMIN_USER.id,
            "email": TEST_ADMIN_USER.email,
            "full_name": TEST_ADMIN_USER.full_name,
            "password_hash": TEST_ADMIN_USER.password_hash,
            "role": TEST_ADMIN_USER.role.value,
        },
    )
