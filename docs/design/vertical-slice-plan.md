# SupplyLens Vertical Slice Implementation Plan

**Goal:** One connected, tested flow: import UCI → validated sales → baseline forecast → feasible plan → cited policy evidence → draft action → approval → sandbox order → reconciled state, visible in the web app.

**Architecture:** Python package `supplylens` (services/api/src) shared by the FastAPI app and the worker; PostgreSQL 17 + pgvector with RLS; Next.js web app in apps/web talking to /api/v1 through a Next.js rewrite. See `docs/design/approved-design.md`.

**Tech Stack:** Python 3.12 (uv), FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg 3, pandas/pyarrow, OR-Tools, LightGBM, PyTorch, LangGraph; Node 26, Next.js, TypeScript strict, Tailwind, Radix, next-themes, ECharts, React Three Fiber, Motion; pytest, Playwright.

## Global Constraints

- Raw files under `data/raw/` are never modified; every derived file records source hash.
- Every simulated/assumed value carries `value_kind` in (`observed`,`derived`,`forecast`,`assumed`,`simulated`) and `source_kind` in (`public`,`user_supplied`,`generated`).
- Money: integer minor units + ISO currency. Quantities: integers with unit code.
- No generative LLM. Embeddings: Ollama `bge-m3`, lexical fallback.
- No metric is written to docs unless produced by a command in this repo.
- App DB role `supplylens_app` is NOT owner and has no BYPASSRLS; tenant set with `SET LOCAL app.tenant_id`.
- Mutations require `Idempotency-Key` header.

---

### Task 1: Python workspace, config, database bootstrap

**Files:** `pyproject.toml`, `services/api/src/supplylens/{__init__,config,db}.py`, `services/api/alembic.ini`, `services/api/migrations/`, `scripts/dev_db.sh`, `.env.example`, `tests/conftest.py`, `tests/test_db_rls.py`

**Produces:** `supplylens.config.settings` (`database_url`, `admin_database_url`, `storage_dir`, `ollama_url`); `supplylens.db.session_for(tenant_id: UUID) -> ContextManager[Session]` that sets `app.tenant_id` locally.

- [ ] Create DBs `supplylens` and `supplylens_test`, owner role `supplylens_owner`, app role `supplylens_app`, `CREATE EXTENSION vector`.
- [ ] Migration 0001: tenants, users, memberships, datasets, ingestion_batches, quarantine, products, locations, sales_daily, sales_lines, returns, jobs, outbox, audit_events; RLS `ENABLE` + `FORCE` with `USING/WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)`.
- [ ] Test: app role with tenant A context sees 0 rows of tenant B; missing context returns 0 rows; insert with wrong tenant raises.
- [ ] Run `uv run pytest tests/test_db_rls.py -v` → PASS. Commit.

### Task 2: UCI qualification and ingestion (DAT-001..004, BUS-001/002)

**Files:** `ml/supplylens_ml/uci.py`, `services/api/src/supplylens/ingest/uci.py`, `tests/test_uci_ingest.py`

**Produces:** `qualify_uci(zip_path) -> QualificationReport` (rows per sheet, accepted/returns/quarantined counts, date span, totals); `ingest_uci(tenant_id, zip_path) -> batch_id` (idempotent by file hash).

- [ ] Tests on a small synthetic XLSX built in the test: cancellation `C` invoice → returns; negative qty non-C → returns; missing StockCode/price<0/bad date → quarantine with reason; accepted+returns+quarantined == input rows; second ingest of same hash returns same batch, no duplicate rows; raw file hash unchanged after ingest.
- [ ] Implement; run on real ZIP; write `artifacts/reports/uci_qualification.json`. Commit.

### Task 3: Seasonal-naive forecast service (ML-002 baseline)

**Files:** `ml/supplylens_ml/baselines.py`, `services/api/src/supplylens/forecasting/service.py`, `tests/test_seasonal_naive.py`

**Produces:** `seasonal_naive(history: pd.Series, origin: date, horizon=28, season=7) -> DataFrame[date,q10,q50,q90]` with quantiles from training-only residuals; `ForecastService.run(tenant, sku_ids, origin, model_version) -> forecast_run_id`.

- [ ] Tests: forecast at origin uses only data ≤ origin (inject a spike after origin, output unchanged); q10≤q50≤q90; non-negative; MASE undefined when training seasonal diffs all zero.
- [ ] Implement, persist forecast_runs + forecast_points. Commit.

### Task 4: Planner + validator + policy fixture (ARC-05, EXE-003/005)

**Files:** `optimisation/supplylens_opt/planner.py`, `optimisation/supplylens_opt/validator.py`, `tests/test_planner_fixture.py`

**Produces:** `plan(request: PlanRequest) -> PlanResult(status, lines, objective_minor, violations, explanation, input_hash)`.

- [ ] Tests: JSON fixture as_of 2026-09-30 → A 30 / 15000 minor; as_of 2026-10-02 → B 30 / 18000; spec-text variant same; budget 140 → INFEASIBLE with `budget` in explanation; validator rejects a hand-built line below MOQ.
- [ ] Implement CP-SAT (1 worker, seed 0). Commit.

### Task 5: Documents and temporal retrieval (EXE-004/005, ARC-04 subset)

**Files:** migration 0002 (documents, document_versions, chunks with tsvector + vector(1024)), `services/api/src/supplylens/knowledge/{ingest,retrieve,embed}.py`, `tests/test_retrieval_temporal.py`

**Produces:** `search(tenant, query, as_of, mode) -> list[Evidence]`; `applicable_terms(tenant, supplier_id, sku_id, as_of) -> TermsResult | Conflict`.

- [ ] Tests: amendment with known_at after as_of excluded; amendment effective after as_of is known but not applicable; conflicting active versions → `Conflict` with both citations; other tenant's chunks never returned; embedding fallback when Ollama unreachable.
- [ ] Commit.

### Task 6: Actions, approvals, outbox, sandbox ERP (BUS-005..007, EXE-007..009)

**Files:** migration 0003 (recommendations, actions, approvals, idempotency_keys, sandbox_erp.orders), `services/api/src/supplylens/actions/*.py`, `services/worker/src/supplylens_worker/main.py`, `tests/test_actions.py`

- [ ] Tests: same Idempotency-Key + same body → same action; different body → 409; approval by preparer → 403; approval after quantity edit → stale; dispatch twice → one sandbox order; injected timeout-after-success → UNKNOWN_OUTCOME then reconcile → CONFIRMED with same external id; reconciliation reads order back and compares qty/supplier.
- [ ] Commit.

### Task 7: Agent graph (deterministic LangGraph)

**Files:** `services/api/src/supplylens/agent/graph.py`, `tests/test_agent_graph.py`

- [ ] Tests: fixture run ends WAIT_FOR_APPROVAL with prepared action citing amendment; conflict run ends REVIEW_REQUIRED with no action; run events persisted and retrievable after process restart.
- [ ] Commit.

### Task 8: FastAPI endpoints + dev auth

**Files:** `services/api/src/supplylens/api/*.py`, `tests/test_api.py`

Endpoints: `GET /health`, `GET /api/v1/me`, `POST /api/v1/dev/session`, `GET /api/v1/datasets`, `GET /api/v1/datasets/{id}/quality`, `GET /api/v1/products`, `GET /api/v1/products/{sku}/sales`, `POST /api/v1/forecasts`, `GET /api/v1/forecasts/{id}`, `POST /api/v1/plans`, `GET /api/v1/evidence/search`, `POST /api/v1/agent-runs`, `GET /api/v1/agent-runs/{id}/events`, `POST /api/v1/actions/{id}/approve|reject`, `GET /api/v1/actions`, `GET /api/v1/inventory`.

- [ ] Tests: viewer cannot approve; unauthenticated 401; invalid horizon 422. Commit.

### Task 9: Web app slice

**Files:** `apps/web/**`

- [ ] Next.js app with theme provider (Light/Dark/System persisted, no flash), shell nav, Overview (KPIs from API + 3D warehouse), Data admission, Products/Forecast, Scenario (plan), Evidence, Approvals.
- [ ] Playwright journey: sign in as planner → open product → run forecast → run plan → start agent run → sign in as approver → approve → see CONFIRMED order. Theme toggle persists after reload.
- [ ] Commit.

### Task 10: Evidence and continuity

- [ ] Update PROJECT_STATUS.md, TASKS.md, DECISIONS.md, EVIDENCE_INDEX.md with executed commands and outputs only. Commit.
