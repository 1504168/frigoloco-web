# 0007 - Railway Deployment & Upgrade Runbook

## Modification History

| Date (UTC)              | Description                                                        |
|-------------------------|--------------------------------------------------------------------|
| 2026-07-29 08:22 AM UTC | Initial creation - GitHub-based deploy now, image hosting later.   |

---

## Why

FrigoLoco is a three-segment monorepo (`backend/` FastAPI, `frontend/` Vite+React, `cron/` APScheduler worker) that needs to run in the cloud with **two publicly reachable environments**:

- **production** - the live system, backed by the `sakura` Railway Postgres.
- **testing** - a staging copy for safe validation, backed by the `turntable` Postgres (which already holds the historically-synced data).

The end goal: **two public frontend URLs anyone can reach** (one per environment), each talking to its own backend and its own database. This spec is the runbook to get there and to upgrade the deployment afterwards.

The problem this solves: before this work there was no `docker-compose.yml`, no `backend/`/`frontend/` Dockerfile, no Railway service config, and no documented deploy procedure. The repo was described as deployable but was not. This spec closes that gap.

---

## Decisions (and the alternatives weighed)

### D1. Deploy source: GitHub-linked build NOW, prebuilt image hosting LATER

**Chosen:** Railway builds each service from the GitHub repo (`1504168/frigoloco-web`) using that segment's Dockerfile. Container-image hosting (push to a registry, deploy the image) is explicitly a **separate later task** (see "Deferred: image hosting").

- **Option A - GitHub-linked (chosen for now).** Railway pulls the repo and builds from the Dockerfile. Auto-redeploys on push to the watched branch. No registry, no image-credential wiring.
  - Pros: zero registry setup; auto-deploy on push; Railway injects per-environment service variables as Docker build args (so the frontend bakes the right API URL per environment automatically).
  - Cons: build happens on Railway (slower first deploy); monorepo needs a per-service **Root Directory** setting (a dashboard/API action).
- **Option B - Prebuilt images (deferred).** Build locally/CI, push to GHCR/Docker Hub, Railway runs the image.
  - Pros: deterministic; self-contained images (no monorepo root-dir config); the images were already built and container-tested locally.
  - Cons: needs a registry + (for private) Railway pull credentials; the frontend bakes its API URL at build time, so image hosting wants a **runtime-config** frontend change (one image, env-driven) to avoid one image per environment.
  - **Why deferred:** it adds a registry decision and a frontend code change that are not needed to ship the two URLs today. Isolating it keeps the first deploy simple.

### D2. Two environments in ONE Railway project

Railway "Environments" give each environment its own service variables while sharing the service definitions. So we create the services once; they exist in both `production` and `testing`, and only the **variables differ** (chiefly `DB_URL` and `APP_ENV`). No duplicated service wiring.

- Rejected: two separate Railway projects. More to manage, no shared service definitions, easy to drift.

### D3. Per-environment DB via `APP_ENV` overlay (local) / `DB_URL` variable (Railway)

`backend/app/config.py` loads an overlay env file selected by `APP_ENV` (`.env.production` -> sakura, `.env.test` -> turntable) layered over the base `.env`; real process env vars always win (override=False). On Railway there are no `.env` files - `DB_URL` (and everything else) is a Railway service variable per environment. Both paths converge on `Settings.db_url`.

- Rejected: hardcoding DB URLs or branching in code. The overlay keeps shared secrets in one place locally and lets Railway inject per-env values in the cloud.

### D4. Frontend API URL

- **Now (GitHub build):** `VITE_API_BASE_URL` is a per-environment Railway **build variable**; Railway passes it as the `ARG VITE_API_BASE_URL` build arg, so each environment's frontend build bakes its own backend URL. No code change.
- **Later (image hosting):** switch to runtime config (nginx writes `/config.js` from an env var at container start; `api.ts` reads `window.__APP_CONFIG__`) so one image serves both environments. This is the D1 Option-B follow-up.

---

## Target topology

```
Railway project: Frigo Loco ERP  (id 9febc1ff-2f7c-4d34-b4bb-004948f8d130)

  ├─ Postgres (sakura)      ← production DB, in-project service
  │
  ├─ frigoloco-backend      Root Directory: backend/    Dockerfile: Dockerfile
  ├─ frigoloco-frontend     Root Directory: frontend/   Dockerfile: Dockerfile
  └─ frigoloco-cron         Root Directory: (repo root)  Dockerfile: cron/Dockerfile   (1 replica)

  Environments:
    production  → DB_URL = sakura,     APP_ENV=production
    testing     → DB_URL = turntable,  APP_ENV=test
```

- `turntable` Postgres is external to this project (the pre-existing DB); it is referenced only via the `DB_URL` variable in the `testing` environment.
- The cron worker MUST run exactly **1 replica** (no scheduler lock guard - two would double-fire every job).

---

## Prerequisites / inputs still required

| Input | Needed for | Status |
|-------|-----------|--------|
| Dockerfiles on the watched branch | Railway build | PR #1 (`deploy/railway-dockerfiles`) open; needs merge to `main` OR services point at the branch |
| Railway ↔ GitHub connection | GitHub-linked services | Connected (CLI `railway add --repo` succeeded) |
| `turntable` full connection URL | `testing` env `DB_URL` | **MISSING** - lives in the unreadable base `.env`; must be pasted or set in the dashboard |
| `FRIGOLOCO_API_USERNAME` / `FRIGOLOCO_API_PASSWORD` | cron sync (and backend if it calls Husky) | **MISSING** - same reason. Not needed for the frontend/backend to serve data; needed for ongoing sync |

Backend serving data from the DB needs only `DB_URL`. Husky credentials are only needed by the sync jobs (cron). So the two URLs can go live before the Husky creds are set.

---

## Procedure - first deploy

All CLI commands assume the Railway CLI is installed and authenticated (`railway whoami` works) and the project is linked (`railway link --project 9febc1ff-2f7c-4d34-b4bb-004948f8d130`).

### 1. Land the Dockerfiles on the build branch
- Merge PR #1 into `main` (production tracks `main`), or point each service at branch `deploy/railway-dockerfiles` for an interim deploy and switch to `main` after merge.

### 2. Create the testing environment (done)
```
railway environment new testing
```

### 3. Create the three services (GitHub-linked)
```
railway add --service frigoloco-backend  --repo 1504168/frigoloco-web --branch main
railway add --service frigoloco-frontend --repo 1504168/frigoloco-web --branch main
railway add --service frigoloco-cron     --repo 1504168/frigoloco-web --branch main
```
Note: Railway uses a **staged-changes** model - services created via CLI are staged and must be applied (dashboard "Deploy"/"Sync", or the next deploy) before they materialise.

### 4. Set each service's monorepo build config (dashboard: Service → Settings → Build)
| Service | Root Directory | Dockerfile Path |
|---------|----------------|-----------------|
| frigoloco-backend  | `backend/`  | `Dockerfile` (relative to root dir) |
| frigoloco-frontend | `frontend/` | `Dockerfile` |
| frigoloco-cron     | *(repo root, leave blank)* | `cron/Dockerfile` |

Reason: `backend/Dockerfile` and `frontend/Dockerfile` assume the build context is their own subdirectory; `cron/Dockerfile` intentionally builds from the repo root (it copies both `backend/` and `cron/`). If Root Directory cannot be set (CLI has no flag today), the alternative is to set `RAILWAY_DOCKERFILE_PATH` and rewrite backend/frontend Dockerfiles for repo-root context - not chosen, to keep the tested Dockerfiles unchanged.

### 5. Set variables per environment
Shared (both environments), on backend and cron:
```
railway variable set FRIGOLOCO_API_USERNAME=<...> --service frigoloco-backend --environment production --skip-deploys
railway variable set FRIGOLOCO_API_PASSWORD=<...> --service frigoloco-backend --environment production --skip-deploys
# repeat for frigoloco-cron and for --environment testing
```
Per environment:
```
# production
railway variable set APP_ENV=production                          --service frigoloco-backend --environment production --skip-deploys
railway variable set DB_URL='${{Postgres.DATABASE_URL}}'         --service frigoloco-backend --environment production --skip-deploys
# testing
railway variable set APP_ENV=test                                --service frigoloco-backend --environment testing --skip-deploys
railway variable set DB_URL='<turntable connection URL>'         --service frigoloco-backend --environment testing --skip-deploys
```
- Production `DB_URL` can reference the in-project Postgres via `${{Postgres.DATABASE_URL}}` (no secret in plaintext). Testing `DB_URL` is the external turntable URL.
- cron needs the same DB + Husky vars; it has no `PORT`.

### 6. Generate public domains
```
railway domain --service frigoloco-backend  --environment production
railway domain --service frigoloco-frontend --environment production
railway domain --service frigoloco-backend  --environment testing
railway domain --service frigoloco-frontend --environment testing
```
This yields the two public backend URLs and the two public frontend URLs.

### 7. Wire the frontend build var, then deploy
Set each environment's frontend `VITE_API_BASE_URL` to that environment's **backend** public URL (build-time), then deploy:
```
railway variable set VITE_API_BASE_URL=https://<prod-backend-domain> --service frigoloco-frontend --environment production
railway variable set VITE_API_BASE_URL=https://<test-backend-domain> --service frigoloco-frontend --environment testing
railway up --service frigoloco-backend  --environment production -d
railway up --service frigoloco-frontend --environment production -d
railway up --service frigoloco-cron     --environment production -d
# repeat the three for --environment testing
```

### 8. Verify
- `GET https://<backend-domain>/health` → 200 (`db:true` once DB_URL is correct).
- Open each frontend URL; confirm it loads and its network calls hit the matching backend.
- cron: `railway logs --service frigoloco-cron` shows the scheduler registering its 7 jobs; confirm exactly 1 replica.

---

## Procedure - upgrade / redeploy

**GitHub path (current):** push to the watched branch → Railway auto-builds and redeploys the affected services. To force a redeploy without a code change: `railway redeploy --service <name> --environment <env>`. To change behaviour, set/adjust the service variable and Railway redeploys (unless `--skip-deploys`).

**Schema changes:** no Alembic. Apply plain SQL directly against the target DB before/with the deploy:
```
APP_ENV=production python backend/scripts/apply_migration.py 000N_<name>.sql
```
`schema.sql` is known to lag the migrations (it was missing `expiry_dates`/`weekly_fridge_count`/`husky_epc` when production was bootstrapped), so a fresh DB needs `apply_schema.py` **then** all `scripts/migrations/*.sql` (they are idempotent; `0009_fridge_stock_latest_only` no-ops/fails-benign on a fresh DB because it migrates an old `stock_snapshots` table that fresh DBs never had).

---

## Deferred: image hosting (D1 Option B)

When we move off GitHub builds to prebuilt images:
1. Pick a registry (recommendation: GHCR private under `1504168`, wire Railway pull credentials).
2. Add the runtime-config frontend change so one image serves both environments (nginx writes `/config.js` from `API_BASE_URL` at boot; `api.ts` reads `window.__APP_CONFIG__`, falling back to `VITE_API_BASE_URL` then localhost).
3. Build + push `frigoloco-backend`, `frigoloco-frontend`, `frigoloco-cron`.
4. Point each Railway service at its image (`railway add --image <ref>` / service source connect); set the same per-environment variables.
5. Upgrade flow becomes: rebuild → push new tag → `railway redeploy` (or update the image ref).

---

## Risks & limitations

- **Staged-changes model:** CLI-created services do not appear live until applied; a half-staged state is easy to create. Verify with `railway service list` after each change.
- **Monorepo root directory** is currently a dashboard/API setting, not a CLI flag - the one manual UI step in an otherwise CLI-driven flow.
- **cron single-replica** is a correctness requirement, not a preference.
- **Ephemeral disk:** `RAW_ARCHIVE_DIR` writes raw Husky payloads to local disk; on Railway that is lost on redeploy unless a volume is attached (blob archive is not built yet).
- **Production data is trailing-window only:** the initial production sync loaded the routine windows (48h purchases/restock, 14d reviews), not full history. A `cron.jobs.backfill` run is needed for full historical parity with turntable.
- **Secrets:** `turntable` URL and `FRIGOLOCO_API_*` live only in the unreadable base `.env`; they must be provided to set the corresponding Railway variables. `.env.production` / `.env.test` are git-ignored and never committed.
