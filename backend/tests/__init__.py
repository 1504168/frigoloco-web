"""Test package.

Shared DB-compat bridges. The integration tests run against a live database that
may be one or more not-yet-applied migrations behind the ORM models. Each bridge
below runs inside the test's rolled-back outer transaction, so it never persists,
and becomes a no-op once the matching migration has been applied to that database.
"""

from __future__ import annotations

from sqlalchemy import Connection, text


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
