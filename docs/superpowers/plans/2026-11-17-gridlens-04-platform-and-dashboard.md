# GridLens Plan 4 — Database, API, worker and EMS dashboard

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Swap the remaining supply-chain domain for the energy domain end to end — database tables, API, worker, approvals, plant adapter and every screen — so a peer can open GridLens, replay a day under any controller, press "Blackout" during the presentation and watch islanding, frequency, load-shedding with reasons, savings and carbon, with every number labelled observed, simulated or assumed.

**Architecture:** A forward migration (`0012_energy_domain`) drops supply-chain tables and creates energy tables with the same forced row-level security. An `energy` service package in the API wraps Plans 2–3 (parks, controllers, replays, what-if, bills, reports, explanations). A replay is computed for the whole day (worker locally, inline on the hosted demo) and the browser animates it; a stress-test event forks a new replay from the chosen step, which is exact because the simulator is deterministic. Approval-bound dispatch requests replace purchase-order actions and are delivered through a signed outbox to a sandbox plant adapter.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 17 RLS, Next.js 16, TanStack Query, ECharts, React Three Fiber, Playwright, axe.

**Spec:** §8, §9.1–§9.2, §11, §12.1. **Requires:** Plans 1–3 merged.

## Global Constraints

- Every tenant table: `tenant_id uuid not null`, `ENABLE` + `FORCE ROW LEVEL SECURITY`, policy `tenant_isolation` using `current_setting('app.tenant_id', true)` exactly as migration 0001 does; grants to `gridlens_app`.
- Routes follow `routes_research.py`: `APIRouter(prefix="/api/v1/...", dependencies=[Depends(csrf_guard)])`, `a: Actor = Depends(actor)`, `a.require(<operation>)`, data access through `tenant_session(a.tenant_id)`; writes take an `Idempotency-Key` through `idempotent(...)`.
- Authorization matrix operations added: `replay.run` (planner), `request.prepare` (planner), `request.approve` / `request.reject` (approver), `alert.ack` unchanged. Separation of duties: the approver of a request is never its requester.
- No PyTorch and no LightGBM in the API process: RL policies are served by `NumpyPolicy`, forecasts by `CachedForecaster` (falls back to seasonal naive).
- The API contract is regenerated (`./scripts/update_contracts.sh`) after every route change and checked (`./scripts/check_contracts.sh`); the web client is typed from it.
- Screens: existing components only (`PageHeader`, `Card`, `Stat`, `Chart`, `Button`, `Provenance`, `TableScroll`, `TabList`, `KV`, `Empty`, `QueryError`); both themes; WCAG checks with axe stay green; every number shows its provenance.
- Commit after each task; messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File map

| Path | Change |
|---|---|
| `services/api/migrations/versions/0012_energy_domain.py` | drop supply-chain tables, create energy tables |
| `services/api/src/gridlens/energy/{__init__,parks,replay,requests,plant_adapter,whatif,bills,report,alerts}.py` | energy service layer |
| `services/api/src/gridlens/api/routes_energy.py`, `routes_requests.py` | API |
| `services/api/src/gridlens/api/schemas.py` | energy schemas; supply-chain schemas removed |
| `services/api/src/gridlens/authz.py` | new operations |
| `services/worker/src/gridlens_worker/main.py` | replay and plant-command ticks |
| deleted: `planning/`, `simulation/`, `onboarding/`, `ingest/uci.py`, `integrations/`, `actions/`, `agent/`, `routes_decisions.py` (supply parts), `routes_onboarding.py`, supply-chain tests | supply-chain core |
| `tests/conftest.py`, `tests/test_energy_*.py` | test fixtures and API tests |
| `apps/web/lib/replay.ts`, `apps/web/components/{power-flow,soc-gauge,replay-player,park3d,shed-log,explain-panel}.tsx` | dashboard building blocks |
| `apps/web/app/(app)/{page,forecast,dispatch,stress-test,commitment,tenants,impact,whatif,research,approvals,policies}/page.tsx` | screens |
| `apps/web/app/(app)/layout.tsx` | navigation |
| `apps/web/e2e/{energy-journey,stress-test,approvals-energy}.spec.ts` | browser journeys |
| `scripts/precompute_replays.py`, `docker-compose.yml`, `.github/workflows/keep-warm.yml` | hosting and offline fallback |

---

### Task 1: Migration 0012 — energy domain tables

**Files:**
- Create: `services/api/migrations/versions/0012_energy_domain.py`
- Modify: `tests/conftest.py` (`TENANT_TABLES_CLEAR_ORDER`, sandbox truncation)
- Test: `tests/test_energy_schema.py`

**Interfaces:**
- Produces tables: `sites`, `park_tenants`, `replays`, `replay_steps`, `replay_events`, `shed_events`, `dispatch_requests`, `plant_commands`, schema `sandbox_plant` with `sandbox_plant.commands` and `sandbox_plant.fault_injection`.

- [ ] **Step 1: Write the failing test**

`tests/test_energy_schema.py`:
```python
from sqlalchemy import text

from gridlens.db import admin_engine

ENERGY = ["sites", "park_tenants", "replays", "replay_steps", "replay_events", "shed_events",
          "dispatch_requests", "plant_commands"]
GONE = ["products", "sales_lines", "sales_daily", "suppliers", "supplier_terms", "purchase_order_lines",
        "inventory_positions", "receipts", "plan_runs", "warehouse_slots", "public_awards", "clause_labels",
        "agent_runs", "agent_events", "actions", "approvals", "outbox"]


def test_energy_tables_exist_with_forced_rls():
    with admin_engine().connect() as c:
        rows = dict(c.execute(text(
            "select relname, relforcerowsecurity from pg_class where relname = any(:n) and relkind = 'r'"),
            {"n": ENERGY}).all())
    assert set(rows) == set(ENERGY) and all(rows.values())


def test_supply_chain_tables_are_gone():
    with admin_engine().connect() as c:
        left = c.execute(text("select relname from pg_class where relname = any(:n) and relkind = 'r'"),
                         {"n": GONE}).scalars().all()
    assert left == []
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_energy_schema.py -q`
Expected: FAIL (energy tables missing).

- [ ] **Step 3: Write the migration**

`services/api/migrations/versions/0012_energy_domain.py`:
```python
"""Energy domain: drop supply-chain tables, create GridLens tables with forced row-level security.

Revision ID: 0012_energy_domain
Revises: 0011
"""
from alembic import op

revision = "0012_energy_domain"
down_revision = "0011"     # set to the exact revision id string of 0011_erp_connector_and_operations.py
branch_labels = None
depends_on = None

SUPPLY = ["receipts", "purchase_order_lines", "import_rows", "import_batches", "erp_connector_state",
          "clause_labels", "public_awards", "warehouse_slots", "agent_events", "agent_runs", "approvals", "outbox",
          "actions", "plan_runs", "forecast_points", "forecast_runs", "supplier_terms", "inventory_positions",
          "suppliers", "assumption_sets", "sales_daily", "return_lines", "sales_lines", "products", "locations"]
ENERGY_DDL = """
CREATE TABLE sites (
  tenant_id uuid NOT NULL REFERENCES tenants(id), id text NOT NULL, name text NOT NULL,
  currency text NOT NULL, timezone text NOT NULL, config jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, id));
CREATE TABLE park_tenants (
  tenant_id uuid NOT NULL REFERENCES tenants(id), site_id text NOT NULL, id text NOT NULL, name text NOT NULL,
  share double precision NOT NULL CHECK (share > 0 AND share <= 1),
  priority text NOT NULL CHECK (priority IN ('critical','essential','flexible')),
  flexible_share double precision NOT NULL CHECK (flexible_share >= 0 AND flexible_share <= 1),
  PRIMARY KEY (tenant_id, site_id, id), FOREIGN KEY (tenant_id, site_id) REFERENCES sites(tenant_id, id));
CREATE TABLE replays (
  tenant_id uuid NOT NULL REFERENCES tenants(id), id uuid PRIMARY KEY, site_id text NOT NULL, day date NOT NULL,
  controller text NOT NULL, forecaster text NOT NULL, scenario jsonb NOT NULL, uc boolean NOT NULL DEFAULT false,
  parent_id uuid REFERENCES replays(id), fork_step int, status text NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued','running','done','failed')),
  error text, kpis jsonb, created_by uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz, FOREIGN KEY (tenant_id, site_id) REFERENCES sites(tenant_id, id));
CREATE TABLE replay_steps (
  tenant_id uuid NOT NULL REFERENCES tenants(id), replay_id uuid NOT NULL REFERENCES replays(id) ON DELETE CASCADE,
  k int NOT NULL CHECK (k >= 0 AND k < 96), record jsonb NOT NULL, explanation jsonb NOT NULL,
  PRIMARY KEY (replay_id, k));
CREATE TABLE replay_events (
  tenant_id uuid NOT NULL REFERENCES tenants(id), id bigserial PRIMARY KEY,
  replay_id uuid NOT NULL REFERENCES replays(id) ON DELETE CASCADE, event jsonb NOT NULL, child_id uuid,
  created_by uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE shed_events (
  tenant_id uuid NOT NULL REFERENCES tenants(id), id bigserial PRIMARY KEY,
  replay_id uuid NOT NULL REFERENCES replays(id) ON DELETE CASCADE, k int NOT NULL, ts timestamptz NOT NULL,
  park_tenant_id text NOT NULL, kw double precision NOT NULL, trigger text NOT NULL, rule text NOT NULL);
CREATE INDEX shed_events_by_tenant ON shed_events (tenant_id, park_tenant_id, ts);
CREATE TABLE dispatch_requests (
  tenant_id uuid NOT NULL REFERENCES tenants(id), id uuid PRIMARY KEY, site_id text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('battery_override','demand_response_shed')), payload jsonb NOT NULL,
  payload_hash text NOT NULL, reason text NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','expired','delivered',
    'unknown_outcome','failed')),
  requested_by uuid NOT NULL, decided_by uuid, decided_at timestamptz, expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), CHECK (decided_by IS NULL OR decided_by <> requested_by));
CREATE TABLE plant_commands (
  tenant_id uuid NOT NULL REFERENCES tenants(id), id uuid PRIMARY KEY,
  request_id uuid NOT NULL REFERENCES dispatch_requests(id), body jsonb NOT NULL, signature text NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','confirmed','unknown_outcome','failed')),
  attempts int NOT NULL DEFAULT 0, last_error text, created_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz, confirmed_at timestamptz);
CREATE SCHEMA IF NOT EXISTS sandbox_plant;
CREATE TABLE sandbox_plant.commands (id uuid PRIMARY KEY, tenant_id uuid NOT NULL, body jsonb NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE sandbox_plant.fault_injection (id int PRIMARY KEY DEFAULT 1, mode text NOT NULL DEFAULT 'none'
  CHECK (mode IN ('none','timeout_after_write','reject','down')));
INSERT INTO sandbox_plant.fault_injection (id, mode) VALUES (1, 'none');
"""
TENANT_TABLES = ["sites", "park_tenants", "replays", "replay_steps", "replay_events", "shed_events",
                 "dispatch_requests", "plant_commands"]


def upgrade() -> None:
    for t in SUPPLY:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.execute("DROP SCHEMA IF EXISTS sandbox_erp CASCADE")
    op.execute(ENERGY_DDL)
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} "
                   f"USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
                   f"WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
    op.execute("GRANT USAGE ON SCHEMA public, sandbox_plant TO gridlens_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO gridlens_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA sandbox_plant TO gridlens_app")
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO gridlens_app")
    op.execute("REVOKE UPDATE, DELETE ON audit_events FROM gridlens_app")   # audit stays append-only


def downgrade() -> None:
    raise RuntimeError("0012 drops the supply-chain domain; restore from tag archive/supplylens instead")
```
Before writing: open `0011_erp_connector_and_operations.py` and copy its `revision` string into `down_revision`; open `0001_core_schema.py` and confirm how the tenants table is named (`tenants`) and whether `audit_events` is already append-only (if it is, keep the REVOKE line anyway — it is idempotent).

- [ ] **Step 4: Update the test fixtures**

In `tests/conftest.py` replace `TENANT_TABLES_CLEAR_ORDER` with
```python
TENANT_TABLES_CLEAR_ORDER = [
    "plant_commands", "dispatch_requests", "shed_events", "replay_events", "replay_steps", "replays",
    "park_tenants", "sites", "web_vitals", "tenant_exports", "alerts", "rate_limit_buckets", "tenant_settings",
    "audit_events", "idempotency_keys", "jobs", "model_versions", "chunk_vectors", "chunks",
    "document_versions", "documents", "quarantine", "datasets",
]
```
and in `clean_db` replace the `sandbox_erp` truncation and update with
```python
        conn.execute(text(f"TRUNCATE {tables}, sandbox_plant.commands, worker_heartbeats"))
        conn.execute(text("UPDATE sandbox_plant.fault_injection SET mode = 'none'"))
```

- [ ] **Step 5: Migrate and run**

```bash
GRIDLENS_MIGRATION_URL=postgresql+psycopg://gridlens_owner:gridlens_owner_dev@localhost:5432/gridlens_test \
  uv run alembic -c services/api/alembic.ini upgrade head
uv run pytest tests/test_energy_schema.py -q
```
Expected: `2 passed`. The rest of `tests/` will now fail where it touches dropped tables — Task 2 removes that code and those tests; do not commit until Task 2 is green.

---

### Task 2: Remove the supply-chain core (code and tests)

**Files:**
- Delete: `services/api/src/gridlens/{planning,simulation,onboarding,integrations,actions,agent}/`, `services/api/src/gridlens/ingest/uci.py`, `services/api/src/gridlens/api/routes_onboarding.py`, `services/api/src/gridlens/bootstrap.py` (UCI retail), `ml/gridlens_ml/{uci,panel,series,models,tcn}.py` only after Plan 5 Task 2 has moved the TCN/LSTM code (until then keep `tcn.py`), `optimisation/gridlens_opt/{planner,validator,replenishment,leadtime_demand,terms,demand_sim}.py`, `data/synthetic/operations/`, `fixtures/`
- Modify: `routes_core.py` (keep auth, `/me`, `/datasets`, `/audit`; delete `/overview`, `/inventory*`, `/products/*`, `/warehouse`, `/integrations`), `routes_decisions.py` (keep documents/evidence endpoints for the policy library; delete forecasts, terms, scenarios, agent-runs, actions, open-orders, sandbox), `routes_ops.py` (delete reconciliation/connector/clause and the `INVENTORY_SQL` import; keep health, members, jobs, models monitoring, audit CSV), `app.py`, `schemas.py`, `jobs.py`, `alerts.py`, `operations.py`, `seed.py`, `demo.py`, `lifecycle.py`, worker `main.py`
- Delete tests: every `tests/test_*.py` whose subject is deleted (`test_actions`, `test_agent_graph`, `test_phase6_erp`, `test_planner_fixture`, `test_inventory_classes`, `test_leadtime_demand`, `test_onboarding`, `test_uci_ingest`, `test_seasonal_naive`, `test_forecast_service`, `test_forecast_metrics`, `test_phase5_ml`, `test_golden_boundaries`, `test_emissions_tradeoff`, `test_fair_allocation` if it imports the planner, `rehearsal_workload.py`, `test_rehearsals.py`); edit mixed files (`test_api.py`, `test_security_matrix.py`, `test_phase*`, `test_reliability.py`, `test_lifecycle.py`, `test_alerts.py`, `test_contract_responses.py`) by deleting cases about removed endpoints.

- [ ] **Step 1: Delete the packages and modules**

```bash
cd services/api/src/gridlens
git rm -q -r planning simulation onboarding integrations actions agent ingest/uci.py api/routes_onboarding.py bootstrap.py
cd -
cd optimisation/gridlens_opt && git rm -q planner.py validator.py replenishment.py leadtime_demand.py terms.py demand_sim.py && cd -
git rm -q -r data/synthetic/operations fixtures
```

- [ ] **Step 2: Find every dangling reference**

```bash
uv run ruff check . --select F401,F811,F821 2>&1 | head -60
uv run python -c "import gridlens.api.app" 2>&1 | tail -5
uv run python -c "import gridlens_worker.main" 2>&1 | tail -5
```
For each error, delete the import and every endpoint, function or test that used the removed module. The keep-lists in **Files** above decide what stays. In `seed.py` keep tenants, users and memberships; rename the seeded workspaces to `gwangyang-park` (Korea, observed load) and `abu-dhabi-whatif` (UAE what-if) and `demo` (synthetic). In the worker keep heartbeat, job leasing, alert evaluation and delivery; remove run refresh and ERP sync (Task 6 adds the energy ticks).

- [ ] **Step 3: Delete tests of removed features and run the suite**

```bash
git rm -q tests/test_actions.py tests/test_agent_graph.py tests/test_phase6_erp.py tests/test_planner_fixture.py \
  tests/test_inventory_classes.py tests/test_leadtime_demand.py tests/test_onboarding.py tests/test_uci_ingest.py \
  tests/test_seasonal_naive.py tests/test_forecast_service.py tests/test_forecast_metrics.py tests/test_phase5_ml.py \
  tests/test_golden_boundaries.py tests/test_emissions_tradeoff.py tests/rehearsal_workload.py tests/test_rehearsals.py
uv run pytest -q 2>&1 | tail -15
```
Fix each remaining failure by deleting the test case for a removed endpoint (never by changing what a security or isolation test asserts). Expected end state: 0 failures.

- [ ] **Step 4: Regenerate the contract and commit Tasks 1–2 together**

```bash
./scripts/update_contracts.sh && ./scripts/check_contracts.sh
uv run ruff check . && uv run pytest -q 2>&1 | tail -3 && uv run pytest tests_energy -q
git add -A
git commit -m "Swap the database to the energy domain and remove the supply-chain core

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Energy service layer — parks, controllers and replays

**Files:**
- Create: `services/api/src/gridlens/energy/__init__.py`, `parks.py`, `replay.py`
- Modify: `services/api/src/gridlens/seed.py` (sites and park tenants per workspace)
- Test: `tests/test_energy_replay.py`

**Interfaces:**
- Produces: `parks.park(site_id) -> ParkData` (cached; synthetic `testing.synthetic_series` for site id `demo`); `parks.forecaster(site_id, kind="lgbm") -> Forecaster` (cached LightGBM file if present, else seasonal naive); `parks.CONTROLLERS: dict[str, str]` (name → description); `parks.make_controller(name, site, env, site_id) -> Controller` (raises `KeyError` for unknown or unavailable names; RL names `ppo`, `sac` resolve to the seed with the lowest validation cost in `models/rl/<site>/*.json`); `parks.available_controllers(site_id) -> list[str]`; `replay.create(tenant_id, user_id, site_id, day, controller, scenario: dict, uc: bool, forecaster: str, parent_id=None, fork_step=None) -> UUID`; `replay.run(tenant_id, replay_id) -> dict` (KPIs); `replay.fork(tenant_id, user_id, replay_id, event: dict) -> UUID`.

- [ ] **Step 1: Write the failing tests**

`tests/test_energy_replay.py`:
```python
import uuid

from sqlalchemy import text

from gridlens.db import tenant_session
from gridlens.energy import replay
from gridlens.seed import user_id


def test_replay_runs_a_full_day_and_logs_sheds(clean_db, tenant_b):
    from gridlens.seed import seed
    seed()
    uid = user_id("planner@demo.test")
    rid = replay.create(tenant_b, uid, "demo", "2018-11-02", "rule_tou",
                        {"seed": 0, "regime": "blackout", "events": [
                            {"kind": "blackout", "start": 72, "duration": 16, "magnitude": 0.0}]},
                        uc=False, forecaster="naive")
    kpis = replay.run(tenant_b, rid)
    assert kpis["unserved_kwh"] >= 0
    with tenant_session(tenant_b) as s:
        steps = s.execute(text("select count(*) from replay_steps where replay_id = :r"), {"r": rid}).scalar()
        sheds = s.execute(text("select count(*) from shed_events where replay_id = :r"), {"r": rid}).scalar()
        status = s.execute(text("select status from replays where id = :r"), {"r": rid}).scalar()
    assert steps == 96 and sheds > 0 and status == "done"


def test_fork_reproduces_steps_before_the_event(clean_db, tenant_b):
    from gridlens.seed import seed
    seed()
    uid = user_id("planner@demo.test")
    rid = replay.create(tenant_b, uid, "demo", "2018-11-02", "greedy_self",
                        {"seed": 0, "regime": "normal", "events": []}, uc=False, forecaster="naive")
    replay.run(tenant_b, rid)
    child = replay.fork(tenant_b, uid, rid, {"kind": "blackout", "start": 50, "duration": 8, "magnitude": 0.0})
    replay.run(tenant_b, child)
    with tenant_session(tenant_b) as s:
        a = s.execute(text("select record from replay_steps where replay_id = :r and k < 50 order by k"),
                      {"r": rid}).scalars().all()
        b = s.execute(text("select record from replay_steps where replay_id = :r and k < 50 order by k"),
                      {"r": child}).scalars().all()
        c50 = s.execute(text("select record from replay_steps where replay_id = :r and k = 50"),
                        {"r": child}).scalar()
    assert a == b and c50["grid_available"] is False
    assert isinstance(child, uuid.UUID)
```
(Use the seeded planner e-mail for the `demo` workspace; check `seed.dev_email` for the exact address format and use it.)

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_energy_replay.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'gridlens.energy'`.

- [ ] **Step 3: Write `energy/parks.py`**

```python
"""Parks, forecasters and controllers available to the API (no PyTorch, no LightGBM in this process)."""
from __future__ import annotations

import json
from functools import lru_cache

from gridlens_control.baselines import GreedySelf, NoBattery, RuleTOU
from gridlens_control.mpc import PerfectInfoOracle, StochasticMPC
from gridlens_control.policy import NumpyPolicy, RLController
from gridlens_sim.config import load_site
from gridlens_sim.factory import ParkData, load_park
from gridlens_sim.forecast import CachedForecaster, SeasonalNaiveForecaster
from gridlens_sim.testing import synthetic_series

from ..config import REPO_ROOT

CONTROLLERS = {
    "no_battery": "Reference: battery idle (safety layer only)",
    "rule_tou": "Classical baseline 1: charge in the light band, discharge in the peak band",
    "greedy_self": "Classical baseline 2: greedy solar self-consumption",
    "stochastic_mpc": "Stochastic MPC: scenario linear programme re-planned every 15 minutes",
    "ppo": "Deep RL: PPO policy (best validation seed)",
    "sac": "Deep RL: SAC policy (best validation seed)",
    "oracle": "Bound: perfect information (not deployable)",
}
DEMO_DAYS = 28


@lru_cache(maxsize=4)
def park(site_id: str) -> ParkData:
    if site_id == "demo":
        site = load_site("kr_gwangyang", p_peak_kw=1000.0)
        import pandas as pd
        s = synthetic_series(site, days=DEMO_DAYS, start="2018-10-20")
        return ParkData(site=site, series=s, weather=pd.DataFrame(index=s.index))
    return load_park(site_id)


@lru_cache(maxsize=8)
def forecaster(site_id: str, kind: str = "lgbm"):
    s = park(site_id).series
    naive = SeasonalNaiveForecaster(s)
    cache = REPO_ROOT / "data" / "silver" / "energy" / f"forecasts_{site_id}.npz"
    return CachedForecaster(cache, naive) if kind == "lgbm" and cache.exists() else naive


def _best_policy(site_id: str, algo: str) -> tuple[NumpyPolicy, str] | None:
    metas = [json.loads(p.read_text()) | {"_path": p}
             for p in (REPO_ROOT / "models" / "rl" / site_id).glob(f"{algo}_seed*.json")]
    if not metas:
        return None
    best = min(metas, key=lambda m: m["val_total_cost"])
    return NumpyPolicy.load(best["_path"].with_suffix(".npz"), expected_sha256=best["sha256"]), f"{algo}_s{best['seed']}"


def available_controllers(site_id: str) -> list[str]:
    rl_site = "kr_gwangyang" if site_id == "demo" else site_id
    return [c for c in CONTROLLERS if c not in ("ppo", "sac") or _best_policy(rl_site, c) is not None]


def make_controller(name: str, site, env, site_id: str):
    """site_id is the workspace's site key; the synthetic `demo` site reuses the Korea-trained RL policies."""
    if name == "no_battery":
        return NoBattery()
    if name == "rule_tou":
        return RuleTOU(site)
    if name == "greedy_self":
        return GreedySelf(site)
    if name == "stochastic_mpc":
        return StochasticMPC(site, scenarios=5, horizon=48)
    if name == "oracle":
        return PerfectInfoOracle(site, env, horizon=48)
    if name in ("ppo", "sac"):
        found = _best_policy("kr_gwangyang" if site_id == "demo" else site_id, name)
        if found is None:
            raise KeyError(f"no trained {name} policy for {site.id}")
        return RLController(found[0], site, found[1])
    raise KeyError(name)
```

- [ ] **Step 4: Write `energy/replay.py`**

```python
"""Replays: one simulated day under one controller, stored step by step with explanations and shed reasons.

The simulator is deterministic (seeded scenario, seeded MPC sampling), so a stress-test event forks a new replay
whose steps before the event equal the parent's."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict

import pandas as pd
from sqlalchemy import text

from gridlens_control.commitment import uc_commitment_fn
from gridlens_control.explain import explain_step
from gridlens_control.runner import EpisodeResult, run_episode
from gridlens_sim.disruptions import Event, Scenario
from gridlens_sim.env import MicrogridEnv
from gridlens_sim.tenants import DEFAULT_TENANTS

from ..db import tenant_session
from . import parks

TRIGGERS = {True: "UFLS (automatic, frequency)", False: "supply shortfall (safety layer)"}


def create(tenant_id, user_id, site_id: str, day: str, controller: str, scenario: dict, *, uc: bool,
           forecaster: str, parent_id=None, fork_step=None) -> uuid.UUID:
    if controller not in parks.available_controllers(site_id):
        raise KeyError(f"controller {controller} is not available for {site_id}")
    Scenario.from_dict(scenario)                       # validates the shape
    rid = uuid.uuid4()
    with tenant_session(tenant_id) as s:
        s.execute(text(
            "insert into replays (tenant_id, id, site_id, day, controller, forecaster, scenario, uc, parent_id, "
            "fork_step, created_by) values (:t, :id, :site, :day, :c, :f, cast(:sc as jsonb), :uc, :p, :fs, :u)"),
            {"t": tenant_id, "id": rid, "site": site_id, "day": day, "c": controller, "f": forecaster,
             "sc": json.dumps(scenario), "uc": uc, "p": parent_id, "fs": fork_step, "u": user_id})
    return rid


def run(tenant_id, replay_id) -> dict:
    with tenant_session(tenant_id) as s:
        r = s.execute(text("select * from replays where id = :id"), {"id": replay_id}).mappings().one()
        s.execute(text("update replays set status = 'running' where id = :id"), {"id": replay_id})
    try:
        data = parks.park(r["site_id"])
        site, series = data.site, data.series
        fc = parks.forecaster(r["site_id"], r["forecaster"])
        env = MicrogridEnv(site, series, fc)
        scenario = Scenario.from_dict(r["scenario"])
        ds = series.position(pd.Timestamp(str(r["day"]), tz=series.index.tz))
        controller = parks.make_controller(r["controller"], site, env, r["site_id"])
        commitment = uc_commitment_fn(site, fc, series)(ds, scenario) if r["uc"] else None
        result: EpisodeResult = run_episode(env, controller, ds, scenario, commitment=commitment)
        kpis = result.kpis()
        _store(tenant_id, replay_id, site, result)
        with tenant_session(tenant_id) as s:
            s.execute(text("update replays set status = 'done', kpis = cast(:k as jsonb), finished_at = now() "
                           "where id = :id"), {"k": json.dumps(kpis), "id": replay_id})
        return kpis
    except Exception as exc:
        with tenant_session(tenant_id) as s:
            s.execute(text("update replays set status = 'failed', error = :e, finished_at = now() where id = :id"),
                      {"e": f"{type(exc).__name__}: {exc}"[:500], "id": replay_id})
        raise


def _store(tenant_id, replay_id, site, result: EpisodeResult) -> None:
    with tenant_session(tenant_id) as s:
        for rec in result.records:
            s.execute(text("insert into replay_steps (tenant_id, replay_id, k, record, explanation) values "
                           "(:t, :r, :k, cast(:rec as jsonb), cast(:ex as jsonb))"),
                      {"t": tenant_id, "r": replay_id, "k": rec.k, "rec": json.dumps(asdict(rec)),
                       "ex": json.dumps(explain_step(rec, site))})
            for tenant, kw in zip(DEFAULT_TENANTS, rec.shed_by_tenant, strict=True):
                if kw > 1e-6:
                    s.execute(text(
                        "insert into shed_events (tenant_id, replay_id, k, ts, park_tenant_id, kw, trigger, rule) "
                        "values (:t, :r, :k, :ts, :pt, :kw, :tr, :rule)"),
                        {"t": tenant_id, "r": replay_id, "k": rec.k, "ts": rec.timestamp, "pt": tenant.id, "kw": kw,
                         "tr": TRIGGERS[bool(rec.stages_tripped)],
                         "rule": f"priority {tenant.priority}; order flexible > essential > critical, "
                                 f"rotating within class"})


def fork(tenant_id, user_id, replay_id, event: dict) -> uuid.UUID:
    Event(**event)                                     # validates the event
    with tenant_session(tenant_id) as s:
        r = s.execute(text("select * from replays where id = :id"), {"id": replay_id}).mappings().one()
    scenario = dict(r["scenario"])
    scenario["events"] = [*scenario["events"], event]
    scenario["regime"] = "stress_test"
    child = create(tenant_id, user_id, r["site_id"], str(r["day"]), r["controller"], scenario, uc=r["uc"],
                   forecaster=r["forecaster"], parent_id=replay_id, fork_step=int(event["start"]))
    with tenant_session(tenant_id) as s:
        s.execute(text("insert into replay_events (tenant_id, replay_id, event, child_id, created_by) values "
                       "(:t, :r, cast(:e as jsonb), :c, :u)"),
                  {"t": tenant_id, "r": replay_id, "e": json.dumps(event), "c": child, "u": user_id})
    return child
```
`Scenario.from_dict` accepts `regime` values outside `REGIMES` (it does not validate the regime), so `"stress_test"` is allowed for forks.

- [ ] **Step 5: Seed sites and park tenants**

In `seed.py`, after workspaces are created, insert one `sites` row per workspace (`gwangyang-park` → `kr_gwangyang`, `abu-dhabi-whatif` → `ae_industrial`, `demo` → `demo`) with `config` = the site YAML as JSON, and five `park_tenants` rows from `DEFAULT_TENANTS`. Use `ON CONFLICT DO NOTHING` so seeding stays idempotent.

- [ ] **Step 6: Run tests and commit**

```bash
uv run pytest tests/test_energy_replay.py -q && uv run ruff check --fix services
git add services tests/test_energy_replay.py
git commit -m "Add energy service layer: parks, controllers and deterministic replays with forks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: What-if sizing, tenant bills, daily report and energy alerts

**Files:**
- Create: `services/api/src/gridlens/energy/whatif.py`, `bills.py`, `report.py`, `alerts.py`
- Test: `tests/test_energy_features.py`

**Interfaces:**
- Produces: `whatif.compare(site_id, day, controller, scenario: dict, battery_hours: float, pv_ratio: float) -> dict` (`{"base": kpis, "variant": kpis, "delta": {...}}`); `bills.allocate(records: list[dict], tenants, site) -> list[dict]` (per tenant: energy cost share, demand-charge share by coincident-peak share, DR credit to tenants that deferred, shed compensation at `site.voll_per_kwh × 0.1` per kWh shed, net bill); `report.daily_markdown(replay_row, steps, kpis, bills) -> str`; `alerts.evaluate_replay(tenant_id, replay_id) -> list[str]` raising existing-system alerts of kinds `islanding`, `ufls_trip`, `dr_shortfall`, `low_soc_before_peak`, `low_power_factor`.

- [ ] **Step 1: Write the failing tests**

`tests/test_energy_features.py`:
```python
import pytest

from gridlens.energy import bills, report, whatif
from gridlens_sim.tenants import DEFAULT_TENANTS


def test_bigger_battery_cuts_cost_on_a_normal_day():
    out = whatif.compare("demo", "2018-11-02", "rule_tou", {"seed": 0, "regime": "normal", "events": []},
                         battery_hours=4.0, pv_ratio=0.8)
    assert out["variant"]["operating_cost"] < out["base"]["operating_cost"]
    assert out["delta"]["operating_cost"] == pytest.approx(
        out["variant"]["operating_cost"] - out["base"]["operating_cost"])


def test_bills_sum_to_the_park_energy_cost():
    records = [{"energy_cost": 100.0, "demand_cost": 10.0, "dr_cost": -20.0, "grid_import_kw": 400.0,
                "tenant_demand_kw": [140, 100, 60, 60, 40], "shed_by_tenant": [0, 0, 0, 10, 0],
                "deferred_kwh": 5.0}]
    from gridlens_sim.config import load_site
    site = load_site("kr_gwangyang", 1000.0)
    out = bills.allocate(records, DEFAULT_TENANTS, site)
    assert sum(b["energy"] + b["demand"] for b in out) == pytest.approx(110.0)
    assert sum(b["dr_credit"] for b in out) == pytest.approx(20.0)
    assert next(b for b in out if b["tenant"] == "T4")["shed_compensation"] > 0


def test_report_mentions_controller_and_provenance():
    md = report.daily_markdown({"site_id": "demo", "day": "2018-11-02", "controller": "rule_tou",
                                "scenario": {"regime": "normal", "events": []}},
                               [], {"operating_cost": 1.0, "co2_kg": 2.0}, [])
    assert "rule_tou" in md and "simulated" in md.lower()
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_energy_features.py -q`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `energy/whatif.py`**

```python
"""Digital-twin what-if: the same day, scenario and controller with a different battery or PV size."""
from __future__ import annotations

import dataclasses

import pandas as pd

from gridlens_control.runner import run_episode
from gridlens_sim.disruptions import Scenario
from gridlens_sim.env import MicrogridEnv
from gridlens_sim.series import build_series
from gridlens_sim.tenants import DEFAULT_TENANTS

from . import parks


def _variant_site(site, battery_hours: float, pv_ratio: float):
    b = dataclasses.replace(site.battery, energy_kwh=site.battery.power_kw * battery_hours)
    pv = dataclasses.replace(site.pv, kwp=site.p_peak_kw * pv_ratio)
    return dataclasses.replace(site, battery=b, pv=pv)


def compare(site_id: str, day: str, controller: str, scenario: dict, battery_hours: float, pv_ratio: float) -> dict:
    data = parks.park(site_id)
    site, s = data.site, data.series
    sc = Scenario.from_dict(scenario)
    ds = s.position(pd.Timestamp(day, tz=s.index.tz))
    fc = parks.forecaster(site_id)
    base_env = MicrogridEnv(site, s, fc)
    base = run_episode(base_env, parks.make_controller(controller, site, base_env, site_id), ds, sc).kpis()
    vsite = _variant_site(site, battery_hours, pv_ratio)
    scale = vsite.pv.kwp / site.pv.kwp if site.pv.kwp > 0 else 0.0
    vseries = build_series(s.index, s.load_kw, s.pv_kw * scale, vsite, DEFAULT_TENANTS,
                           reactive_kvar=s.reactive_kvar)
    venv = MicrogridEnv(vsite, vseries, fc)
    variant = run_episode(venv, parks.make_controller(controller, vsite, venv, site_id), ds, sc).kpis()
    return {"base": base, "variant": variant, "delta": {k: variant[k] - base[k] for k in base},
            "assumptions": {"battery_hours": battery_hours, "pv_ratio": pv_ratio,
                            "note": "forecasts are the base site's; PV scaled linearly (simulated)"}}
```

- [ ] **Step 4: Write `energy/bills.py`**

```python
"""Allocate a day's park energy bill to tenant factories (spec §9.2 transparency).

Energy cost by each tenant's share of served energy; demand charge by share of load at the park's import peak;
demand-response credits to tenants that postponed flexible load, by their flexible share; compensation for shed energy
at 10 % of the value of lost load (assumed policy, published on the Policies screen).
"""
from __future__ import annotations

import numpy as np

SHED_COMPENSATION_SHARE = 0.10


def allocate(records: list[dict], tenants, site) -> list[dict]:
    n = len(tenants)
    served = np.zeros(n)
    shed = np.zeros(n)
    energy = demand = dr_credit = 0.0
    peak_k = int(np.argmax([r["grid_import_kw"] for r in records])) if records else 0
    for r in records:
        dem = np.asarray(r["tenant_demand_kw"], dtype=float)
        sh = np.asarray(r["shed_by_tenant"], dtype=float)
        served += (dem - sh) * 0.25
        shed += sh * 0.25
        energy += r["energy_cost"]
        demand += r["demand_cost"]
        dr_credit += -r["dr_cost"] if r["dr_cost"] < 0 else 0.0
    peak = np.asarray(records[peak_k]["tenant_demand_kw"], dtype=float) if records else np.ones(n)
    flex = np.array([t.share * t.flexible_share for t in tenants])
    e_share = served / served.sum() if served.sum() > 0 else np.full(n, 1 / n)
    p_share = peak / peak.sum() if peak.sum() > 0 else np.full(n, 1 / n)
    f_share = flex / flex.sum() if flex.sum() > 0 else np.zeros(n)
    out = []
    for i, t in enumerate(tenants):
        comp = shed[i] * site.voll_per_kwh * SHED_COMPENSATION_SHARE
        row = {"tenant": t.id, "name": t.name, "priority": t.priority, "served_kwh": float(served[i]),
               "shed_kwh": float(shed[i]), "energy": float(energy * e_share[i]), "demand": float(demand * p_share[i]),
               "dr_credit": float(dr_credit * f_share[i]), "shed_compensation": float(comp)}
        row["net"] = row["energy"] + row["demand"] - row["dr_credit"] - row["shed_compensation"]
        out.append(row)
    return out
```

- [ ] **Step 5: Write `energy/report.py`**

```python
"""Printable daily EMS report (Markdown; the web app renders it and the browser prints it to PDF)."""
from __future__ import annotations


def daily_markdown(replay: dict, steps: list[dict], kpis: dict, bills: list[dict]) -> str:
    lines = [f"# GridLens daily report — {replay['site_id']} — {replay['day']}", "",
             f"Controller: **{replay['controller']}** · Scenario: **{replay['scenario']['regime']}** "
             f"({len(replay['scenario']['events'])} events)", "",
             "All figures are simulated on observed load and weather; asset sizes, tariffs marked assumed and "
             "tenant splits are assumptions. This is not a bill.", "", "## Key figures", "",
             "| Measure | Value |", "|---|---|"]
    lines += [f"| {k.replace('_', ' ')} | {v:,.2f} |" for k, v in kpis.items() if isinstance(v, (int, float))]
    events = [s for s in steps if s["explanation"] and not s["record"]["grid_available"]
              or s["record"]["stages_tripped"] or s["record"]["shed_kw"] > 0]
    if events:
        lines += ["", "## Events", ""]
        lines += [f"- {s['record']['timestamp'][11:16]} — " + " ".join(s["explanation"]) for s in events[:40]]
    if bills:
        lines += ["", "## Tenant allocation", "", "| Tenant | Priority | Served kWh | Shed kWh | Net |",
                  "|---|---|---|---|---|"]
        lines += [f"| {b['name']} | {b['priority']} | {b['served_kwh']:,.0f} | {b['shed_kwh']:,.1f} | "
                  f"{b['net']:,.2f} |" for b in bills]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 6: Write `energy/alerts.py`**

```python
"""Energy alerts on a finished replay, raised through the existing alert queue (signed webhook delivery)."""
from __future__ import annotations

from sqlalchemy import text

from .. import alerts
from ..db import tenant_session


def evaluate_replay(tenant_id, replay_id) -> list[str]:
    with tenant_session(tenant_id) as s:
        steps = s.execute(text("select k, record from replay_steps where replay_id = :r order by k"),
                          {"r": replay_id}).all()
    raised = []
    recs = [r for _, r in steps]

    def raise_(kind, title, detail):
        alerts.raise_alert(tenant_id, kind, f"{kind}:{replay_id}", title, detail)
        raised.append(kind)

    if any(not r["grid_available"] for r in recs):
        raise_("islanding", "Park islanded", {"replay_id": str(replay_id)})
    if any(r["stages_tripped"] for r in recs):
        raise_("ufls_trip", "Under-frequency load shedding tripped", {"replay_id": str(replay_id)})
    if any(r["dr_shortfall_kw"] > 1e-6 for r in recs):
        raise_("dr_shortfall", "Demand-response commitment missed", {"replay_id": str(replay_id)})
    if any(r["band"] == "peak" and r["soc"] < 0.2 for r in recs):
        raise_("low_soc_before_peak", "Battery below 20 % in a peak band", {"replay_id": str(replay_id)})
    if any(r["grid_import_kw"] > 0 and r["power_factor"] < 0.9 - 1e-9 for r in recs):
        raise_("low_power_factor", "Power factor below 0.90", {"replay_id": str(replay_id)})
    return raised
```
Add the five kinds to `KINDS` in `gridlens/alerts.py`.

- [ ] **Step 7: Run tests and commit**

```bash
uv run pytest tests/test_energy_features.py -q && uv run ruff check --fix services
git add services tests/test_energy_features.py
git commit -m "Add what-if sizing, tenant bill allocation, daily report and energy alerts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Energy API

**Files:**
- Create: `services/api/src/gridlens/api/routes_energy.py`
- Modify: `services/api/src/gridlens/api/app.py`, `schemas.py`, `authz.py`
- Test: `tests/test_energy_api.py`

**Interfaces (all under `/api/v1/energy`):**

| Method and path | Operation | Returns |
|---|---|---|
| `GET /sites` | read | sites of the workspace with tariff, assets, provenance notes |
| `GET /sites/{site}/series?day=` | read | 96 rows: load, PV, price, band, reactive, flex (observed/simulated labels) |
| `GET /sites/{site}/forecast?day=&step=` | read | quantile fan for load and PV issued at that step |
| `GET /sites/{site}/commitment?day=&alert=` | read | unit commitment (on/off per unit, starts, status) |
| `GET /controllers?site=` | read | available controllers with descriptions |
| `POST /replays` | replay.run | created replay (computed inline when no worker is configured) |
| `GET /replays?site=` | read | recent replays with KPIs |
| `GET /replays/{id}` | read | replay, KPIs and all 96 steps with explanations |
| `POST /replays/{id}/events` | replay.run | child replay id and fork step |
| `GET /replays/{id}/report.md` | read | Markdown report |
| `GET /replays/{id}/bills` | read | tenant allocation |
| `GET /tenants?site=` | read | park tenants, priority policy text |
| `GET /shed-log?site=&tenant=` | read | shed events with trigger and rule |
| `POST /whatif` | replay.run | base vs variant KPIs |
| `GET /benchmarks` | read | studies GF1, UC1, MB1, MB2, FS1, CY1, DR1 from the registry (same mechanism as research) |

- [ ] **Step 1: Write the failing tests**

`tests/test_energy_api.py`:
```python
def test_replay_round_trip_and_fork(client_planner):
    c = client_planner
    r = c.post("/api/v1/energy/replays", json={"site": "demo", "day": "2018-11-02", "controller": "rule_tou",
                                               "scenario": {"seed": 0, "regime": "normal", "events": []}})
    assert r.status_code == 201
    rid = r.json()["id"]
    d = c.get(f"/api/v1/energy/replays/{rid}").json()
    assert d["status"] == "done" and len(d["steps"]) == 96 and d["steps"][0]["explanation"]
    f = c.post(f"/api/v1/energy/replays/{rid}/events",
               json={"kind": "blackout", "start": 60, "duration": 8, "magnitude": 0.0})
    assert f.status_code == 201 and f.json()["fork_step"] == 60
    child = c.get(f"/api/v1/energy/replays/{f.json()['id']}").json()
    assert child["steps"][60]["record"]["grid_available"] is False


def test_viewer_cannot_start_replays(client_viewer):
    r = client_viewer.post("/api/v1/energy/replays", json={"site": "demo", "day": "2018-11-02",
                                                           "controller": "rule_tou",
                                                           "scenario": {"seed": 0, "regime": "normal", "events": []}})
    assert r.status_code == 403


def test_unknown_controller_is_a_422(client_planner):
    r = client_planner.post("/api/v1/energy/replays", json={"site": "demo", "day": "2018-11-02",
                                                            "controller": "magic",
                                                            "scenario": {"seed": 0, "regime": "normal", "events": []}})
    assert r.status_code == 422


def test_other_workspace_replays_are_invisible(client_planner, client_other_workspace):
    rid = client_planner.post("/api/v1/energy/replays", json={
        "site": "demo", "day": "2018-11-02", "controller": "no_battery",
        "scenario": {"seed": 0, "regime": "normal", "events": []}}).json()["id"]
    assert client_other_workspace.get(f"/api/v1/energy/replays/{rid}").status_code == 404
```
Build the fixtures `client_planner`, `client_viewer`, `client_other_workspace` in `tests/conftest.py` from the existing sign-in helpers (look at how `tests/test_api.py` signs in a role and sets the workspace header; the header name is now `X-GridLens-Tenant`).

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_energy_api.py -q`
Expected: FAIL (404 on `/api/v1/energy/replays`).

- [ ] **Step 3: Add schemas and operations**

In `authz.py` add `"replay.run", "request.prepare"` to `planner`, `"request.approve", "request.reject"` to `approver`, and `"replay.run"` to `tenant_admin`. In `schemas.py` add:
```python
class ScenarioEventIn(BaseModel):
    kind: Literal["blackout", "cloud_drop", "machine_start", "dr_event"]
    start: int = Field(ge=0, lt=96)
    duration: int = Field(ge=1, le=96)
    magnitude: float = Field(ge=0)


class ScenarioIn(BaseModel):
    seed: int = 0
    regime: str = "normal"
    events: list[ScenarioEventIn] = []


class ReplayIn(BaseModel):
    site: str
    day: date
    controller: str
    scenario: ScenarioIn
    uc: bool = False
    forecaster: Literal["lgbm", "naive"] = "lgbm"


class ReplayCreated(BaseModel):
    id: UUID
    status: str
    fork_step: int | None = None


class ReplayStep(BaseModel):
    k: int
    record: dict
    explanation: list[str]


class Replay(BaseModel):
    id: UUID
    site_id: str
    day: date
    controller: str
    forecaster: str
    scenario: dict
    uc: bool
    status: str
    error: str | None
    kpis: dict | None
    parent_id: UUID | None
    fork_step: int | None
    steps: list[ReplayStep]
    provenance: dict


class WhatIfIn(BaseModel):
    site: str
    day: date
    controller: str
    scenario: ScenarioIn
    battery_hours: float = Field(gt=0, le=8)
    pv_ratio: float = Field(ge=0, le=3)
```
plus response models for sites, series, forecast, commitment, controllers, tenants, shed log, bills and what-if, each a `BaseModel` mirroring the dictionaries the service functions return (one field per key).

- [ ] **Step 4: Write `routes_energy.py`**

```python
"""GridLens energy API (spec §8.1)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import text

from ..authz import Actor
from ..db import tenant_session
from ..energy import bills, parks, replay, report, whatif
from .deps import actor, csrf_guard, current_user_id
from .schemas import ReplayCreated, ReplayIn, ScenarioEventIn, WhatIfIn

router = APIRouter(prefix="/api/v1/energy", dependencies=[Depends(csrf_guard)])
PROVENANCE = {"load": "observed (UCI steel 851)", "weather": "observed (Open-Meteo)",
              "pv": "simulated (pvlib)", "tenants": "simulated split", "assets": "assumed sizes",
              "tariff": "observed or marked assumed per value", "results": "simulated"}


def _site_of(a: Actor, site: str) -> None:
    with tenant_session(a.tenant_id) as s:
        if not s.execute(text("select 1 from sites where id = :i"), {"i": site}).first():
            raise HTTPException(404, "unknown site for this workspace")


@router.get("/controllers")
def controllers(site: str, a: Actor = Depends(actor)):
    a.require("read")
    _site_of(a, site)
    return [{"name": n, "description": parks.CONTROLLERS[n]} for n in parks.available_controllers(site)]


@router.post("/replays", response_model=ReplayCreated, status_code=201)
def create_replay(body: ReplayIn, a: Actor = Depends(actor), uid=Depends(current_user_id)):
    a.require("replay.run")
    _site_of(a, body.site)
    try:
        rid = replay.create(a.tenant_id, uid, body.site, body.day.isoformat(), body.controller,
                            body.scenario.model_dump(), uc=body.uc, forecaster=body.forecaster)
    except KeyError as exc:
        raise HTTPException(422, str(exc)) from exc
    replay.run(a.tenant_id, rid)
    return {"id": rid, "status": "done"}


@router.get("/replays/{rid}")
def get_replay(rid: str, a: Actor = Depends(actor)):
    a.require("read")
    with tenant_session(a.tenant_id) as s:
        r = s.execute(text("select * from replays where id = :i"), {"i": rid}).mappings().first()
        if r is None:
            raise HTTPException(404)
        steps = s.execute(text("select k, record, explanation from replay_steps where replay_id = :i order by k"),
                          {"i": rid}).mappings().all()
    return {**dict(r), "steps": [dict(x) for x in steps], "provenance": PROVENANCE}


@router.post("/replays/{rid}/events", response_model=ReplayCreated, status_code=201)
def stress_event(rid: str, body: ScenarioEventIn, a: Actor = Depends(actor), uid=Depends(current_user_id)):
    a.require("replay.run")
    get_replay(rid, a)
    child = replay.fork(a.tenant_id, uid, rid, body.model_dump())
    replay.run(a.tenant_id, child)
    return {"id": child, "status": "done", "fork_step": body.start}


@router.get("/replays/{rid}/bills")
def replay_bills(rid: str, a: Actor = Depends(actor)):
    r = get_replay(rid, a)
    site = parks.park(r["site_id"]).site
    from gridlens_sim.tenants import DEFAULT_TENANTS
    return bills.allocate([s["record"] for s in r["steps"]], DEFAULT_TENANTS, site)


@router.get("/replays/{rid}/report.md", response_class=PlainTextResponse)
def replay_report(rid: str, a: Actor = Depends(actor)):
    r = get_replay(rid, a)
    return report.daily_markdown(r, r["steps"], r["kpis"] or {}, replay_bills(rid, a))


@router.post("/whatif")
def what_if(body: WhatIfIn, a: Actor = Depends(actor)):
    a.require("replay.run")
    _site_of(a, body.site)
    return whatif.compare(body.site, body.day.isoformat(), body.controller, body.scenario.model_dump(),
                          body.battery_hours, body.pv_ratio)
```
Add the remaining read endpoints from the table (`/sites`, `/sites/{site}/series`, `/sites/{site}/forecast`, `/sites/{site}/commitment`, `/replays` list, `/tenants`, `/shed-log`, `/benchmarks`) in the same style: `a.require("read")`, `_site_of`, values from `parks.park(site).series` sliced to the day, `parks.forecaster(site).forecast(step)`, `control.commitment.day_ahead(...)`, SQL selects on `replays`, `park_tenants`, `shed_events`, and for `/benchmarks` reuse `routes_research._latest` and `_review` for each study prefix. Give every route a `response_model` from Step 3. Register the router in `app.py` (`app.include_router(routes_energy.router)`).

- [ ] **Step 5: Run tests, regenerate the contract, commit**

```bash
uv run pytest tests/test_energy_api.py -q && uv run pytest -q 2>&1 | tail -3
./scripts/update_contracts.sh && ./scripts/check_contracts.sh
git add services tests packages/contracts
git commit -m "Add energy API: sites, forecasts, commitment, replays with stress forks, bills, report, what-if

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Approval-bound dispatch requests, signed plant commands and the worker

**Files:**
- Create: `services/api/src/gridlens/energy/requests.py`, `services/api/src/gridlens/energy/plant_adapter.py`, `services/api/src/gridlens/api/routes_requests.py`
- Modify: `services/worker/src/gridlens_worker/main.py`, `services/api/src/gridlens/config.py` (`plant_signing_key`)
- Test: `tests/test_energy_requests.py`

**Interfaces:**
- Produces: `requests.prepare(tenant_id, user_id, site_id, kind, payload, reason, ttl_minutes=60) -> UUID` (payload hash = sha256 of canonical JSON); `requests.decide(tenant_id, user_id, request_id, approve: bool, payload_hash: str)` (refuses the requester, a stale hash, an expired request); on approval inserts one `plant_commands` row with an HMAC-SHA256 signature; `plant_adapter.send(tenant_id, command_id)` (writes to `sandbox_plant.commands`, honours `fault_injection.mode`, marks `confirmed`, `unknown_outcome` or `failed`); `plant_adapter.reconcile(tenant_id, command_id)` (looks the command up in the sandbox, never resends); worker `plant_tick(tenant_id)`.
- Routes: `POST /api/v1/requests` (request.prepare), `GET /api/v1/requests`, `POST /api/v1/requests/{id}/approve` and `/reject` (body `{payload_hash}`), `POST /api/v1/requests/{id}/reconcile` (approver).

- [ ] **Step 1: Write the failing tests**

`tests/test_energy_requests.py`:
```python
import pytest
from sqlalchemy import text

from gridlens.db import admin_engine, tenant_session
from gridlens.energy import plant_adapter, requests
from gridlens.seed import user_id

PAYLOAD = {"tenant": "T4", "start": "2018-11-02T14:00:00+09:00", "minutes": 60, "kw": 100}


def test_requester_cannot_approve_and_hash_must_match(clean_db, tenant_b):
    planner, approver = user_id("planner@demo.test"), user_id("approver@demo.test")
    rid = requests.prepare(tenant_b, planner, "demo", "demand_response_shed", PAYLOAD, "DR event 14:00-15:00")
    with pytest.raises(PermissionError):
        requests.decide(tenant_b, planner, rid, True, requests.payload_hash(PAYLOAD))
    with pytest.raises(ValueError, match="changed"):
        requests.decide(tenant_b, approver, rid, True, "0" * 64)
    requests.decide(tenant_b, approver, rid, True, requests.payload_hash(PAYLOAD))
    with tenant_session(tenant_b) as s:
        cmd = s.execute(text("select id, signature from plant_commands where request_id = :r"), {"r": rid}).one()
    assert plant_adapter.verify(cmd.signature, tenant_b, cmd.id)


def test_timeout_after_write_is_reconciled_not_resent(clean_db, tenant_b):
    planner, approver = user_id("planner@demo.test"), user_id("approver@demo.test")
    rid = requests.prepare(tenant_b, planner, "demo", "battery_override", {"kw": -200, "minutes": 30}, "pre-charge")
    requests.decide(tenant_b, approver, rid, True, requests.payload_hash({"kw": -200, "minutes": 30}))
    with admin_engine().begin() as c:
        c.execute(text("update sandbox_plant.fault_injection set mode = 'timeout_after_write'"))
    with tenant_session(tenant_b) as s:
        cid = s.execute(text("select id from plant_commands where request_id = :r"), {"r": rid}).scalar()
    assert plant_adapter.send(tenant_b, cid) == "unknown_outcome"
    assert plant_adapter.reconcile(tenant_b, cid) == "confirmed"
    with admin_engine().connect() as c:
        assert c.execute(text("select count(*) from sandbox_plant.commands where id = :i"), {"i": cid}).scalar() == 1
```
(Use the seeded e-mails for the `demo` workspace's planner and approver.)

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_energy_requests.py -q`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `energy/requests.py` and `energy/plant_adapter.py`**

```python
"""Approval-bound dispatch requests (spec §9.1-§9.2): non-emergency load shedding and battery overrides need a
second person's approval bound to the exact payload; approval queues one signed plant command (outbox)."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from ..db import tenant_session
from . import plant_adapter


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def prepare(tenant_id, user_id, site_id: str, kind: str, payload: dict, reason: str, ttl_minutes: int = 60):
    rid = uuid.uuid4()
    with tenant_session(tenant_id) as s:
        s.execute(text("insert into dispatch_requests (tenant_id, id, site_id, kind, payload, payload_hash, reason, "
                       "requested_by, expires_at) values (:t, :i, :site, :k, cast(:p as jsonb), :h, :r, :u, :e)"),
                  {"t": tenant_id, "i": rid, "site": site_id, "k": kind, "p": json.dumps(payload),
                   "h": payload_hash(payload), "r": reason, "u": user_id,
                   "e": datetime.now(UTC) + timedelta(minutes=ttl_minutes)})
    return rid


def decide(tenant_id, user_id, request_id, approve: bool, expected_hash: str) -> str:
    with tenant_session(tenant_id) as s:
        r = s.execute(text("select * from dispatch_requests where id = :i for update"),
                      {"i": request_id}).mappings().one()
        if r["requested_by"] == user_id:
            raise PermissionError("the requester cannot decide their own request")
        if r["status"] != "pending":
            raise ValueError(f"request is {r['status']}")
        if r["expires_at"] < datetime.now(UTC):
            s.execute(text("update dispatch_requests set status = 'expired' where id = :i"), {"i": request_id})
            raise ValueError("request expired")
        if r["payload_hash"] != expected_hash:
            raise ValueError("payload changed since it was shown to the approver")
        status = "approved" if approve else "rejected"
        s.execute(text("update dispatch_requests set status = :st, decided_by = :u, decided_at = now() "
                       "where id = :i"), {"st": status, "u": user_id, "i": request_id})
        if approve:
            cid = uuid.uuid4()
            body = {"request_id": str(request_id), "kind": r["kind"], "payload": r["payload"]}
            s.execute(text("insert into plant_commands (tenant_id, id, request_id, body, signature) values "
                           "(:t, :c, :r, cast(:b as jsonb), :sig)"),
                      {"t": tenant_id, "c": cid, "r": request_id, "b": json.dumps(body),
                       "sig": plant_adapter.sign(tenant_id, cid)})
    return status
```

```python
"""Sandbox plant adapter: receives signed commands; a real site controller would sit behind the same contract.
Fault modes: timeout_after_write (the command arrives but the reply is lost), reject, down."""
from __future__ import annotations

import hashlib
import hmac

from sqlalchemy import text

from ..config import settings
from ..db import admin_engine, tenant_session


def sign(tenant_id, command_id) -> str:
    msg = f"{tenant_id}:{command_id}".encode()
    return hmac.new(settings.plant_signing_key.encode(), msg, hashlib.sha256).hexdigest()


def verify(signature: str, tenant_id, command_id) -> bool:
    return hmac.compare_digest(signature, sign(tenant_id, command_id))


def send(tenant_id, command_id) -> str:
    with tenant_session(tenant_id) as s:
        cmd = s.execute(text("select * from plant_commands where id = :i"), {"i": command_id}).mappings().one()
    if not verify(cmd["signature"], tenant_id, command_id):
        status = "failed"
    else:
        with admin_engine().begin() as c:
            mode = c.execute(text("select mode from sandbox_plant.fault_injection where id = 1")).scalar()
            if mode in ("reject", "down"):
                status = "failed"
            else:
                c.execute(text("insert into sandbox_plant.commands (id, tenant_id, body) values (:i, :t, "
                               "cast(:b as jsonb)) on conflict (id) do nothing"),
                          {"i": command_id, "t": tenant_id, "b": __import__("json").dumps(cmd["body"])})
                status = "unknown_outcome" if mode == "timeout_after_write" else "confirmed"
    with tenant_session(tenant_id) as s:
        s.execute(text("update plant_commands set status = :st, attempts = attempts + 1, sent_at = now(), "
                       "confirmed_at = case when :st = 'confirmed' then now() end where id = :i"),
                  {"st": status, "i": command_id})
        s.execute(text("update dispatch_requests set status = :st where id = :r"),
                  {"st": {"confirmed": "delivered"}.get(status, status), "r": cmd["request_id"]})
    return status


def reconcile(tenant_id, command_id) -> str:
    with admin_engine().connect() as c:
        found = c.execute(text("select 1 from sandbox_plant.commands where id = :i"), {"i": command_id}).first()
    status = "confirmed" if found else "failed"
    with tenant_session(tenant_id) as s:
        s.execute(text("update plant_commands set status = :st, confirmed_at = case when :st = 'confirmed' "
                       "then now() end where id = :i"), {"st": status, "i": command_id})
    return status
```
Replace `__import__("json")` with a normal `import json` at the top when you paste it. Add `plant_signing_key: str = "dev-only-plant-key"` to `Settings` in `config.py` and refuse the default in the production/demo profile the same way existing secrets are refused (look for how `config.py` validates other secrets).

- [ ] **Step 4: Routes and worker tick**

`routes_requests.py`: `POST /api/v1/requests` (`a.require("request.prepare")`, body `{site, kind, payload, reason}`, idempotent), `GET /api/v1/requests` (read, newest first, includes `payload_hash` so the approver signs exactly what is shown), `POST /{id}/approve` and `/{id}/reject` (`a.require("request.approve")` / `("request.reject")`, body `{payload_hash}`; map `PermissionError` → 403, `ValueError` → 409), `POST /{id}/reconcile` (`a.require("request.approve")`). Register it in `app.py`.
Worker `main.py`: add
```python
def plant_tick(tenant_id) -> int:
    with tenant_session(tenant_id) as s:
        ids = s.execute(text("select id from plant_commands where status = 'pending' order by created_at limit 20")
                        ).scalars().all()
    for cid in ids:
        plant_adapter.send(tenant_id, cid)
    return len(ids)
```
and call it from `tenant_tick` beside the alert tick.

- [ ] **Step 5: Run tests and commit**

```bash
uv run pytest tests/test_energy_requests.py -q && uv run pytest -q 2>&1 | tail -3
./scripts/update_contracts.sh && ./scripts/check_contracts.sh
git add services tests packages/contracts
git commit -m "Add approval-bound dispatch requests with signed plant commands and reconciliation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Dashboard foundations — replay hook, power flow, SoC gauge, explanation panel

**Files:**
- Create: `apps/web/lib/replay.ts`, `apps/web/components/power-flow.tsx`, `apps/web/components/soc-gauge.tsx`, `apps/web/components/explain-panel.tsx`, `apps/web/components/replay-player.tsx`
- Test: `apps/web/lib/replay.test.ts`

**Interfaces:**
- Produces: `useReplay(id: string | null)` (query of `GET /energy/replays/{id}`); `usePlayer(steps: number, opts?: {speed?: number})` returning `{k, playing, play, pause, seek, speed, setSpeed}` (animates 0…95 at `speed` steps per second); `<PowerFlow record />` (ECharts graph of PV, grid, battery, diesel → park, edge width ∝ kW, labels in kW); `<SocGauge soc band />`; `<ExplainPanel lines />`; `<ReplayPlayer replayId />` composing them with a step slider and play/pause/speed.

- [ ] **Step 1: Write the failing unit test**

`apps/web/lib/replay.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { nextStep } from "./replay";

describe("nextStep", () => {
  it("advances and stops at the last step", () => {
    expect(nextStep(0, 96)).toBe(1);
    expect(nextStep(95, 96)).toBe(95);
  });
});
```

- [ ] **Step 2: Run it to see it fail**

Run: `npm --prefix apps/web test -- replay`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `apps/web/lib/replay.ts`**

```ts
"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "./queries";

export const nextStep = (k: number, steps: number) => Math.min(k + 1, steps - 1);

export function useReplay(id: string | null) {
  return useApi(["replay", id], id ? (`/api/v1/energy/replays/{rid}` as const) : null,
    id ? ({ params: { path: { rid: id } } } as never) : undefined);
}

export function usePlayer(steps: number, opts: { speed?: number; start?: number } = {}) {
  const [k, setK] = useState(opts.start ?? 0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(opts.speed ?? 4);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (!playing) return;
    timer.current = setInterval(() => setK((x) => {
      const n = nextStep(x, steps);
      if (n === x) setPlaying(false);
      return n;
    }), 1000 / speed);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [playing, speed, steps]);
  const seek = useCallback((n: number) => setK(Math.max(0, Math.min(steps - 1, n))), [steps]);
  return { k, playing, play: () => setPlaying(true), pause: () => setPlaying(false), seek, speed, setSpeed };
}
```
Check `useApi`'s argument shape for path parameters in `apps/web/lib/contract.ts` (`Args<P>`) and pass the replay id the way other screens pass path parameters (search for `params:` in `apps/web/app`).

- [ ] **Step 4: Write the components**

`apps/web/components/power-flow.tsx`:
```tsx
"use client";
import { baseOption, Chart, token, useChartTheme } from "./chart";

type Rec = { pv_used_kw: number; grid_import_kw: number; grid_export_kw: number; battery_kw: number;
  diesel_kw: number; load_kw: number; shed_kw: number; grid_available: boolean };

export function PowerFlow({ record }: { record: Rec }) {
  const theme = useChartTheme();
  const kw = (v: number) => `${Math.round(v)} kW`;
  const nodes = [
    { name: "Solar", x: 0, y: 0 }, { name: record.grid_available ? "Grid" : "Grid (down)", x: 0, y: 100 },
    { name: "Battery", x: 0, y: 200 }, { name: "Diesel", x: 0, y: 300 }, { name: "Park", x: 300, y: 150 },
  ];
  const grid = nodes[1].name;
  const links = [
    { source: "Solar", target: "Park", value: record.pv_used_kw },
    { source: grid, target: "Park", value: record.grid_import_kw },
    { source: "Park", target: grid, value: record.grid_export_kw },
    { source: "Battery", target: "Park", value: Math.max(record.battery_kw, 0) },
    { source: "Park", target: "Battery", value: Math.max(-record.battery_kw, 0) },
    { source: "Diesel", target: "Park", value: record.diesel_kw },
  ].filter((l) => l.value > 0.5);
  const option = {
    ...baseOption(theme),
    series: [{
      type: "graph", layout: "none", symbolSize: 56, roam: false, edgeSymbol: ["none", "arrow"],
      label: { show: true, color: token(theme, "ink") },
      data: nodes.map((n) => ({ ...n, value: n.name === "Park" ? record.load_kw - record.shed_kw : undefined })),
      links: links.map((l) => ({ ...l, label: { show: true, formatter: kw(l.value) },
        lineStyle: { width: 1 + Math.min(12, l.value / 60), color: token(theme, "accent") } })),
    }],
  };
  return <Chart option={option} height={300} label={`Power flows: ${links.map((l) => `${l.source} to ${l.target} ${kw(l.value)}`).join(", ")}`} />;
}
```
`apps/web/components/soc-gauge.tsx`:
```tsx
"use client";
import { baseOption, Chart, token, useChartTheme } from "./chart";

export function SocGauge({ soc, band }: { soc: number; band: string }) {
  const theme = useChartTheme();
  const option = {
    ...baseOption(theme),
    series: [{ type: "gauge", min: 0, max: 100, progress: { show: true }, detail: { formatter: "{value}%" },
      data: [{ value: Math.round(soc * 100), name: `${band} band` }],
      axisLine: { lineStyle: { color: [[0.1, token(theme, "danger")], [0.95, token(theme, "accent")], [1, token(theme, "warn")]] } } }],
  };
  return <Chart option={option} height={220} label={`Battery state of charge ${Math.round(soc * 100)} percent, ${band} price band`} />;
}
```
`apps/web/components/explain-panel.tsx`:
```tsx
import { Card, Eyebrow } from "./ui";

export function ExplainPanel({ lines, time }: { lines: string[]; time: string }) {
  return (
    <Card aria-labelledby="why-title">
      <Eyebrow>Why · {time}</Eyebrow>
      <h2 id="why-title" className="sr-only">Why this decision</h2>
      <ul className="mt-2 space-y-1 text-sm">{lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
    </Card>
  );
}
```
`apps/web/components/replay-player.tsx`: a `Card` with the play/pause `Button`, a range input (`aria-label="Replay step"`, 0–95), a speed `select` (1, 4, 16 steps/s), the time label from `steps[k].record.timestamp`, and a 3-column grid of `<SocGauge>`, `<PowerFlow>`, `<ExplainPanel>`; below it four `Stat`s for the step (price, import, CO2 so far, shed so far) with `kind="simulated"`, and an ECharts line chart of load, PV, import and SoC over the day with a vertical marker at `k`. Map token names to the ones `chart-theme.ts` defines (open it; use its existing keys instead of `danger`/`warn`/`accent` if they differ).

- [ ] **Step 5: Run web checks and commit**

```bash
npm --prefix apps/web test && npm --prefix apps/web run typecheck && npm --prefix apps/web run lint
git add apps/web/lib/replay.ts apps/web/lib/replay.test.ts apps/web/components
git commit -m "Add replay player, power-flow graph, SoC gauge and explanation panel

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Screens

**Files:**
- Modify/create: `apps/web/app/(app)/page.tsx` (Overview), `forecast/page.tsx`, `dispatch/page.tsx` (from `runs/`), `stress-test/page.tsx` (from `scenarios/`), `commitment/page.tsx` (new), `tenants/page.tsx` (from `inventory/`), `impact/page.tsx` (from `value/`), `whatif/page.tsx` (new), `research/page.tsx`, `approvals/page.tsx`, `policies/page.tsx`, `layout.tsx`
- Delete: `apps/web/app/(app)/{exceptions,inventory,runs,scenarios,value}/` after moving, and components only they used (`inventory-classes.tsx`, `floorplan.tsx` if unused, `status-assistant.tsx` if replaced)

**Interfaces:**
- Navigation groups: **Operate** — Overview `/`, Dispatch `/dispatch`, Stress test `/stress-test`, Unit commitment `/commitment`; **Forecast** — Forecast lab `/forecast`; **Fairness** — Tenants & fairness `/tenants`, Approvals `/approvals`, Policies `/policies`; **Prove** — Savings & carbon `/impact`, What-if `/whatif`, Benchmarks `/research`; **Govern** — Data admission `/data`, Administration `/admin`, Settings `/settings`.

- [ ] **Step 1: Navigation**

Replace the `NAV` array in `layout.tsx` with the entries above (icons from `lucide-react`: `Gauge`, `Activity`, `Zap`, `CalendarClock`, `LineChart`, `Users`, `ClipboardCheck`, `FileText`, `Leaf`, `SlidersHorizontal`, `Microscope`, `Database`, `ShieldCheck`, `Settings2`) and the group names.

- [ ] **Step 2: Overview (`page.tsx`)**

The page keeps a "current replay" in the URL (`?replay=`). With none, it shows a form: site (from `GET /energy/sites`), day (date input limited to the series), controller (from `GET /energy/controllers`), forecaster, scenario regime (`normal`, `blackout`, `cloud_drop`, `machine_start`, `combined`, `dr_event`, seeded by a seed field), UC toggle, and a "Run day" `Button` posting `/energy/replays` with an idempotency key. With a replay it renders `<ReplayPlayer>`, a KPI row (`operating_cost`, `peak_import_kw`, `co2_kg`, `unserved_kwh`, `critical_served_pct`, `mean_power_factor`, `dr_cost`, `capacity_fade_pct`; each `Stat` with `kind="simulated"`), the 3D park (Task 9) and links to its report and bills.

- [ ] **Step 3: Dispatch (`dispatch/page.tsx`)**

Pick two controllers for the same day and scenario; post both replays; show two synchronised players (one `usePlayer` driving both) and a table of KPI differences with the better value marked. Explanations of the same step side by side.

- [ ] **Step 4: Stress test (`stress-test/page.tsx`)** — the live-demo screen

Large buttons: **Blackout now** (duration selector 15 min – 4 h), **Cloud drop now**, **Machine start-up now** (size 15–35 % of peak), **Demand-response event now** (reduction kW), each posting `/energy/replays/{id}/events` with `start = k` (the player's current step) and switching the player to the child replay at the same `k`. Next to the player: the frequency trace for transient steps (nadir vs nominal, UFLS thresholds as horizontal lines), the live shed log for the replay (tenant, kW, trigger, rule), and a counter of peer-triggered events. Keyboard shortcuts `B`, `C`, `M`, `D` with visible hints and `aria-keyshortcuts`.

- [ ] **Step 5: Unit commitment (`commitment/page.tsx`)**

Gantt per diesel unit from `GET /energy/sites/{site}/commitment?day=&alert=` (ECharts custom series or stacked bars over 96 steps), with net-demand q50/q90 lines and the reserve requirement; toggle "storm warning" (alert) to show the islanding reserve; footer with starts, fuel, NOx and PM.

- [ ] **Step 6: Tenants & fairness (`tenants/page.tsx`)**

Table of park tenants (share, priority, flexible share) with the published shed-order policy text; shed log filterable by tenant (`GET /energy/shed-log`); burden-equity chart (shed kWh per kWh demand per tenant over all replays of the workspace); bill allocation for the selected replay (`GET /replays/{id}/bills`) with shed compensation and DR credit columns.

- [ ] **Step 7: Forecast lab, Savings & carbon, What-if, Benchmarks, Approvals, Policies**

- Forecast lab: quantile fan (q10–q90 band, q25–q75 band, median) for load and PV at a chosen step of a day, actual overlaid; GF1 table from `/energy/benchmarks`.
- Savings & carbon: for the selected replay vs `no_battery` on the same day and scenario (post it if missing): peak shaved (kW), energy-cost saving, demand-charge saving, CO2 avoided, diesel hours, NOx and PM grams; cost–carbon frontier component reused from `emissions-frontier.tsx` fed with MB1 results when present.
- What-if: sliders battery hours (0.5–6) and PV ratio (0–1.5) → `POST /energy/whatif` → base vs variant KPI table and delta bars.
- Benchmarks: study cards for GF1, UC1, MB1, MB2, FS1, CY1, DR1 with headline, status, confidence intervals, negative results.
- Approvals: list of `dispatch_requests` with kind, payload (rendered), payload hash, requester, expiry; approve/reject sends the shown hash; planners get a "Request" form (DR shed of a tenant for a window, or battery override).
- Policies: tariff tables per site with assumed values flagged, load-shed priority policy, shed-compensation policy, demand-response programme terms, data sources and licences; document library from the retained retrieval engine.

- [ ] **Step 8: Remove old screens and run web checks**

```bash
cd apps/web && git rm -q -r "app/(app)/exceptions" "app/(app)/inventory" "app/(app)/runs" "app/(app)/scenarios" "app/(app)/value" && cd -
npm --prefix apps/web run typecheck && npm --prefix apps/web run lint && npm --prefix apps/web test
git add -A apps/web
git commit -m "Add EMS screens: overview, dispatch, stress test, commitment, tenants, impact, what-if, approvals

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: 3D industrial park

**Files:**
- Create: `apps/web/components/park3d.tsx` (from `warehouse3d.tsx`)
- Delete: `apps/web/components/warehouse3d.tsx` after the move

**Interfaces:**
- `<Park3D record tenants />`: five tenant buildings sized by share, rooftop PV panels on each roof (emissive intensity ∝ `pv_used_kw / pv_kwp`), a battery container (fill height ∝ SoC, colour by charge/discharge), a diesel yard (two units, smoke particles when on), a grid substation (red when `grid_available` is false), animated flow lines toward the park bus with speed ∝ kW; a tenant turns grey with a "shed" label when its `shed_by_tenant` is > 0. Keeps `gl-boundary.tsx` WebGL fallback and the 2D table alternative for accessibility.

- [ ] **Step 1: Move and adapt**

`git mv apps/web/components/warehouse3d.tsx apps/web/components/park3d.tsx`, keep its canvas, camera, lights, theme handling and WebGL boundary; replace the rack/slot geometry with the objects above; keep the legend pattern (opaque background, theme colours). Add an accessible table under the canvas listing each tenant's demand, shed and status for the current step.

- [ ] **Step 2: Checks and commit**

```bash
npm --prefix apps/web run typecheck && npm --prefix apps/web run lint
git add -A apps/web/components
git commit -m "Turn the 3D warehouse into a 3D industrial park with live shed state

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Browser journeys

**Files:**
- Create: `apps/web/e2e/energy-journey.spec.ts`, `apps/web/e2e/stress-test.spec.ts`, `apps/web/e2e/approvals-energy.spec.ts`
- Delete/modify: supply-chain e2e specs (`journey`, `workflows`, `operations`, `consistency`, `remediation` cases about removed screens); rebuild visual baselines.

- [ ] **Step 1: Write the journeys**

`apps/web/e2e/stress-test.spec.ts`:
```ts
import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

test("peer-triggered blackout islands the park and shows sheds with reasons", async ({ page }) => {
  await signIn(page, "planner", "demo");
  await page.goto("/?ws=demo");
  await page.getByLabel("Controller").selectOption("rule_tou");
  await page.getByRole("button", { name: "Run day" }).click();
  await expect(page.getByLabel("Replay step")).toBeVisible();
  await page.getByLabel("Replay step").fill("70");
  await page.goto(page.url().replace("/?", "/stress-test?"));
  await page.getByRole("button", { name: /Blackout now/ }).click();
  await expect(page.getByText(/islanded/)).toBeVisible();
  await expect(page.getByRole("table", { name: /Shed log/ })).toContainText(/UFLS|shortfall/);
});
```
`energy-journey.spec.ts`: sign in as viewer → Overview shows a precomputed replay (Task 11) with KPIs and provenance labels; Benchmarks lists GF1; switching site to the UAE what-if relabels currency to AED. `approvals-energy.spec.ts`: planner requests a DR shed of T4; approver sees it with its payload hash and approves; the request shows `delivered`; the planner cannot approve their own request (button disabled with explanation).

- [ ] **Step 2: Run, fix, rebuild baselines, commit**

```bash
cd apps/web && npx playwright test --project desktop --project mobile 2>&1 | tail -5
npx playwright test --project desktop --grep visual --update-snapshots && cd -
git add -A apps/web/e2e
git commit -m "Add energy browser journeys and rebuild visual baselines

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Hosting, precomputed replays and the offline fallback

**Files:**
- Create: `scripts/precompute_replays.py`
- Modify: `docker-compose.yml`, `deploy/vercel-api/*` build script inputs (`scripts/vercel/build_api.py`), `.github/workflows/keep-warm.yml`, `docs/operations/hosted-demo.md`

- [ ] **Step 1: Precompute demonstration replays**

`scripts/precompute_replays.py` seeds, for each workspace, replays of one weekday under every available controller in `normal`, `blackout`, `dr_event` and `combined` (fixed seeds), so the hosted demo opens instantly and the presentation never waits on a solver:
```python
"""Create the demonstration replays for every seeded workspace (idempotent: skips existing ones)."""
from gridlens.energy import parks, replay
from gridlens.seed import tenant_id, user_id

DAYS = {"gwangyang-park": ("kr_gwangyang", "2018-11-15"), "abu-dhabi-whatif": ("ae_industrial", "2018-11-15"),
        "demo": ("demo", "2018-11-02")}
REGIMES = {"normal": [], "blackout": [{"kind": "blackout", "start": 72, "duration": 12, "magnitude": 0.0}],
           "dr_event": [{"kind": "dr_event", "start": 56, "duration": 8, "magnitude": 0.0}]}


def main() -> None:
    for ws, (site, day) in DAYS.items():
        t, u = tenant_id(ws), user_id("planner@" + ws + ".test")
        p_peak = parks.park(site).site.p_peak_kw
        for regime, events in REGIMES.items():
            evs = [dict(e, magnitude=0.2 * p_peak) if e["kind"] == "dr_event" else e for e in events]
            for c in parks.available_controllers(site):
                rid = replay.create(t, u, site, day, c, {"seed": 0, "regime": regime, "events": evs},
                                    uc=False, forecaster="lgbm")
                replay.run(t, rid)
                print(ws, regime, c, rid)


if __name__ == "__main__":
    main()
```
(Use the real seeded planner e-mail pattern from `seed.dev_email`.)

- [ ] **Step 2: Offline fallback**

In `docker-compose.yml` mount `data/raw/energy`, `data/silver/energy` and `models/rl` read-only into the API and worker containers, and add a one-shot `precompute` service running `scripts/precompute_replays.py` after migrations. Document in `docs/operations/hosted-demo.md`: `docker compose up` on the presenting laptop with no network, the expected start time, and the rehearsal checklist.

- [ ] **Step 3: Hosted demo**

Include `config/`, the cached forecasts and the RL `.npz/.json` files in the Vercel API bundle (`scripts/vercel/build_api.py`); exclude PyTorch and LightGBM from the hosted dependency set (the API imports neither). After the owner renames the Vercel and Neon projects, update the URL in `.github/workflows/keep-warm.yml`.

- [ ] **Step 4: Checks and commit**

```bash
uv run python scripts/precompute_replays.py
docker compose up -d && sleep 20 && curl -fsS localhost:8000/api/v1/auth/config && docker compose down
git add -A scripts docker-compose.yml deploy docs/operations .github/workflows/keep-warm.yml
git commit -m "Add precomputed demo replays, offline Docker fallback and hosted bundle for GridLens

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Done when

- `uv run pytest -q`, `uv run pytest tests_energy -q`, web typecheck, lint, unit tests and the Playwright desktop and mobile projects pass.
- On the hosted demo and in `docker compose up` without network: open Overview → a precomputed replay plays; Stress test → "Blackout now" forks and shows islanding, frequency and the shed log with reasons; Approvals → a DR shed request goes from pending to delivered with a second person's approval.
