---
name: redeploy
description: Redeploy the FrigoLoco backend / frontend / cron services to Railway after a code change. Use when the user says "redeploy", "deploy to Railway", "push the update live", "ship this", or after editing backend/, frontend/, or cron/ code that needs to reach production or testing. Handles the monorepo, per-environment services, build-arg wiring, and post-deploy verification.
allowed-tools: Bash, Read
metadata:
  version: "1.0.0"
  domain: deployment
  triggers: redeploy, deploy, Railway, ship, push live, release, deploy backend, deploy frontend, deploy cron
  scope: operations
---

# Redeploy FrigoLoco to Railway

Deploy the local, tested code to Railway via `railway up` (uploads the current
directory as the build context — the tested Dockerfiles build unchanged, no
GitHub connection or monorepo Root-Directory juggling needed). This is the
same mechanism the tag-push CI (`.github/workflows/deploy-railway.yml`) uses.

## Prerequisites (check first, fix if missing)

```bash
export PATH="$PATH:$(npm root -g)/../bin"     # railway CLI is npm-global
railway whoami                                 # must be logged in; if not: user runs `! railway login`
railway link --project 9febc1ff-2f7c-4d34-b4bb-004948f8d130   # link once if needed
```

Run everything from the repo root: `/Users/ismailhosen/Documents/Frigoloco`.

## Service map (Railway project "Frigo Loco ERP", id 9febc1ff-2f7c-4d34-b4bb-004948f8d130)

| Component | Root dir | production service | testing service |
|-----------|----------|--------------------|-----------------|
| backend   | `backend`  | `authentic-kindness`    | `generous-endurance` |
| frontend  | `frontend` | `supportive-expression` | `feisty-motivation`  |
| cron      | (repo root, `cron/Dockerfile`) | `frigoloco-cron` *(not created yet)* | *(not created yet)* |

Public URLs:
- production frontend: https://supportive-expression-production-c16f.up.railway.app
- production backend:  https://authentic-kindness-production-78a1.up.railway.app
- testing frontend:    https://feisty-motivation-testing.up.railway.app
- testing backend:     https://generous-endurance-testing.up.railway.app

> If the Railway services are ever renamed, update this table. Confirm current
> names with `railway service list --environment <env>`.

## Procedure

1. **Scope the deploy.** Decide which component(s) and which environment(s). If
   the user didn't say, infer from what changed:
   ```bash
   git status --short backend frontend cron
   ```
   Default target is **production** unless the user says testing/both. Ask only
   if genuinely ambiguous.

2. **Keep the upload small.** `railway up` respects `.gitignore`. Confirm the
   heavy generated dir is ignored (it caused a 500 once):
   ```bash
   git check-ignore cron/raw_archive backend/raw_archive   # should print both
   ```

3. **Deploy each affected component** (from repo root, `--detach` to return
   immediately). Railway uses the service's Root Directory as the build context.
   ```bash
   # backend
   railway up --service authentic-kindness  --environment production --detach   # prod
   railway up --service generous-endurance  --environment testing    --detach   # test
   # frontend
   railway up --service supportive-expression --environment production --detach
   railway up --service feisty-motivation     --environment testing    --detach
   ```

4. **Frontend build-arg caveat.** `VITE_API_BASE_URL` is baked at BUILD time from
   the per-environment Railway variable (already set to each env's backend URL).
   Only touch it if the backend URL changed:
   ```bash
   railway variable set 'VITE_API_BASE_URL=<backend-url>' --service <frontend-svc> --environment <env> --skip-deploys
   # then redeploy that frontend
   ```

5. **Schema changes** (no Alembic — plain SQL, idempotent). Apply BEFORE/with the
   backend deploy, per target DB:
   ```bash
   APP_ENV=production backend/.venv/bin/python backend/scripts/apply_migration.py 000N_<name>.sql
   APP_ENV=test       backend/.venv/bin/python backend/scripts/apply_migration.py 000N_<name>.sql
   ```
   (`APP_ENV=production` → sakura DB via `.env.production`; `APP_ENV=test` → turntable via `.env.test`; unset → base `.env`.)

6. **Verify** each deployed service (build + rollout takes ~1–3 min):
   ```bash
   # backend healthy AND auth live (protected route rejects no-token)
   curl -s "https://<backend-url>/health"                       # {"status":"ok","db":true}
   curl -s -o /dev/null -w '%{http_code}\n' "https://<backend-url>/api/v1/products?limit=1"  # 401 = auth live
   # frontend serving
   curl -s -o /dev/null -w '%{http_code}\n' "https://<frontend-url>/login"   # 200
   ```
   Poll in a short loop until green; a fresh deploy briefly returns 404 while rolling out.

7. **Report** the deployed components, environments, and the verification results
   (health, auth-gated, frontend up). Surface any build failure with its Railway
   build-logs URL rather than declaring success.

## Notes / gotchas (learned the hard way)

- `railway up` needs the **service to already exist** (materialized) in the target
  environment; it 404s otherwise. New services are created once via the dashboard
  (Empty Service → set Root Directory → Deploy), then `railway up` deploys code.
- **cron** must run **exactly 1 replica** (no scheduler lock; two would double-fire
  every job). It also needs `FRIGOLOCO_API_*` creds set as Railway variables.
- Secrets (`SECRET_KEY`, `DB_URL`, `FRIGOLOCO_API_*`) live only as Railway
  variables — never print or commit them. `.env.production` / `.env.test` are
  git-ignored and are NOT uploaded.
- Full runbook + rationale: `specs/0007-railway-deployment/`.
