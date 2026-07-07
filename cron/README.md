# FrigoLoco cron layer

APScheduler worker + one-off CLI jobs that ingest the Intelligent Fridges
("Husky") API into PostgreSQL. This package depends on the backend
(`frigoloco-backend`) for `Settings`, the ORM models, the DB session and the
`app.husky` client — the cron layer only orchestrates; the API contract and
data model live in the backend.

```
cron.jobs.<name>  ->  app.husky (client/normalize/archive)  ->  app.{config,models}
```

## Jobs

| CLI | Schedule (Europe/Brussels) | Target table | Idempotency key |
|---|---|---|---|
| `python -m cron.jobs.sync_purchases` | hourly :05 (trailing 48h) | `sales_events` | `(husky_ref, sold_at)` |
| `python -m cron.jobs.sync_restock` | hourly :10 (trailing 48h) | `restock_events` | `(husky_ref, occurred_at)` |
| `python -m cron.jobs.snapshot_stock` | every 15 min | `stock_snapshots` | `(taken_at, fridge_id, product_code)` |
| `python -m cron.jobs.catalogue_sync` | daily 02:00 | `products` / `fridges` / `clients` / `fridge_product_prices` | `code` / `husky_id` / name / `(fridge_id, product_id)` |
| `python -m cron.jobs.reviews_sync` | daily 02:15 (trailing 14d) | `product_reviews` | synthesized `husky_ref` |
| `python -m cron.jobs.recompute_scores` | daily 02:30 | `product_scores` | `(product_id, period_end)` |
| `python -m cron.jobs.backfill` | CLI only | (delegates) | via `sync_run` |

Every job: archives the raw payload **before** transform, writes a `sync_run`
row (start + finish/failed), and upserts via `ON CONFLICT` on the constraints
above so re-runs and overlap windows are free.

## Common invocations

```bash
# Steady-state manual runs
python -m cron.jobs.catalogue_sync
python -m cron.jobs.snapshot_stock
python -m cron.jobs.sync_purchases --from 2026-06-26 --to 2026-06-28
python -m cron.jobs.sync_restock                     # trailing 48h
python -m cron.jobs.reviews_sync
python -m cron.jobs.recompute_scores --as-of 2026-07-03

# Historical backfill (resumable, 7-day chunks, auto-halving on failure)
python -m cron.jobs.backfill --dry-run --endpoint purchases --from 2024-01-01 --to 2024-02-01
python -m cron.jobs.backfill --endpoint restock --from 2025-01-01 --to 2025-07-01

# Long-running scheduler (its own container)
python -m cron.scheduler
```

## Setup

```bash
cd cron
python3 -m venv .venv
.venv/bin/pip install -e ../backend -e .        # backend first satisfies the path dep
.venv/bin/python -m cron.jobs.snapshot_stock
```

Configuration is read from the repo-root `.env` via the backend `Settings`
(`DB_URL`/`DATABASE_URL`, `FRIGOLOCO_API_BASE_URL/USERNAME/PASSWORD`,
`FRIGOLOCO_MERCHANT_NAME`, `RAW_ARCHIVE_DIR`, `HUSKY_THROTTLE_RPS`).

## Tests

```bash
.venv/bin/pytest cron/tests/test_jobs.py
```

Unit tests cover the normalisation layer (cents→Decimal, refund flag,
comma-decimal strings, VAT), response-model parsing (inline fixtures) and pure
job helpers (fridge resolver, backfill windowing). No live API/DB calls.

## Docker

```bash
docker build -f cron/Dockerfile -t frigoloco-cron .   # build from repo root
docker run --env-file .env frigoloco-cron             # runs the scheduler
```
