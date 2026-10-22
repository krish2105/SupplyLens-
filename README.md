<div align="center">

# SupplyLens

**Evidence-grounded inventory and procurement decisions**

Trained demand forecasts · time-aware supplier-policy evidence · constrained replenishment planning ·
approval-bound purchase orders that are reconciled before they count as done.

![Python](https://img.shields.io/badge/Python-3.12-3776AB) ![FastAPI](https://img.shields.io/badge/FastAPI-0.158-009688)
![Next.js](https://img.shields.io/badge/Next.js-16-000000) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17%20%2B%20pgvector-336791)
![Tests](https://img.shields.io/badge/tests-296%20backend%20%C2%B7%20102%20browser-0F6B55)

<img src="docs/images/overview-dark.png" alt="SupplyLens overview with linked 3D warehouse" width="900" />

</div>

## Why SupplyLens

Planners need to know *what to order, from whom, and why* — and to prove it later. SupplyLens connects real
sales history, the supplier terms that were actually in force on the decision date, and an optimiser that never
invents a plan. Every recommendation carries an evidence packet (data cutoff, forecast version, cited contract
clause, constraint checks), every external write needs a bound approval, and every order is read back from the
target system before it is marked complete.

## Highlights

- **Two clocks for every decision** — *known by* (knowledge cutoff) and *in force on* (effective date), so
  historical replays never use documents that arrived later and amendments apply only from their effective date.
- **Trained forecasting** — LightGBM quantile and a compact quantile TCN, evaluated against seasonal naive on a
  frozen chronological protocol; artifacts are hash-verified before serving.
- **Deterministic planning** — OR-Tools CP-SAT with MOQ, pack multiples, lead times, budget and capacity, an
  independent validator, and explanations when a plan is infeasible.
- **Hybrid temporal retrieval** — PostgreSQL full-text + local `bge-m3` vectors, reciprocal-rank fusion,
  supersession-aware reranking (optional cross-encoder, off by default and unevaluated), abstention when the evidence is missing.
- **Lead-time-demand replenishment** — order-up-to level is the service-level quantile of demand over lead time + coverage,
  with day-to-day dependence measured from the SKU's own sales (simulation-checked, not yet validated on real history).
- **Controlled execution** — stateful LangGraph investigator, approvals bound to payload hash and expiry,
  separation of duties, transactional outbox, idempotent sandbox ERP, unknown-outcome reconciliation.
- **Multi-tenant by construction** — forced row-level security on 34 tables, non-owner database role,
  CSRF protection, atomic idempotency keys, database-shared rate limits, append-only audit trail, verified tenant
  export and certified deletion.
- **Operable** — alert queue with signed webhook, OpenTelemetry tracing, WAL archiving with a rehearsed point-in-time
  recovery, load-tested on a 100,000-chunk / 1,000,000-row reference data set ([`docs/operations/load-test.md`](docs/operations/load-test.md)).
- **Interface** — 15 screens, linked 3D/2D/table inventory, live investigation stream, ⌘K command palette,
  Light/Dark/System themes, WCAG-checked with axe on desktop and mobile.

| Forecast lab | Research results |
|---|---|
| <img src="docs/images/forecast-lab.png" alt="Forecast lab" /> | <img src="docs/images/research.png" alt="Research results" /> |
| **Policies & evidence** | **Supplier market** |
| <img src="docs/images/policies.png" alt="Policies and evidence" /> | <img src="docs/images/market.png" alt="Supplier market" /> |

## Measured results

All figures come from experiment artifacts in `artifacts/experiments/`; details in
[`docs/research/results.md`](docs/research/results.md).

| Study | Result |
|---|---|
| Forecasting (506 products, held-out 28 days) | MAE: seasonal naive 21.41 → LightGBM 15.37 → quantile TCN 15.08; trained models beat the baseline (95% CI excludes 0); TCN vs LightGBM statistically tied |
| Inventory simulation (simulated costs) | Lower forecast error did not lower simulated cost; changing the ordering policy cut it by ~£21k for every model |
| Time-aware retrieval (118 questions) | Wrong-version citations 7.4% → 0% with effective-date logic |
| Clause localisation (73 CUAD contracts) | Hybrid hit@3 76.7% vs vector 72.2% vs lexical 66.8% |
| InventoryBench (official evaluator, 1,320 instances) | SupplyLens policy 0.482 vs base-stock 0.433 |
| Investigator scenarios | 57 scenarios × 3 trials, 100% oracle-verified, 0 unapproved external writes |

Negative results are kept: vector-only retrieval beats the hybrid on ACORD, and accuracy-optimal medians
under-stock on heavy-tailed sales.

## Data

| Workspace | Sources | Labels |
|---|---|---|
| UCI Research | UCI Online Retail II — 1,067,371 rows, reconciled to the row (CC BY 4.0) + simulated stock, suppliers and agreements | Observed / Simulated |
| Contract research | ACORD clauses, 73 CUAD supply agreements with 2,176 expert labels, 295,058 World Bank awards (CC BY 4.0) | Observed |
| Demo | Fictional fixtures and a reference policy-change case | Synthetic |

Datasets are never joined across domains, raw files are immutable and hashed, and simulated values are labelled
everywhere they appear. Raw data is not committed; see `scripts/download_datasets.py`.

## Architecture

```
apps/web/            Next.js 16, TypeScript, Tailwind 4, ECharts, React Three Fiber
services/api/        FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg 3
services/worker/     PostgreSQL job queue (SKIP LOCKED, leases, fencing) + outbox dispatcher
ml/                  Data adapters, LightGBM quantile, quantile TCN (PyTorch), metrics
optimisation/        CP-SAT planner, validator, temporal terms resolution, replenishment
evaluations/         Frozen studies: forecasting, simulation, retrieval, InventoryBench, agent
packages/contracts/  OpenAPI document + generated TypeScript types (drift-checked)
infra/               Dockerfiles, PostgreSQL bootstrap; docker-compose.yml; CI workflow
```

## Getting started

Requirements: PostgreSQL 17 with pgvector, [uv](https://docs.astral.sh/uv/), Node 20+, optionally Ollama with `bge-m3`.

```bash
cp .env.example .env && ./scripts/dev_db.sh && uv sync
uv run alembic -c services/api/alembic.ini upgrade head
python3 scripts/download_datasets.py --dataset online_retail_ii
uv run python -m supplylens.bootstrap
uv run python evaluations/forecast_study.py

uv run uvicorn supplylens.api.app:app --port 8000      # API
uv run python -m supplylens_worker.main                 # worker
npm --prefix apps/web install && npm --prefix apps/web run dev   # http://localhost:3100
```

Full setup, backup/restore and operating procedures: [`docs/operations/runbook.md`](docs/operations/runbook.md).

## Testing

```bash
uv run pytest -q                       # 296 tests against real PostgreSQL (incl. failed-migration / rollback / outage rehearsals)
(cd apps/web && npx playwright test)   # 102 browser tests: journeys, resilience, accessibility, Web Vitals, layout
uv run ruff check .                    # correctness, imports, bugbear and security rules
./scripts/check_contracts.sh           # API contract drift (the web client is typed from it)
./scripts/backup_restore_drill.sh      # logical restore rehearsal with hash verification
./scripts/pitr_drill.sh                # point-in-time recovery rehearsal on a scratch cluster
uv run python scripts/loadtest/seed_reference.py && scripts/loadtest/run_reference.sh   # ARC-07 reference workload
```

## Project status

A complete controlled product, verified locally. Not production-ready: enterprise sign-in (OIDC), a real ERP
connector and pilot validation are outstanding. See [`PROJECT_STATUS.md`](PROJECT_STATUS.md) and the
[acceptance register](docs/acceptance/acceptance_register.csv).

## Acknowledgements

UCI Online Retail II (Chen, 2012, doi:10.24432/C5CG6D); ACORD and CUAD (The Atticus Project); World Bank IPF
contract awards; InventoryBench (Peng et al.). Public datasets are used under CC BY 4.0 with attribution.

© 2026 Krishna Mathur. All rights reserved.
