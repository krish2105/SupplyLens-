# SupplyLens — approved design (2026-10-21)

Approved by the project owner in session on 2026-10-21. This document records the
choices made on top of the execution pack (`execution_pack/`, `docs/specs/`). Where it
is silent, the pack's specification governs.

## Owner decisions

| Topic | Decision |
|---|---|
| Repository root | `SupplyLens/`. Original starter packs and ZIPs stay untouched beside it and are git-ignored. |
| M5 | Skipped for now. Can be added later as an academic-only study under `data/raw/academic/m5/`. |
| Public data now | UCI Online Retail II only. CUAD/ACORD/World Bank/TED/InventoryBench deferred. |
| Generative LLM | None. Answers are extractive with citations; agent nodes are deterministic. A provider-neutral adapter slot exists but is disabled. |
| Embeddings | Local `bge-m3` through Ollama (1024-d). Lexical-only fallback when Ollama is unavailable. |
| Visual style | Bold, Awwwards-grade, built on the spec's palette. Data screens stay dense and readable; motion respects reduced-motion. |

## Architecture

Monorepo, native development runtime, `docker-compose.yml` for clean-setup checks.

```
apps/web/            Next.js (App Router, strict TS), Tailwind + Radix primitives,
                     next-themes, ECharts (only chart library), React Three Fiber, Motion
services/api/        FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic + psycopg 3, /api/v1
services/worker/     Postgres job queue (FOR UPDATE SKIP LOCKED, lease, heartbeat, fencing),
                     outbox dispatcher, sandbox ERP adapter, reconciliation
ml/                  UCI adapter, features, seasonal naive, LightGBM quantile, quantile TCN
optimisation/        CP-SAT replenishment planner, independent validator, lost-sales simulator
evaluations/         Frozen task sets and experiment runners
tests/               pytest (real Postgres), Playwright journeys
```

API and worker share one Python package (`supplylens`) so domain services, validation
and authorisation are written once. Database: Homebrew PostgreSQL 17 + pgvector 0.8.x,
database `supplylens`, migrations run as owner role, the app connects as a non-owner role
without BYPASSRLS, tenant context set per transaction (`SET LOCAL app.tenant_id`).

## Workspaces (tenants)

1. **UCI Research** — real UCI Online Retail II sales (CC BY 4.0, attribution). One
   location: the online retailer itself. `Country` is customer residence, never a
   warehouse. Stock, supplier terms, costs and lead times do not exist in the source;
   they come from a versioned *assumption configuration* and every such value carries
   `value_kind = simulated`.
2. **Demo** — the pack's fictional DEMO suppliers, products, snapshots, POs and
   contracts plus the policy-change fixture. `source_kind = generated`.

The two workspaces never share keys. No public dataset is joined to another.

## Data pipeline

`data/raw/core/online_retail_ii/` holds the publisher ZIP (immutable, SHA-256 in the
receipt). Bronze: extracted XLSX → parquet per sheet. Silver: typed sales lines with
lineage (`source_row`, sheet, hash); cancellations (`Invoice` starting `C`) and
negative quantities kept in a separate returns table; invalid rows quarantined with a
reason. Gold: daily fulfilled positive units per StockCode, zero-filled only inside the
product's active range and flagged as "no recorded sales" rather than "zero demand".
Reconciliation report accounts for 100% of rows (accepted / returns / quarantined).

## Forecasting protocol

Target: daily unit sales per StockCode, 28-day horizon, quantiles 0.1/0.5/0.9.
Cohort: products with sales on at least N days in the training window (decided from
training data only). Chronological splits: train → validation origins → untouched final
test of the last 28 days before 2011-12-09. Models: seasonal naive (s=7, intervals from
training residuals), LightGBM global quantile model (horizon as feature, lagged features
shifted before origin), compact causal dilated TCN with a direct 28×3 quantile head,
three seeds on MPS. Metrics: MAE, MASE (training-scale; undefined when the denominator
is zero, reported with counts), pinball per quantile and horizon, 80% coverage and
width, quantile crossing rate. Models registered in Postgres
(TRAINING/EVALUATED/CANDIDATE/CHAMPION/RETIRED/FAILED); champion chosen by validation.

## Planning

CP-SAT with integer minor units: supplier eligibility as of the decision date, MOQ,
order multiples, budget, capacity, lead-time deadline. One supplier per line by
default. Returns status, objective breakdown, input hash and solver settings
(1 worker, fixed seed). An independent validator rechecks every accepted line.
Infeasible problems return the violated constraints (found by testing each constraint
family relaxed), never an invented plan. Reference fixture: A 30u/USD 150 before the
amendment, B 30u/USD 180 after; both the JSON fixture and the spec-text variant are tested,
plus a delayed-knowledge variant and an unresolved-conflict variant (review required).

## Retrieval

Documents carry `known_at`, `valid_from`, `valid_to`, `supersedes_version_id`, hash and
section locators. Candidates: Postgres full-text (described as lexical, not BM25) and
exact pgvector cosine search, both filtered inside SQL by tenant, ACL, `known_at <= as_of`
and effective date; merged with reciprocal-rank fusion; then a deterministic rule-based
reranker (entity match, effective-date applicability, supersession). Answers are
structured claims with extracted spans and citations (document/version/section). Missing
or conflicting evidence yields an abstention or a review-required state.

## Agent and actions

LangGraph state graph with deterministic nodes: ACCEPT → PLAN → GATHER_EVIDENCE →
COMPUTE → CHECK → PREPARE_ACTION → WAIT_FOR_APPROVAL → COMMIT_OUTBOX → EXECUTE → VERIFY →
COMPLETE, with FAILED/CANCELLED/STALE_PLAN/UNKNOWN_OUTCOME terminals and bounded
CHECK loops. Checkpoints persisted in Postgres behind a tenant-checking wrapper.
Action states: DRAFT → VALIDATED → PENDING_APPROVAL → APPROVED → QUEUED → SUBMITTED →
CONFIRMED → RECONCILED, plus REJECTED, STALE, UNKNOWN_OUTCOME. Approval binds payload
hash, data/policy/forecast versions, max spend, approver and expiry; self-approval is
blocked. Mutations require an `Idempotency-Key`. The sandbox ERP lives in its own schema,
deduplicates by external idempotency key and supports injected "timeout after success"
so reconciliation can be demonstrated.

## Identity

Development: seeded users per role (Viewer, Planner, Approver, Tenant Admin) selected
with a dev-only sign-in that is visibly labelled. OIDC is reported as
NOT_CONFIGURED. Role checks happen server-side on every request and tool call.

## Interface

Bold direction on the spec palette (graphite, warm off-white, teal selection, cobalt
forecast, amber risk). Overview uses the real schematic 3D warehouse as its hero; racks
map to actual SKU-location rows. Large tabular numerals, glass panels, staged entrance
motion (disabled under reduced motion), no idle render loop. Screens: Data admission,
Overview, Inventory (table + 2D + 3D linked), Forecast lab, Scenario studio, Policies &
evidence, Approvals & actions, Runs, Settings. Shared state (tenant, as-of, product,
scenario, model run) serialised to the URL. Provenance chips: Observed, Forecast,
Assumed, Simulated.

## Testing and evidence

pytest against a real Postgres test database (RLS, idempotency, planner fixture,
temporal retrieval, leakage checks), Playwright for browser journeys, axe for
accessibility. Only executed results are written to `EVIDENCE_INDEX.md`.

## First milestone

Import UCI → validated sales view → seasonal-naive forecast → feasible plan under
simulated terms → cited policy evidence → draft action → approval → sandbox order →
reconciled persisted state, visible in the web app. Later milestones: trained model
comparison, retrieval evaluation, full UI and 3D, enterprise controls.
