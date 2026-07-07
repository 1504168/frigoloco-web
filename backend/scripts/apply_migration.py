"""Apply a plain-SQL migration file against the configured ``DB_URL``.

Mirrors ``scripts/apply_schema.py``: the SQL file is executed whole (not
statement-split) via psycopg2 so ``$$``-quoted PL/pgSQL bodies survive, and the
file manages its own ``BEGIN``/``COMMIT``. Migrations under
``scripts/migrations/`` are written to be idempotent, so re-running is safe.

Usage:
    python scripts/apply_migration.py                       # applies 0002 (default)
    python scripts/apply_migration.py 0002_money_to_cents.sql
    python scripts/apply_migration.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg2

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
DEFAULT_MIGRATION = "0002_money_to_cents.sql"


def _mask_dsn(dsn: str) -> str:
    if "://" not in dsn or "@" not in dsn:
        return "***"
    scheme, rest = dsn.split("://", 1)
    host_part = rest.split("@", 1)[1]
    return f"{scheme}://***:***@{host_part}"


def apply_migration_sql(db_url: str, sql_path: Path) -> None:
    sql_text = sql_path.read_text(encoding="utf-8")
    connection = psycopg2.connect(db_url)
    try:
        # The migration file manages its own BEGIN/COMMIT; run it as one script.
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(sql_text)
            for notice in connection.notices:
                print(notice.rstrip())
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply a FrigoLoco SQL migration.")
    parser.add_argument(
        "migration",
        nargs="?",
        default=DEFAULT_MIGRATION,
        help=f"Migration file under scripts/migrations/ (default: {DEFAULT_MIGRATION})",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sql_path = MIGRATIONS_DIR / args.migration
    if not sql_path.exists():
        print(f"ERROR: migration not found: {sql_path}", file=sys.stderr)
        return 1

    settings = get_settings()
    if args.dry_run:
        print(f"Target database : {_mask_dsn(settings.db_url)}")
        print(f"Migration       : {sql_path}")
        print("(dry-run: nothing applied)")
        return 0

    print(f"Applying {sql_path.name} to {_mask_dsn(settings.db_url)} ...")
    apply_migration_sql(settings.db_url, sql_path)
    print("Migration applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
