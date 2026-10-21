# SupplyLens

Evidence-grounded inventory and procurement decisions: trained unit-sales forecasts, time-aware
supplier-policy evidence, constrained replenishment planning, approval-bound purchase-order drafts, and a
sandbox execution path that is read back and reconciled before it counts as done.

> **Status:** P0 controlled product demonstrated locally (46/80 acceptance items passed, 18 partial; see
> `PROJECT_STATUS.md` and `docs/acceptance/acceptance_register.csv`). Not a production system: no real ERP,
> no enterprise sign-in, no generative LLM (owner decision).

## Results at a glance (from `docs/research/results.md`)

| Study | Result |
|---|---|
| F1 forecasting, 506 UCI products | MAE: seasonal naive 21.41 → LightGBM 15.37 → quantile TCN 15.08; trained models beat the baseline (CI excludes 0), TCN vs LightGBM tied |
| S1 simulated inventory | Better forecasts did **not** lower simulated cost; switching the ordering policy cut it by about £21k for every model |
| R2 time-aware retrieval | Wrong-version citations 7.4% → 0% with effective-date logic (118 generated questions) |
| C1 / R1 public contracts | Hybrid best inside CUAD contracts (hit@3 76.7%); vector-only best on ACORD (negative result for hybrid) |
| InventoryBench (official evaluator) | SupplyLens policy 0.482 vs base-stock 0.433 |
| Agent scenarios | 57 × 3 oracle-checked, 100% verified, 0 unapproved external writes |

## Workspaces

| Workspace | Contents | Labels |
|---|---|---|
| UCI Research | Real UCI Online Retail II sales (1,067,371 rows, CC BY 4.0) + simulated stock, suppliers, costs and agreements | Observed / Simulated |
| Contract research | ACORD clauses, 73 CUAD supply agreements with expert labels, 295,058 World Bank awards (CC BY 4.0) | Observed (public) |
| Demo (fictional) | Execution-pack fixtures and the spec's reference policy-change case | Synthetic |

No public dataset is joined to another. Selling price is never treated as purchase cost.

## Product

Overview · Exceptions · Inventory (linked 3D schematic / 2D floor plan / table) · Forecast lab (model choice,
backtest, model comparison) · Scenario studio · Investigations (deterministic LangGraph run, live event stream) ·
Approvals (exact payload, evidence packet, separation of duties, reconciliation) · Policies & evidence (hybrid
temporal search, amendment diff, expert clause labels) · Supplier market · Research · Value · Data admission ·
Administration · Settings. ⌘K command palette, Light/Dark/System themes, keyboard and screen-size support.

## Architecture

```
apps/web/            Next.js 16, TypeScript strict, Tailwind 4, ECharts 6, React Three Fiber 9, Motion
services/api/        FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic + psycopg 3 (package supplylens)
services/worker/     PostgreSQL job queue + outbox dispatcher (package supplylens_worker)
ml/                  UCI adapter, panel, seasonal naive, LightGBM quantile, quantile TCN (separate process), metrics
optimisation/        CP-SAT planner, independent validator, temporal terms, replenishment
evaluations/         Frozen studies: forecast, simulation, retrieval, InventoryBench, agent
packages/contracts/  OpenAPI document + generated TypeScript types (drift-checked)
tests/               131 pytest tests against real PostgreSQL; apps/web/e2e: 37 Playwright tests
infra/, docker-compose.yml, .github/workflows/ci.yml
```

PostgreSQL 17 + pgvector is the only database; tenant tables use forced row-level security and the app connects as a
non-owner role. Embeddings run locally (Ollama `bge-m3`).

## Run locally

Prerequisites: Homebrew PostgreSQL 17 + pgvector on `/tmp:5432`, `uv`, Node 20+, Ollama with `bge-m3:567m` (optional).
Full first-install sequence: `docs/operations/runbook.md`.

```bash
cp .env.example .env && ./scripts/dev_db.sh && uv sync
uv run alembic -c services/api/alembic.ini upgrade head
python3 scripts/download_datasets.py --dataset online_retail_ii
uv run python -m supplylens.bootstrap
uv run python evaluations/forecast_study.py
```

```bash
uv run uvicorn supplylens.api.app:app --host 127.0.0.1 --port 8000
uv run python -m supplylens_worker.main
npm --prefix apps/web install && npm --prefix apps/web run dev
```

Open http://localhost:3100 and choose a development account.

## Verify

```bash
uv run pytest -q
./scripts/check_contracts.sh
(cd apps/web && npx playwright test)
./scripts/backup_restore_drill.sh
```

## Try the reference case

Demo workspace → Investigations → *Known by* 20 Oct 2026 09:00 → Start: 30 units from Reference Supplier B for
USD 180 (A's amendment raised its MOQ). With 19 Oct: 30 units from A for USD 150. Sign in as Dev Approver →
Approvals → approve → the worker submits to the sandbox ERP, reads it back and marks it **RECONCILED**.

## Licences and attribution

UCI Online Retail II (Chen, 2012, doi:10.24432/C5CG6D), ACORD and CUAD (The Atticus Project), World Bank IPF
contract awards: CC BY 4.0. InventoryBench code MIT; its H&M-derived data terms were not reviewed for
redistribution. Raw data is not committed (`data/raw/` is git-ignored).
