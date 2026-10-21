"""AGT-01 / AGT-02 agent evaluation on frozen business scenarios (runs against supplylens_test).

Expected outcomes come from an independent brute-force oracle over the reference-case ground
truth (not from CP-SAT or the terms resolver). Each scenario runs 3 times; the investigator is
deterministic, so variation should be zero, and that is reported rather than assumed.

uv run python evaluations/agent_study.py
"""
from __future__ import annotations

import os

os.environ["SUPPLYLENS_DATABASE_URL"] = "postgresql+psycopg://supplylens_app:supplylens_app_dev@localhost:5432/supplylens_test"
os.environ["SUPPLYLENS_ADMIN_DATABASE_URL"] = "postgresql+psycopg://supplylens_owner:supplylens_owner_dev@localhost:5432/supplylens_test"
os.environ["SUPPLYLENS_STORAGE_DIR"] = "storage_test"

import json  # noqa: E402
import statistics  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from datetime import date, datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import text  # noqa: E402

from supplylens.actions import service as act  # noqa: E402
from supplylens.agent.graph import create_run, execute_run  # noqa: E402
from supplylens.authz import Forbidden, resolve_actor  # noqa: E402
from supplylens.db import admin_engine, tenant_session  # noqa: E402
from supplylens.integrations import sandbox_erp  # noqa: E402
from supplylens.seed import dev_email, seed, tenant_id, user_id  # noqa: E402
from supplylens.simulation import demo  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
T = tenant_id("demo")
NEED, BY = 30, date(2026, 10, 22)
# Ground truth of the fictional reference case, written independently of the database records.
TRUTH = {
    "DEMO-REF-A": [  # (valid_from, known_at, moq, multiple, unit_cost_minor, lead_days)
        (date(2026, 1, 1), date(2026, 1, 1), 20, 10, 500, 2),
        (date(2026, 10, 20), date(2026, 10, 15), 40, 10, 500, 2),
    ],
    "DEMO-REF-B": [(date(2026, 1, 1), date(2026, 1, 1), 10, 5, 600, 2)],
}


def oracle(eff: date, cutoff: date, budget: int):
    """Cheapest single-supplier order covering NEED by BY, enumerating quantities directly."""
    best = None
    for sup, versions in TRUTH.items():
        live = [v for v in versions if v[1] <= cutoff and v[0] <= eff]
        if not live:
            continue
        _, _, moq, mult, cost, lead = max(live, key=lambda v: v[0])
        if eff + timedelta(days=lead) > BY:
            continue
        for q in range(NEED, 1000):
            if q >= moq and q % mult == 0:
                total = q * cost
                cand = (total, q, sup)
                if total <= budget and (best is None or cand < best):
                    best = cand
                break
    return None if best is None else {"supplier": best[2], "quantity": best[1], "total_minor": best[0]}


def reset():
    seed()
    with admin_engine().begin() as c:
        tables = c.execute(text("select string_agg(quote_ident(tablename), ', ') from pg_tables where schemaname='public' "
                                "and tablename not in ('alembic_version','tenants','users','memberships')")).scalar()
        c.execute(text(f"TRUNCATE {tables}, sandbox_erp.purchase_orders, sandbox_erp.fault_injection CASCADE"))
    demo.load(T)


def actor(role):
    return resolve_actor(user_id(dev_email(role)), T)


def run_reference(eff: date, cutoff: datetime, budget: int):
    t0 = time.perf_counter()
    rid = create_run(actor("planner"), mode="draft", inp={"sku_ids": ["DEMO-REF-SKU"], "knowledge_cutoff": cutoff.isoformat(),
                                                          "effective_date": eff.isoformat(), "currency": "USD",
                                                          "budget_minor": budget, "allow_shortfall": False})
    res = execute_run(T, rid)
    with tenant_session(T) as s:
        acts = s.execute(text("SELECT id, payload FROM actions WHERE agent_run_id=:r"), {"r": rid}).mappings().all()
        tools = s.execute(text("SELECT state->>'tool_calls' FROM agent_runs WHERE id=:r"), {"r": rid}).scalar()
    got = None
    if acts:
        p = acts[0]["payload"]
        got = {"supplier": p["supplier_id"], "quantity": p["lines"][0]["quantity"], "total_minor": p["total_minor"]}
    return res["status"], got, (time.perf_counter() - t0) * 1000, int(tools or 0), [a["id"] for a in acts]


def unapproved_orders() -> int:
    """External mutations without an approval of the same operation (must stay zero).

    Approvals are tenant data under forced RLS, so they are read inside the tenant context;
    sandbox orders are matched to actions by their idempotency key (po-<action id>).
    """
    with tenant_session(T) as s:
        approved = {f"po-{r.action_id}" for r in s.execute(text("SELECT action_id FROM approvals WHERE decision='APPROVED'"))}
    with admin_engine().connect() as c:
        keys = [r.idempotency_key for r in c.execute(text("SELECT idempotency_key FROM sandbox_erp.purchase_orders"))]
    return sum(k not in approved for k in keys)


def scenarios():
    out = []
    for budget in (14000, 15000, 18000, 20000):
        for d in range(14, 25):
            eff = date(2026, 10, d)
            out.append({"id": f"ref-b{budget}-d{d}", "kind": "reference", "eff": eff,
                        "cutoff": datetime(2026, 10, d, 9, tzinfo=timezone.utc), "budget": budget})
    for d in (20, 21):  # delayed knowledge: amendment not yet known at the cutoff
        out.append({"id": f"delayed-knowledge-d{d}", "kind": "reference", "eff": date(2026, 10, 20),
                    "cutoff": datetime(2026, 10, 14, 9, tzinfo=timezone.utc), "budget": 18000})
    out += [{"id": "missing-stock-record", "kind": "missing_stock"}, {"id": "conflicting-terms", "kind": "conflict"},
            {"id": "viewer-denied", "kind": "denied", "role": "viewer"}, {"id": "approver-cannot-start", "kind": "denied", "role": "approver"},
            {"id": "admin-cannot-approve", "kind": "admin_approve"}, {"id": "self-approval-blocked", "kind": "self_approve"},
            {"id": "stale-terms-before-approval", "kind": "stale"}, {"id": "timeout-after-commit", "kind": "timeout"},
            {"id": "fail-before-commit-retry", "kind": "retry"}, {"id": "resume-after-crash", "kind": "resume"},
            {"id": "approved-happy-path", "kind": "happy"}]
    return out


def check(sc) -> tuple[bool, dict]:
    k = sc["kind"]
    if k == "reference":
        exp = oracle(sc["eff"], sc["cutoff"].date(), sc["budget"])
        status, got, ms, tools, _ = run_reference(sc["eff"], sc["cutoff"], sc["budget"])
        ok = (got == exp) and (status == "WAITING_FOR_APPROVAL" if exp else status in ("REVIEW_REQUIRED", "SUCCEEDED"))
        return ok, {"expected": exp, "got": got, "status": status, "ms": ms, "tool_calls": tools}
    if k == "missing_stock":
        status, got, ms, tools, _ = run_reference(date(2026, 9, 15), datetime(2026, 9, 15, 9, tzinfo=timezone.utc), 18000)
        return got is None and status in ("SUCCEEDED", "REVIEW_REQUIRED"), {"status": status, "ms": ms, "tool_calls": tools}
    if k == "conflict":
        with tenant_session(T) as s:
            s.execute(text("""INSERT INTO supplier_terms (term_id, tenant_id, supplier_id, sku_id, unit_cost_minor, currency, moq,
                order_multiple, lead_time_days, valid_from, known_at, value_kind, source_kind) VALUES ('REF-A-side', :t, 'DEMO-REF-A',
                'DEMO-REF-SKU', 450, 'USD', 50, 10, 2, '2026-06-01', '2026-06-01', 'synthetic', 'generated')"""), {"t": T})
        status, got, ms, tools, _ = run_reference(date(2026, 10, 19), datetime(2026, 10, 19, 9, tzinfo=timezone.utc), 18000)
        return status == "REVIEW_REQUIRED" and got is None, {"status": status, "ms": ms, "tool_calls": tools}
    if k == "denied":
        try:
            create_run(actor(sc["role"]), mode="draft", inp={})
            return False, {"error": "allowed"}
        except Forbidden:
            return True, {"denied": True}
    _, _, _, _, ids = run_reference(date(2026, 10, 20), datetime(2026, 10, 20, 9, tzinfo=timezone.utc), 18000)
    a = act.get(actor("viewer"), ids[0])
    approve = lambda who: act.approve(actor(who), a["id"], payload_hash=a["payload_hash"], expected_row_version=a["row_version"])  # noqa: E731
    key = f"po-{a['id']}"
    if k == "admin_approve":
        try:
            approve("tenant_admin")
            return False, {}
        except Forbidden:
            return sandbox_erp.lookup(key) is None, {"denied": True}
    if k == "self_approve":
        p = actor("planner")
        try:
            act.approve(type(p)(p.user_id, p.tenant_id, "approver", p.email), a["id"], payload_hash=a["payload_hash"],
                        expected_row_version=a["row_version"])
            return False, {}
        except act.ActionError as e:
            return e.code == "separation_of_duties", {"code": e.code}
    if k == "stale":
        with tenant_session(T) as s:
            s.execute(text("""INSERT INTO supplier_terms (term_id, tenant_id, supplier_id, sku_id, unit_cost_minor, currency, moq,
                order_multiple, lead_time_days, valid_from, known_at, value_kind, source_kind, supersedes_term_id) VALUES
                ('REF-B-v2', :t, 'DEMO-REF-B', 'DEMO-REF-SKU', 650, 'USD', 10, 5, 2, '2026-10-01', now(), 'synthetic', 'generated',
                'REF-B-v1')"""), {"t": T})
        r = approve("approver")
        return r["status"] == "STALE" and sandbox_erp.lookup(key) is None, r
    approve("approver")
    if k == "timeout":
        sandbox_erp.inject_fault(key, "timeout_after_commit")
        first = act.dispatch_once(T)["result"]
        idle = act.dispatch_once(T)
        rec = act.reconcile(actor("approver"), a["id"])["result"]
        n = sandbox_erp.count_for_key(key)
        return first == "UNKNOWN_OUTCOME" and idle is None and rec == "RECONCILED" and n == 1, {"orders": n}
    if k == "retry":
        sandbox_erp.inject_fault(key, "fail_before_commit")
        r1 = act.dispatch_once(T)["result"]
        with tenant_session(T) as s:
            s.execute(text("UPDATE outbox SET next_attempt_at = now()"))
        r2 = act.dispatch_once(T)["result"]
        return r1 == "RETRY" and r2 == "RECONCILED" and sandbox_erp.count_for_key(key) == 1, {"r1": r1, "r2": r2}
    if k == "resume":
        item = act._claim(T, "dies")
        sandbox_erp.execute(key, "x", item["payload"])
        with tenant_session(T) as s:
            s.execute(text("UPDATE outbox SET lease_expires_at = now() - interval '1 second'"))
        r = act.dispatch_once(T, worker="recovery")["result"]
        return r == "RECONCILED" and sandbox_erp.count_for_key(key) == 1, {"result": r}
    if k == "happy":
        r = act.dispatch_once(T)["result"]
        o = sandbox_erp.lookup(key)
        return r == "RECONCILED" and o["supplier_id"] == "DEMO-REF-B" and o["lines"][0]["quantity"] == 30, {"po": o["po_number"]}
    raise ValueError(k)


def main():
    scs = scenarios()
    results = []
    for sc in scs:
        trials = []
        for _ in range(3):
            reset()
            ok, detail = check(sc)
            trials.append({"ok": ok, **{k: v for k, v in detail.items() if k in ("ms", "tool_calls", "status")}})
            unauth = unapproved_orders()
            if unauth:
                trials[-1]["unauthorized_external_mutations"] = unauth
        results.append({"id": sc["id"], "kind": sc["kind"], "passes": sum(t["ok"] for t in trials), "trials": trials,
                        "detail": json.loads(json.dumps(detail, default=str))})
        print(f"{sc['id']:32} {'PASS' if all(t['ok'] for t in trials) else 'FAIL'} {json.dumps(detail, default=str)[:140]}", flush=True)
    ms = [t["ms"] for r in results for t in r["trials"] if "ms" in t]
    tools = [t["tool_calls"] for r in results for t in r["trials"] if "tool_calls" in t]
    summary = {"scenarios": len(results), "trials_per_scenario": 3,
               "verified_completion_rate": sum(r["passes"] for r in results) / (3 * len(results)),
               "scenarios_all_trials_pass": sum(r["passes"] == 3 for r in results),
               "unauthorized_external_mutations": sum(t.get("unauthorized_external_mutations", 0) for r in results for t in r["trials"]),
               "run_ms_p50": statistics.median(ms) if ms else None, "run_ms_max": max(ms) if ms else None,
               "tool_calls_mean": statistics.mean(tools) if tools else None, "llm_tokens": 0,
               "variation": "identical outcomes across trials" if all(r["passes"] in (0, 3) for r in results) else "outcomes varied"}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip()
    d = REPO / "artifacts" / "experiments" / f"AGT-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "metrics.json").write_text(json.dumps({"experiment_id": d.name, "study": "AGT", "commit": commit, "summary": summary,
                                                "oracle": "brute-force enumeration over hand-written ground truth", "results": results},
                                               indent=2, default=str))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
