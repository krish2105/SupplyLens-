"""Regression tests for the Phase 1 findings (docs/agent-handoff/ISSUES.md). Issue IDs are in the test names.

Each test states the correct behaviour against the real PostgreSQL schema, the CP-SAT solver and the sandbox adapter.
"""
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens import demo as demo_profile
from supplylens import jobs
from supplylens.actions import service as act
from supplylens.agent.graph import create_run
from supplylens.api.app import app
from supplylens.authz import resolve_actor
from supplylens.config import settings
from supplylens.db import tenant_session
from supplylens.integrations import sandbox_erp
from supplylens.planning.positions import load_positions
from supplylens.planning.terms_service import applicable_terms
from supplylens.seed import dev_email, user_id
from supplylens.simulation import demo
from supplylens_opt.planner import Need, Offer, PlanRequest, plan
from supplylens_opt.validator import validate
from supplylens_worker.main import tick

H = {"X-Requested-With": "supplylens"}
DEMO = {**H, "X-SupplyLens-Tenant": "demo"}
CUTOFF = datetime(2026, 10, 20, 9, tzinfo=UTC)
EFF = date(2026, 10, 20)


def who(tenant, role):
    return resolve_actor(user_id(dev_email(role)), tenant)


def login(role):
    c = TestClient(app)
    assert c.post("/api/v1/auth/dev-login", json={"email": dev_email(role)}, headers=H).status_code == 200
    return c


@pytest.fixture()
def demo_tenant(clean_db, tenant_b):
    demo.load(tenant_b)
    return tenant_b


def prepared(tenant, effective=EFF):
    res = applicable_terms(tenant, ["DEMO-REF-SKU"], CUTOFF, effective)
    req = PlanRequest(decision_date=effective, need_by=date(2026, 10, 22), currency="USD", budget_minor=18000,
                      needs=[Need(sku_id="DEMO-REF-SKU", required_units=30)], offers=res.applicable)
    result = plan(req)
    decision = {"knowledge_cutoff": CUTOFF.isoformat(), "effective_date": effective.isoformat(),
                "plan_input_hash": result.input_hash, "budget_minor": 18000}
    return act.prepare(who(tenant, "planner"), supplier_id=result.lines[0].supplier_id, lines=result.lines,
                       currency="USD", need_by=req.need_by, decision=decision, evidence={}, versions={})


def approved(tenant):
    a = prepared(tenant)
    act.approve(who(tenant, "approver"), a["id"], payload_hash=a["payload_hash"], expected_row_version=a["row_version"])
    return a


# =========================================================================================== P0-SEC-01 public demo
@pytest.fixture()
def demo_env(monkeypatch):
    monkeypatch.setattr(settings, "environment", "demo")


ADMIN_WRITES = [
    ("post", "/api/v1/admin/members", {"json": {"email": dev_email("viewer"), "role": None}}),
    ("post", "/api/v1/onboarding/workspaces", {"json": {"slug": "visitor-ws", "name": "Visitor", "currency": "USD",
                                                       "weekly_budget_minor": 1000}}),
    ("post", "/api/v1/onboarding/batches", {"data": {"kind": "sales", "rights": "visitor upload"},
                                           "files": {"file": ("s.csv", b"sku_id,day,units\nA,2026-01-01,1\n", "text/csv")}}),
]


@pytest.mark.parametrize("method,url,kw", ADMIN_WRITES)
def test_P0_SEC_01_demo_profile_refuses_workspace_administration_for_every_role(demo_tenant, demo_env, method, url, kw):
    c = login("tenant_admin")
    r = getattr(c, method)(url, headers={**DEMO, "Idempotency-Key": uuid.uuid4().hex}, **kw)
    assert r.status_code == 403 and "public demo" in r.json()["message"]
    with tenant_session(demo_tenant) as s:              # nothing changed: memberships intact, no workspace, no batch
        assert s.execute(text("SELECT count(*) FROM import_batches")).scalar() == 0
    assert who(demo_tenant, "viewer") is not None


def test_P0_SEC_01_demo_profile_refuses_export_deletion_and_model_promotion(demo_tenant, demo_env):
    c = login("tenant_admin")
    for url, body in (("/api/v1/admin/exports", {}), ("/api/v1/models/00000000-0000-0000-0000-000000000000/status",
                                                {"status": "RETIRED", "reason": "visitor test"})):
        r = c.post(url, json=body, headers={**DEMO, "Idempotency-Key": uuid.uuid4().hex})
        assert r.status_code == 403, (url, r.text)
    with pytest.raises(Exception, match="public demo"):
        who(demo_tenant, "tenant_admin").require("tenant.delete")


def test_P0_SEC_01_demo_profile_keeps_the_planning_and_approval_journey_open(demo_tenant, demo_env):
    for role, op in (("viewer", "read"), ("planner", "agent.start"), ("planner", "action.prepare"),
                     ("approver", "action.approve"), ("approver", "action.reconcile")):
        who(demo_tenant, role).require(op)              # does not raise
    a = approved(demo_tenant)
    assert act.get(who(demo_tenant, "viewer"), a["id"])["status"] == "QUEUED"


def test_P0_SEC_01_outside_the_demo_an_administrator_still_administers(demo_tenant):
    who(demo_tenant, "tenant_admin").require("admin.write")


def test_P0_SEC_01_demo_sign_in_releases_visitor_orders_left_open(demo_tenant, demo_env):
    a = approved(demo_tenant)
    assert act.dispatch_once(demo_tenant)["result"] == "RECONCILED"
    login("viewer")                                     # a fresh order is kept: the visitor may still be using it
    assert [x["open_units"] for x in act.open_orders(who(demo_tenant, "viewer")) if x["action_id"] == a["id"]] == [30]
    with tenant_session(demo_tenant) as s:              # an hour later nobody has touched it
        s.execute(text("UPDATE purchase_order_lines SET updated_at = now() - interval '2 hours'"))
    login("viewer")
    line = [x for x in act.open_orders(who(demo_tenant, "viewer")) if x["action_id"] == a["id"]][0]
    assert (line["open_units"], line["cancelled_units"], line["status"]) == (0, 30, "CANCELLED")
    with tenant_session(demo_tenant) as s:              # recorded like any other cancellation, by the system
        audit = s.execute(text("SELECT actor_id, detail FROM audit_events WHERE action='order.cancelled_open_units'")).first()
    assert audit.actor_id is None and "housekeeping" in audit.detail["reason"]
    assert demo_profile.release_stale_orders() == 0     # idempotent


def test_P0_SEC_01_outside_the_demo_sign_in_never_touches_orders(demo_tenant):
    approved(demo_tenant)
    act.dispatch_once(demo_tenant)
    with tenant_session(demo_tenant) as s:
        s.execute(text("UPDATE purchase_order_lines SET updated_at = now() - interval '2 hours'"))
    login("viewer")
    assert sum(x["open_units"] for x in act.open_orders(who(demo_tenant, "viewer"))) == 30


# =========================================================================================== P1-SEC-02 owner credentials
def _run_vercel_entry(monkeypatch, tmp_path, env: dict) -> dict:
    """Execute the generated Vercel entrypoint up to (not including) the application import, in a scratch environment."""
    import os
    source = (settings_repo() / "deploy" / "vercel-api" / "index.py").read_text()
    entry = source.split("from supplylens.api.app import app")[0]
    for k in list(os.environ):
        if k.startswith(("DATABASE_URL", "POSTGRES_", "PG", "NEON_", "SUPPLYLENS_")):
            monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    saved = dict(os.environ)
    try:                       # a scratch bundle directory: no hosted storage is copied anywhere
        exec(compile(entry, "index.py", "exec"), {"__file__": str(tmp_path / "index.py")})  # noqa: S102
        return dict(os.environ)
    finally:
        os.environ.clear()
        os.environ.update(saved)


def settings_repo():
    from supplylens.config import REPO_ROOT
    return REPO_ROOT


NEON = {"DATABASE_URL_UNPOOLED": "postgres://neon_owner:0wnerPw@ep-x.neon.tech/neondb?sslmode=require",
        "DATABASE_URL": "postgres://neon_owner:0wnerPw@ep-x-pooler.neon.tech/neondb", "PGPASSWORD": "0wnerPw",
        "POSTGRES_URL": "postgres://neon_owner:0wnerPw@ep-x.neon.tech/neondb", "SUPPLYLENS_APP_DB_PASSWORD": "a" * 30}


def test_P1_SEC_02_serving_function_keeps_only_the_app_role(monkeypatch, tmp_path):
    env = _run_vercel_entry(monkeypatch, tmp_path, NEON)
    assert env["SUPPLYLENS_DATABASE_URL"].startswith("postgresql+psycopg://supplylens_app:")
    assert "SUPPLYLENS_ADMIN_DATABASE_URL" not in env
    assert not [k for k in env if k.startswith(("DATABASE_URL", "POSTGRES_", "PGPASSWORD"))]
    assert not [v for v in env.values() if "0wnerPw" in v]


def test_P1_SEC_02_owner_url_exists_only_while_setup_is_enabled(monkeypatch, tmp_path):
    env = _run_vercel_entry(monkeypatch, tmp_path, {**NEON, "SUPPLYLENS_SETUP_TOKEN": "t" * 40})
    assert env["SUPPLYLENS_ADMIN_DATABASE_URL"].startswith("postgresql+psycopg://neon_owner:")


# =========================================================================================== P0-PLAN-01 shortfall


D = date(2026, 1, 5)


def offer(term="T", supplier="S", sku="A", cost=640, moq=1, mult=1, lead=2):
    return Offer(term_id=term, supplier_id=supplier, sku_id=sku, unit_cost_minor=cost, currency="USD", moq=moq,
                 order_multiple=mult, lead_time_days=lead)


def req(offers, need=100, budget=10**8, by_lead=None, allow_shortfall=True, penalty=500, need_by=30):
    return PlanRequest(decision_date=D, need_by=D + timedelta(days=need_by), currency="USD", budget_minor=budget,
                       needs=[Need(sku_id="A", required_units=need, required_units_by_lead_time=by_lead or {})],
                       offers=offers, allow_shortfall=allow_shortfall, shortage_penalty_minor=penalty)


@pytest.mark.parametrize("cost", [499, 500, 501, 640, 50_000])
def test_P0_PLAN_01_shortfall_is_never_cheaper_than_buying_when_the_constraints_allow_buying(cost):
    r = plan(req([offer(cost=cost)], penalty=500))
    assert r.status == "OPTIMAL" and r.shortfall == {} and sum(l.quantity for l in r.lines) == 100


def test_P0_PLAN_01_a_binding_budget_leaves_an_explained_partial_order():
    r = plan(req([offer(cost=640)], budget=640 * 60))
    assert sum(l.quantity for l in r.lines) == 60 and r.shortfall == {"A": 40}
    assert r.explanation[0].startswith("40 required unit(s) cannot be covered")
    assert any("'budget'" in e for e in r.explanation) and validate(req([offer(cost=640)], budget=640 * 60), r) == []


def test_P0_PLAN_01_reference_case_orders_30_even_when_shortfall_is_allowed(demo_tenant):
    res = applicable_terms(demo_tenant, ["DEMO-REF-SKU"], CUTOFF, EFF)
    r = plan(PlanRequest(decision_date=EFF, need_by=date(2026, 10, 22), currency="USD", budget_minor=18000,
                         needs=[Need(sku_id="DEMO-REF-SKU", required_units=30)], offers=res.applicable,
                         allow_shortfall=True, shortage_penalty_minor=500))
    assert r.shortfall == {} and [(l.supplier_id, l.quantity) for l in r.lines] == [("DEMO-REF-B", 30)]


def _run(tenant, **inp):
    run = create_run(who(tenant, "planner"), mode="draft", inp={
        "sku_ids": ["DEMO-REF-SKU"], "knowledge_cutoff": CUTOFF.isoformat(), "effective_date": EFF.isoformat(),
        "currency": "USD", **inp})
    tick()
    with tenant_session(tenant) as s:
        return s.execute(text("SELECT status, state FROM agent_runs WHERE id=:i"), {"i": run}).mappings().first()


def test_P0_PLAN_01_agent_default_run_orders_the_reference_need(demo_tenant):
    r = _run(demo_tenant, budget_minor=18000)               # allow_shortfall left at its default
    assert r["state"]["plan"]["shortfall"] == {} and r["state"]["checks"]["warnings"] == []
    assert r["status"] == "WAITING_FOR_APPROVAL" and len(r["state"]["actions"]) == 1


def test_P0_PLAN_01_agent_partial_order_carries_a_shortfall_warning_to_the_approver(demo_tenant):
    r = _run(demo_tenant, budget_minor=9000)
    assert r["state"]["plan"]["shortfall"] == {"DEMO-REF-SKU": 15}
    assert [w["kind"] for w in r["state"]["checks"]["warnings"]] == ["shortfall"]
    a = act.get(who(demo_tenant, "approver"), r["state"]["actions"][0])
    assert a["evidence"]["checks"]["warnings"][0]["detail"]["uncovered_units"] == {"DEMO-REF-SKU": 15}


def test_P0_PLAN_01_agent_with_no_affordable_order_requires_review_instead_of_succeeding(demo_tenant):
    r = _run(demo_tenant, budget_minor=0)
    assert r["status"] == "REVIEW_REQUIRED"
    assert [i["kind"] for i in r["state"]["checks"]["issues"]] == ["shortfall_unmet"]


# =========================================================================================== P1-PLAN-02 lead time
def test_P1_PLAN_02_a_slower_supplier_must_cover_its_longer_protection_interval():
    fast, slow = offer(term="F", supplier="FAST", cost=110, lead=2), offer(term="L", supplier="SLOW", cost=100, lead=21)
    r = plan(req([fast, slow], need=273, by_lead={2: 273, 21: 482}, allow_shortfall=False))
    (line,) = r.lines
    # SLOW is cheaper per unit but must deliver 482 (48,200) against FAST's 273 (30,030): FAST wins
    assert (line.supplier_id, line.quantity) == ("FAST", 273)
    r2 = plan(req([fast, slow], need=273, by_lead={2: 273, 21: 300}, allow_shortfall=False))
    assert (r2.lines[0].supplier_id, r2.lines[0].quantity) == ("SLOW", 300)


def test_P1_PLAN_02_validator_rejects_a_slow_line_sized_for_the_fast_lead_time():
    fast, slow = offer(term="F", supplier="FAST", cost=110, lead=2), offer(term="L", supplier="SLOW", cost=100, lead=21)
    rq = req([fast, slow], need=273, by_lead={2: 273, 21: 482}, allow_shortfall=False)
    bad = plan(req([slow], need=273, allow_shortfall=False))          # sized without the lead-time requirement
    assert any("21-day lead time" in v for v in validate(rq, bad))


def test_P1_PLAN_02_scenario_sizes_each_supplier_for_its_own_lead_time(uci_world):
    with tenant_session(uci_world) as s:
        s.execute(text("""INSERT INTO suppliers VALUES (:t,'SLOW','Slow supplier','generated','synthetic')"""), {"t": uci_world})
        s.execute(text("""INSERT INTO supplier_terms (term_id, tenant_id, supplier_id, sku_id, unit_cost_minor, currency,
            moq, order_multiple, lead_time_days, valid_from, known_at, value_kind, source_kind) VALUES ('T-S2-SLOW',:t,'SLOW',
            'S2',90,'GBP',1,1,10,'2011-01-01','2011-01-01T00:00:00Z','simulated','generated')"""), {"t": uci_world})
    from supplylens.planning.scenario import ScenarioInput, run_scenario
    out = run_scenario(who(uci_world, "planner"), ScenarioInput(sku_ids=["S2"], budget_minor=10**7))
    ordered = 0
    for key, need in out["needs"].items():
        by_lead = {int(k): v for k, v in need["required_units_by_lead_time"].items()}
        assert set(by_lead) == {3, 10} and by_lead[10] >= by_lead[3]
        if not need["required_units"]:
            continue                        # this site has no share of the SKU's sales
        ordered += 1
        line = next(l for l in out["plan"]["lines"] if l["sku_id"] == key)
        lead = 3 if line["supplier_id"] == "SUP" else 10
        assert line["quantity"] >= by_lead[lead]
    assert ordered


# =========================================================================================== P2-PLAN-03 / -04 / -05
@pytest.fixture()
def uci_world(clean_db, tenant_a):
    """UCI workspace with a 140-day history: S1 at one site (capacity 10; MOQ 12 in packs of 6), S2 at two sites."""
    did = uuid.uuid4()
    with tenant_session(tenant_a) as s:
        s.execute(text("INSERT INTO datasets (id, tenant_id, name, source_kind, license, file_name, sha256, bytes, "
                       "schema_version, status) VALUES (:i,:t,'synthetic','generated','n/a','f','h',1,'v','READY')"),
                  {"i": did, "t": tenant_a})
        for sku in ("S1", "S2"):
            s.execute(text("INSERT INTO products (tenant_id, sku_id, source_kind) VALUES (:t,:k,'generated')"),
                      {"t": tenant_a, "k": sku})
        for loc in ("WH", "WH2"):
            s.execute(text("INSERT INTO locations VALUES (:t,:l,:l,'warehouse',true,'synthetic')"), {"t": tenant_a, "l": loc})
        s.execute(text("INSERT INTO inventory_positions VALUES (:t,'WH','Z','S1','2011-05-20',0,0,0,10,'simulated',NULL)"),
                  {"t": tenant_a})
        for loc in ("WH", "WH2"):
            s.execute(text("INSERT INTO inventory_positions VALUES (:t,:l,'Z','S2','2011-05-20',3,0,0,NULL,'simulated',NULL)"),
                      {"t": tenant_a, "l": loc})
        s.execute(text("INSERT INTO suppliers VALUES (:t,'SUP','Supplier','generated','synthetic')"), {"t": tenant_a})
        for sku in ("S1", "S2"):
            s.execute(text("""INSERT INTO supplier_terms (term_id, tenant_id, supplier_id, sku_id, unit_cost_minor, currency,
                moq, order_multiple, lead_time_days, valid_from, known_at, value_kind, source_kind) VALUES (:id,:t,'SUP',:k,
                100,'GBP',12,6,3,'2011-01-01','2011-01-01T00:00:00Z','simulated','generated')"""),
                      {"id": f"T-{sku}", "t": tenant_a, "k": sku})
        s.execute(text("INSERT INTO tenant_settings VALUES (:t,'2011-05-20T12:00:00Z','GBP',:d,NULL,CAST(:p AS jsonb))"),
                  {"t": tenant_a, "d": did, "p": '{"weekly_budget_minor": 100000, "coverage_days": 14}'})
        for i in range(140):
            for sku in ("S1", "S2"):
                s.execute(text("INSERT INTO sales_daily VALUES (:t,:d,:k,'WH',:day,:u)"),
                          {"t": tenant_a, "d": did, "k": sku, "day": date(2011, 1, 1) + timedelta(days=i), "u": (i % 7) + 2})
    return tenant_a


def test_P2_PLAN_03_replay_ignores_stock_recorded_after_the_knowledge_cutoff(uci_world):
    from supplylens.planning.scenario import ScenarioInput, run_scenario
    with tenant_session(uci_world) as s:      # an earlier snapshot; the fixture's 2011-05-20 snapshot holds 0 units
        s.execute(text("INSERT INTO inventory_positions VALUES (:t,'WH','Z','S1','2011-05-10',7,0,0,10,'simulated',NULL)"),
                  {"t": uci_world})
    out = run_scenario(who(uci_world, "planner"), ScenarioInput(
        sku_ids=["S1"], knowledge_cutoff=datetime(2011, 5, 15, 12, tzinfo=UTC), effective_date=date(2011, 5, 20)))
    assert out["needs"]["S1"]["available"] == 7          # the 2011-05-20 snapshot was not known at the cutoff
    later = run_scenario(who(uci_world, "planner"), ScenarioInput(
        sku_ids=["S1"], knowledge_cutoff=datetime(2011, 5, 20, 12, tzinfo=UTC), effective_date=date(2011, 5, 20)))
    assert later["needs"]["S1"]["available"] == 0        # known once the cutoff reaches it


def test_P2_PLAN_05_scenario_never_plans_with_conflicting_terms(uci_world):
    from supplylens.planning.scenario import ScenarioInput, run_scenario
    with tenant_session(uci_world) as s:      # a second, unlinked term for the same supplier and SKU: a conflict
        s.execute(text("""INSERT INTO supplier_terms (term_id, tenant_id, supplier_id, sku_id, unit_cost_minor, currency,
            moq, order_multiple, lead_time_days, valid_from, known_at, value_kind, source_kind) VALUES ('T-S1-X',:t,'SUP',
            'S1',50,'GBP',1,1,3,'2011-01-01','2011-01-01T00:00:00Z','simulated','generated')"""), {"t": uci_world})
    out = run_scenario(who(uci_world, "planner"), ScenarioInput(sku_ids=["S1"]))
    assert out["terms"]["excluded_for_conflict"] == ["T-S1", "T-S1-X"]
    assert not [l for l in out["plan"]["lines"] if l["term_id"] in ("T-S1", "T-S1-X")]


def test_P2_PLAN_04_missing_trading_days_do_not_shorten_calendar_lags():
    import random

    from supplylens_opt.leadtime_demand import estimate_dependence
    rng = random.Random(7)
    x, vals = 0.0, []
    for _ in range(400):                       # AR(1) demand, persistence 0.9
        x = 0.9 * x + rng.gauss(0, 1)
        vals.append(max(0.0, 20 + 3 * x))
    days = list(range(400))
    full = estimate_dependence(vals, [d % 7 for d in days], ordinals=days)
    kept = [d for d in days if d % 7 != 5 and rng.random() > 0.25]      # no Saturdays, a quarter of other days missing
    gappy = estimate_dependence([vals[d] for d in kept], [d % 7 for d in kept], ordinals=kept)
    naive = estimate_dependence([vals[d] for d in kept], [d % 7 for d in kept])
    assert abs(gappy[0][0] - full[0][0]) < 0.1                 # calendar lags recover the lag-1 dependence
    assert abs(naive[0][0] - full[0][0]) > abs(gappy[0][0] - full[0][0])


# =========================================================================================== P1-ACT-01 STALE re-approval


def _expire_approval(tenant, action_id):
    with tenant_session(tenant) as s:
        s.execute(text("UPDATE approvals SET expires_at = now() - interval '1 minute' WHERE action_id=:a"), {"a": action_id})


def test_P1_ACT_01_a_stale_action_can_be_reviewed_edited_reapproved_and_sent_once(demo_tenant):
    a = approved(demo_tenant)
    _expire_approval(demo_tenant, a["id"])
    assert act.dispatch_once(demo_tenant)["result"] == "STALE"
    stale = act.get(who(demo_tenant, "planner"), a["id"])
    edited = act.edit_quantities(who(demo_tenant, "planner"), a["id"], quantities={"DEMO-REF-SKU": 25},
                                 expected_row_version=stale["row_version"], budget_minor=None)
    assert edited["status"] == "PENDING_APPROVAL"
    out = act.approve(who(demo_tenant, "approver"), a["id"], payload_hash=edited["payload_hash"],
                      expected_row_version=edited["row_version"])
    assert out == {"status": "QUEUED", "operation_id": f"po-{a['id']}"}         # same operation key, never a second one
    assert act.dispatch_once(demo_tenant)["result"] == "RECONCILED"
    assert sandbox_erp.count_for_key(f"po-{a['id']}") == 1
    assert sandbox_erp.lookup(f"po-{a['id']}")["lines"][0]["quantity"] == 25          # the re-approved payload was sent
    final = act.get(who(demo_tenant, "viewer"), a["id"])
    assert final["status"] == "RECONCILED" and len([x for x in final["approvals"] if x["decision"] == "APPROVED"]) == 2


def test_P1_ACT_01_reapproval_never_overrides_an_active_dispatch(demo_tenant):
    a = approved(demo_tenant)                                  # outbox PENDING
    with tenant_session(demo_tenant) as s:                     # force the action back to review without touching the outbox
        s.execute(text("UPDATE actions SET status='PENDING_APPROVAL' WHERE id=:a"), {"a": a["id"]})
    cur = act.get(who(demo_tenant, "viewer"), a["id"])
    with pytest.raises(act.ActionError) as e:
        act.approve(who(demo_tenant, "approver"), a["id"], payload_hash=cur["payload_hash"],
                    expected_row_version=cur["row_version"])
    assert e.value.code == "invalid_state" and "PENDING" in str(e.value)


# =========================================================================================== P1-ACT-02 committed supply
def _on_order(tenant):
    with tenant_session(tenant) as s:
        pos, _ = load_positions(s, ["DEMO-REF-SKU"], EFF)
    return pos["DEMO-REF-SKU"]["on_order"]


def test_P1_ACT_02_an_approved_order_not_yet_sent_already_counts_as_supply(demo_tenant):
    base = _on_order(demo_tenant)
    approved(demo_tenant)                                       # QUEUED: nothing sent, nothing reconciled yet
    assert _on_order(demo_tenant) - base == 30
    r = _run(demo_tenant, budget_minor=18000)                   # a second investigation does not buy the need again
    assert r["state"]["plan"]["status"] == "NO_ACTION" and not r["state"].get("actions")
    # the worker tick that ran the investigation then dispatched the queued order
    assert [x["status"] for x in act.open_orders(who(demo_tenant, "viewer"))] == ["OPEN"]
    assert _on_order(demo_tenant) - base == 30                  # counted once: moved from committed to the ledger


@pytest.mark.parametrize("state", ["UNKNOWN_OUTCOME", "SUBMITTED"])
def test_P1_ACT_02_orders_of_unknown_or_unconfirmed_outcome_count_as_supply(demo_tenant, state):
    base = _on_order(demo_tenant)
    a = approved(demo_tenant)
    with tenant_session(demo_tenant) as s:
        s.execute(text("UPDATE actions SET status=:s WHERE id=:a"), {"s": state, "a": a["id"]})
    assert _on_order(demo_tenant) - base == 30


def test_P1_ACT_02_a_rejected_or_pending_draft_is_not_supply(demo_tenant):
    base = _on_order(demo_tenant)
    p = prepared(demo_tenant)
    assert _on_order(demo_tenant) == base
    act.reject(who(demo_tenant, "approver"), p["id"], reason="not needed", expected_row_version=p["row_version"])
    assert _on_order(demo_tenant) == base


def test_P1_ACT_02_a_read_back_mismatch_counts_as_supply_and_can_be_accepted_by_an_approver(demo_tenant):
    base = _on_order(demo_tenant)
    a = approved(demo_tenant)
    sandbox_erp.inject_fault(f"po-{a['id']}", "alter_line_price")
    assert act.dispatch_once(demo_tenant)["result"] == "MISMATCH"
    assert act.get(who(demo_tenant, "viewer"), a["id"])["status"] == "CONFIRMED"
    assert _on_order(demo_tenant) - base == 30                  # the order exists at the target: it is supply
    with pytest.raises(Exception, match="may not perform"):     # a planner cannot accept a changed order
        act.accept_remote_order(who(demo_tenant, "planner"), a["id"], reason="ok")
    done = act.accept_remote_order(who(demo_tenant, "approver2"), a["id"], reason="supplier price +0.01 accepted")
    assert done["status"] == "RECONCILED" and "differences" in done["status_reason"]
    line = [x for x in act.open_orders(who(demo_tenant, "viewer")) if x["action_id"] == a["id"]][0]
    assert (line["ordered_units"], line["open_units"]) == (30, 30)
    assert _on_order(demo_tenant) - base == 30                  # still counted once
    with pytest.raises(act.ActionError):                        # only once
        act.accept_remote_order(who(demo_tenant, "approver2"), a["id"], reason="again")


def test_P1_ACT_02_accepting_a_cancelled_remote_order_releases_its_units(demo_tenant):
    base = _on_order(demo_tenant)
    a = approved(demo_tenant)
    sandbox_erp.inject_fault(f"po-{a['id']}", "cancel_after_commit")
    act.dispatch_once(demo_tenant)
    act.accept_remote_order(who(demo_tenant, "approver"), a["id"], reason="supplier cancelled the order")
    line = [x for x in act.open_orders(who(demo_tenant, "viewer")) if x["action_id"] == a["id"]][0]
    assert (line["status"], line["open_units"]) == ("CANCELLED", 0) and _on_order(demo_tenant) == base


def test_P1_ACT_02_accept_remote_route_is_available_to_approvers(demo_tenant):
    r = _run(demo_tenant, budget_minor=18000)                   # a draft with a full evidence packet
    a = act.get(who(demo_tenant, "viewer"), r["state"]["actions"][0])
    sandbox_erp.inject_fault(f"po-{a['id']}", "duplicate_line")
    act.approve(who(demo_tenant, "approver"), a["id"], payload_hash=a["payload_hash"], expected_row_version=a["row_version"])
    assert act.dispatch_once(demo_tenant)["result"] == "MISMATCH"
    r = login("approver").post(f"/api/v1/actions/{a['id']}/accept-remote", json={"reason": "duplicate line accepted"},
                               headers=DEMO)
    assert r.status_code == 200 and r.json()["status"] == "RECONCILED"
    assert login("viewer").post(f"/api/v1/actions/{a['id']}/accept-remote", json={"reason": "x"},
                                headers=DEMO).status_code in (403, 409)


# =========================================================================================== P2-REL-01 / P2-REL-02 jobs
def test_P2_REL_01_a_job_that_died_on_its_last_attempt_fails_its_run_and_raises_an_alert(demo_tenant):
    run = create_run(who(demo_tenant, "planner"), mode="draft", inp={"sku_ids": ["DEMO-REF-SKU"]})
    with tenant_session(demo_tenant) as s:
        s.execute(text("""UPDATE jobs SET status='RUNNING', attempts=max_attempts, lease_owner='dead',
            lease_expires_at=now() - interval '1 minute' WHERE payload->>'run_id' = :r"""), {"r": str(run)})
        s.execute(text("UPDATE agent_runs SET status='RUNNING' WHERE id=:r"), {"r": run})
    assert jobs.claim(demo_tenant, "probe") is None
    with tenant_session(demo_tenant) as s:
        job = s.execute(text("SELECT status, error FROM jobs WHERE payload->>'run_id' = :r"), {"r": str(run)}).first()
        status = s.execute(text("SELECT status FROM agent_runs WHERE id=:r"), {"r": run}).scalar()
        alert = s.execute(text("SELECT kind, severity FROM alerts WHERE kind='job_failed'")).first()
    assert job.status == "FAILED" and "final attempt" in job.error and status == "FAILED"
    assert tuple(alert) == ("job_failed", "high")


def test_P2_REL_01_a_job_with_attempts_left_is_retried_not_failed(demo_tenant):
    run = create_run(who(demo_tenant, "planner"), mode="observe", inp={"sku_ids": ["DEMO-REF-SKU"]})
    with tenant_session(demo_tenant) as s:
        s.execute(text("""UPDATE jobs SET status='RUNNING', attempts=1, lease_owner='dead',
            lease_expires_at=now() - interval '1 minute' WHERE payload->>'run_id' = :r"""), {"r": str(run)})
    job = jobs.claim(demo_tenant, "probe")
    assert job is not None and job["attempts"] == 2


def test_P2_REL_02_the_database_refuses_a_second_draft_for_the_same_run_and_supplier(demo_tenant):
    r = _run(demo_tenant, budget_minor=18000)
    first = act.get(who(demo_tenant, "viewer"), r["state"]["actions"][0])
    res = applicable_terms(demo_tenant, ["DEMO-REF-SKU"], CUTOFF, EFF)
    line = plan(PlanRequest(decision_date=EFF, need_by=date(2026, 10, 22), currency="USD", budget_minor=18000,
                            needs=[Need(sku_id="DEMO-REF-SKU", required_units=30)], offers=res.applicable)).lines
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        act.prepare(who(demo_tenant, "planner"), supplier_id=first["payload"]["supplier_id"], lines=line, currency="USD",
                    need_by=date(2026, 10, 22), decision={"effective_date": EFF.isoformat()}, evidence={}, versions={},
                    agent_run_id=first["agent_run_id"])
