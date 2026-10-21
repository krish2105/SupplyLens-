# SupplyLens

Evidence-grounded inventory and procurement decisions: real sales forecasting, time-aware
supplier-policy evidence, constrained replenishment planning, approval-bound purchase-order
drafts, and a sandbox execution path that is reconciled before it is called done.

> **Status:** P0 vertical slice implemented and verified locally (see `PROJECT_STATUS.md`).
> Not a production system. No real ERP, no enterprise sign-in, no generative LLM.

## What is real and what is simulated

| Area | Source | Label in the app |
|---|---|---|
| Sales history (1,067,371 rows, Dec 2009 – Dec 2011) | UCI Online Retail II, CC BY 4.0, DOI 10.24432/C5CG6D | Observed |
| Forecasts | Seasonal-naive baseline trained on that history | Forecast |
| Stock positions, suppliers, purchase costs, MOQs, lead times, capacity, supplier agreements (UCI workspace) | Generated from assumption set `uci-sim-ops v1` (seed 20111208) | Simulated / Assumed |
| Demo workspace data and contracts | Execution-pack fictional fixtures + the spec's reference case | Synthetic |
| Purchase orders | Local sandbox ERP schema (`sandbox_erp`) | Sandbox only |

The UCI StockCodes are never joined to any other public dataset. Selling price is not purchase cost.

## Architecture

```
apps/web/            Next.js 16 (App Router, strict TS), Tailwind 4, ECharts 6, React Three Fiber 9, Motion
services/api/        FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic + psycopg 3   (package: supplylens)
services/worker/     Postgres job queue + outbox dispatcher                         (package: supplylens_worker)
ml/                  UCI adapter, dense series, seasonal naive, metrics             (package: supplylens_ml)
optimisation/        CP-SAT planner, independent validator, temporal terms, replenishment (package: supplylens_opt)
tests/               pytest against real PostgreSQL (RLS, idempotency, planner, agent, API)
apps/web/e2e/        Playwright journeys + axe accessibility scans
```

PostgreSQL 17 + pgvector is the only database. Every tenant table has forced row-level
security; the app connects as a non-owner role without BYPASSRLS. Retrieval uses Postgres
full-text (lexical) + local `bge-m3` embeddings (Ollama) fused with reciprocal-rank fusion.

## Run locally (macOS, verified 2026-10-21 UTC)

Prerequisites: Homebrew PostgreSQL 17 with pgvector running on `/tmp:5432`, `uv`, Node 20+,
Ollama with `bge-m3:567m` (optional; retrieval falls back to lexical-only without it).

```bash
cp .env.example .env
./scripts/dev_db.sh
uv sync
uv run alembic -c services/api/alembic.ini upgrade head
SUPPLYLENS_MIGRATION_URL=postgresql+psycopg://supplylens_owner:supplylens_owner_dev@localhost:5432/supplylens_test uv run alembic -c services/api/alembic.ini upgrade head
python3 scripts/download_datasets.py --dataset online_retail_ii
uv run python -m supplylens.bootstrap
```

Start the three processes (separate terminals):

```bash
uv run uvicorn supplylens.api.app:app --host 127.0.0.1 --port 8000
uv run python -m supplylens_worker.main
npm --prefix apps/web install && npm --prefix apps/web run dev
```

Open http://localhost:3100 and choose a development account.

## Tests

```bash
uv run pytest -q
npm --prefix apps/web run typecheck
npx --prefix apps/web playwright test -c apps/web/playwright.config.ts
```

Playwright expects the API, worker and web app to be running.

## Try the reference case

1. Sign in as **Dev Planner**, switch to **Demo (fictional)**.
2. Investigations → set *Known by* 20 Oct 2026 09:00, *In force on* 20 Oct 2026 → Start investigation.
   The plan is 30 units from Reference Supplier B for USD 180, because A's amendment (MOQ 40) is in force.
   Repeat with 19 Oct: 30 units from A for USD 150, and the amendment shows as an upcoming change.
3. Sign in as **Dev Approver** → Approvals → approve. The worker submits to the sandbox ERP, reads the
   order back and marks the draft **RECONCILED**.

## Licences

UCI Online Retail II: CC BY 4.0 — Chen, D. (2012). Online Retail II. UCI Machine Learning Repository,
https://doi.org/10.24432/C5CG6D. Raw data is not committed (`data/raw/` is git-ignored).
