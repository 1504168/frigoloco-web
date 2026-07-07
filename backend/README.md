# FrigoLoco Backend

FastAPI + SQLAlchemy 2.0 REST API for the FrigoLoco Cloud ERP (Python 3.12).

## Layout

```
backend/
├── app/
│   ├── config.py          # Settings (pydantic-settings); loads repo-root .env
│   ├── db.py              # Engine, SessionLocal, get_db dependency
│   ├── main.py            # FastAPI app, /health, CORS, router auto-discovery
│   ├── models/            # SQLAlchemy 2.0 models mirroring schema.sql + sync tables
│   │   ├── base.py        # DeclarativeBase
│   │   ├── enums.py       # PostgreSQL ENUM bindings
│   │   ├── master.py      # users, suppliers, catalogue, clients, fridges, settings…
│   │   ├── planning.py    # menus, forecasts, scores
│   │   ├── operations.py  # POs, dispatch, stock ledger, reconciliation, finance…
│   │   ├── events.py      # sales_events, restock_events (partitioned), product_reviews
│   │   └── sync.py        # sync_run, stock_snapshots (NOT in schema.sql)
│   └── routers/           # placeholder; router modules arrive from other agents
├── scripts/
│   └── apply_schema.py    # applies architecture/database/schema.sql + sync tables
└── tests/
    └── test_boot.py
```

## Configuration

All config comes from the **repo-root `.env`** (git-ignored). See `.env.example`
for the keys. The one required key is `DB_URL`. `config.py` explicitly calls
`load_dotenv(<repo-root>/.env)` before building `Settings`.

## Setup

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Apply the database schema

```bash
# Preview the tables that would be created (no DB writes):
python scripts/apply_schema.py --dry-run

# Apply schema.sql (whole-file, handles $$ PL/pgSQL bodies) then create the
# two sync tables via SQLAlchemy metadata (idempotent):
python scripts/apply_schema.py
```

## Run the API

```bash
uvicorn app.main:app --reload
# Health check:
curl localhost:8000/health   # -> {"status":"ok","db":true}
```

## Tests

```bash
pytest tests/test_boot.py
```

`/health` always returns HTTP 200; `status` is `"ok"` when the database is
reachable and `"degraded"` otherwise, so the app boots even with the DB down.
