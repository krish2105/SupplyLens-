# Hosted demo on Vercel

**URL:** https://supplylens-self.vercel.app · **Data:** the fictional Demo workspace and public UCI Online Retail II research
data (CC BY 4.0) · **Sign-in:** demo role accounts (profile `demo`, owner decision D-050) · **Status:** verified 2026-10-22
(browser journeys, layout and accessibility suites against the live URL: 50 passed, 1 skipped; journeys repeated 12/12).

## Shape
One Vercel project (`supplylens`) with two [Services](https://vercel.com/docs/services) (`vercel.json`):

| Path | Service | What runs |
|---|---|---|
| `/api/*`, `/health` | `api` | FastAPI as a Python function (service root `deploy/vercel-api`; its buildCommand `scripts/vercel/build_api.py` stages the code) |
| everything else | `web` | the Next.js app (`apps/web`) |

Postgres is Neon (Vercel Marketplace), pgvector enabled. The API connects as `supplylens_app`, a role without owner rights
or row-level-security bypass; the Neon owner credentials are used only by the one-time setup below. Neon's variables are
marked sensitive by Vercel and cannot be downloaded, so setup runs inside the deployment.

## Demo safeguards (D-051, D-052)
- **Shared accounts, closed administration.** The role accounts are public and passwordless, so the `demo` profile refuses
  workspace administration (memberships, new workspaces, imports, model promotion), tenant export and tenant deletion for
  every role (HTTP 403). Reading, investigating, approving, reconciling and booking receipts stay open.
- **Self-cleaning orders.** Each demo sign-in releases order lines nobody has touched for an hour (an audited system
  cancellation), so the next visitor still sees the reference case to order.
- **No owner credentials while serving.** The generated entrypoint keeps the Neon owner URL only while
  `SUPPLYLENS_SETUP_TOKEN` is set, and otherwise deletes the integration's owner variables (`DATABASE_URL*`, `POSTGRES_*`,
  `PG*`, `NEON_*`) from the process before the app loads; the app refuses to start in `demo` if an owner URL remains.
  Residual: Vercel still injects those variables into the function at start; scoping or removing them is an owner
  action in the Vercel/Neon integration settings.

## What differs from a full deployment (honest limits)
- **No worker process.** `SUPPLYLENS_INLINE_JOBS` (set by the bundle) runs a workspace's queued agent runs and order
  dispatches inside the request that queued them, with the worker's own leases and fencing.
- **No trained models.** PyTorch and LightGBM are not bundled; forecasts use the seasonal-naive baseline and say so.
  Research numbers are read from the published study results.
- **No embedding server.** Retrieval runs lexical-only and labels itself degraded.
- **Invoice lines trimmed** to 2011-06-01 onwards (the exceptions screen reads 90 days of prices) to fit Neon's free
  tier; daily sales, stock, terms and documents are complete.
- **Cold starts.** The first request after idle loads the Python function (several seconds).
- **After a redeploy**, a tab opened on the previous deployment may fail to load a page bundle; refreshing fixes it.

## Deploy
**Every push to `main` deploys** (Vercel Git integration, both services). The `api` service's committed files are
`deploy/vercel-api/index.py`, `pyproject.toml` (dependencies pinned to `uv.lock`; CI fails on drift), `source.sha256` (digest of
the staged API sources: Vercel rebuilds a service only when files under its root change, so a backend-only commit must
change this file; CI fails when it is stale) and `hosted_storage/`
(the cited documents); its buildCommand stages the code trees, migrations, published metrics and study registry.

```bash
python3 scripts/vercel/build_api.py --pin       # after changing uv.lock or any API/worker/ML/optimiser code: re-pin, commit
python3 scripts/vercel/build_api.py --check     # what CI runs (dependency pins and source.sha256)
```

Only when the demo **data** should change (first install on an empty database; an export made before migration 0010
lists `chunks.embedding` and must be regenerated):
```bash
SUPPLYLENS_STORAGE_DIR=$PWD/build/hosted-storage uv run python -m supplylens.bootstrap   # against a fresh database
uv run python scripts/vercel/export_hosted_data.py --db postgresql://supplylens_owner:...@localhost:5432/sl_hosted
python3 scripts/vercel/build_api.py --storage build/hosted-storage   # refresh the committed hosted_storage/
vercel deploy --prod      # a CLI deploy carries the git-ignored deploy/vercel-api/hosted_data/ that /setup/data loads
```
First install on an empty database: add a 32+ character `SUPPLYLENS_SETUP_TOKEN` (sensitive) and
`SUPPLYLENS_APP_DB_PASSWORD`, deploy, then `POST /api/v1/internal/setup/schema` and `/setup/data` with header
`X-Setup-Token`; remove the token and redeploy (the endpoint then does not exist: 404). **Schema upgrades** (a new
migration, e.g. 0010) use the same steps with only `/setup/schema`: it is idempotent and migrates to head. Without the token
the serving function holds no owner credentials, so it cannot migrate. Setup copies each workspace's rows
through a staging table and inserts them under that workspace's row-level-security context; it refuses a role that can
bypass row-level security.

**Pending (Phase 6, 2026-10-24): migration 0011** (ERP connector state, receipt sync, worker heartbeats, new alert kinds)
has not been applied to the hosted database; it needs the schema-upgrade steps above (owner action, OPS-P6-03). Until then
the deployed code detects the older schema and keeps the pre-Phase-6 behaviour (D-090). Ordering and reconciliation work,
but the connector state, ERP sync and heartbeats are not recorded. The hosted demo has no worker process, so worker
health reports `inline (serverless)`.

Runtime variables on Vercel: `SUPPLYLENS_ENVIRONMENT=demo`, `SUPPLYLENS_DEV_AUTH=true`, `SUPPLYLENS_COOKIE_SECURE=true`,
`SUPPLYLENS_SESSION_SECRET`, `SUPPLYLENS_ALERT_WEBHOOK_SECRET`, `SUPPLYLENS_APP_DB_PASSWORD` (all generated, sensitive), plus
Neon's own `DATABASE_URL_UNPOOLED`. The demo profile refuses to start with default secrets, insecure cookies or owner
credentials for the API.

`render.yaml` and `scripts/render/` remain as a container-based alternative (API and worker as long-running processes).
