"""Apply the database schema.

Two steps, both idempotent:

1. Execute ``architecture/database/schema.sql`` as a single script against the
   configured ``DB_URL``. The file is run whole (not statement-split) because it
   contains ``$$``-quoted PL/pgSQL function bodies that a naive ``;`` splitter
   would break; psycopg2 executes multi-statement scripts natively.
2. Create the two sync tables (``sync_run``, ``stock_snapshots``) - which are not
   part of schema.sql - via SQLAlchemy ``create_all(checkfirst=True)``.

Usage:
    python scripts/apply_schema.py            # apply schema + sync tables
    python scripts/apply_schema.py --dry-run  # print planned table list only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg2

# Ensure the backend package root (containing ``app``) is importable when the
# script is run directly (``python scripts/apply_schema.py``).
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import REPO_ROOT, get_settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.models import SYNC_TABLES, Base  # noqa: E402

SCHEMA_SQL_PATH = REPO_ROOT / "architecture" / "database" / "schema.sql"


def _mask_dsn(dsn: str) -> str:
    """Mask credentials in a DB URL for safe logging."""
    if "@" not in dsn:
        return dsn
    scheme_sep = "://"
    if scheme_sep not in dsn:
        return "***"
    scheme, rest = dsn.split(scheme_sep, 1)
    host_part = rest.split("@", 1)[1]
    return f"{scheme}{scheme_sep}***:***@{host_part}"


def _schema_table_names() -> list[str]:
    """Best-effort list of tables declared in schema.sql (for --dry-run)."""
    names: list[str] = []
    for raw_line in SCHEMA_SQL_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.upper().startswith("CREATE TABLE IF NOT EXISTS "):
            remainder = line[len("CREATE TABLE IF NOT EXISTS ") :]
            table_name = remainder.split("(")[0].strip().rstrip("(").strip()
            if table_name:
                names.append(table_name)
    return names


def apply_schema_sql(db_url: str) -> None:
    """Run schema.sql whole against the database (handles $$ function bodies)."""
    sql_text = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    connection = psycopg2.connect(db_url)
    try:
        # schema.sql manages its own BEGIN/COMMIT; run it as one script.
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(sql_text)
    finally:
        connection.close()


def create_sync_tables() -> None:
    """Create the two non-schema.sql sync tables if they do not exist."""
    Base.metadata.create_all(bind=engine, tables=list(SYNC_TABLES), checkfirst=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply the FrigoLoco DB schema.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the tables that would be created without touching the DB.",
    )
    args = parser.parse_args()

    settings = get_settings()

    if not SCHEMA_SQL_PATH.exists():
        print(f"ERROR: schema.sql not found at {SCHEMA_SQL_PATH}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"Target database : {_mask_dsn(settings.db_url)}")
        print(f"schema.sql      : {SCHEMA_SQL_PATH}")
        print("\nTables from schema.sql:")
        for name in _schema_table_names():
            print(f"  - {name}")
        print("\nSync tables (create_all):")
        for table in SYNC_TABLES:
            print(f"  - {table.name}")
        return 0

    print(f"Applying schema.sql to {_mask_dsn(settings.db_url)} ...")
    apply_schema_sql(settings.db_url)
    print("schema.sql applied.")

    print("Creating sync tables (checkfirst=True) ...")
    create_sync_tables()
    print("Sync tables ensured.")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
