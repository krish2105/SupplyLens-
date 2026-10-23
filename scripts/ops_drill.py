"""Helper for the operational drills (scripts/outage_drill.sh, scripts/recovery_drill.sh). Never run it against a real
database: the drills point SUPPLYLENS_*_DATABASE_URL at a scratch cluster they create and delete.

  setup            seed the control plane and load the Demo workspace
  approve N        prepare and approve N purchase-order drafts through the services (dispatch is left to a worker)
  state            JSON: actions by status, sandbox orders, duplicate keys, heartbeat errors
  write-loop S LOG commit one row every 0.2 s for S seconds; append "<id> <unix time>" to LOG after each commit
  written          JSON: max id and row count in the write-loop table
"""
from __future__ import annotations

import json
import sys
import time
from datetime import UTC, date, datetime

from sqlalchemy import text

from supplylens.actions import service as act
from supplylens.authz import resolve_actor
from supplylens.db import admin_engine, tenant_session
from supplylens.planning.terms_service import applicable_terms
from supplylens.seed import dev_email, seed, tenant_id, user_id
from supplylens.simulation import demo
from supplylens_opt.planner import Need, PlanRequest, plan

CUTOFF = datetime(2026, 10, 20, 9, tzinfo=UTC)


def setup() -> None:
    seed()
    demo.load(tenant_id("demo"))


def approve(n: int) -> list[str]:
    t = tenant_id("demo")
    planner = resolve_actor(user_id(dev_email("planner")), t)
    approver = resolve_actor(user_id(dev_email("approver")), t)
    out = []
    for _ in range(n):
        eff = date(2026, 10, 20)
        res = applicable_terms(t, ["DEMO-REF-SKU"], CUTOFF, eff)
        req = PlanRequest(decision_date=eff, need_by=date(2026, 10, 22), currency="USD", budget_minor=18000,
                          needs=[Need(sku_id="DEMO-REF-SKU", required_units=30)], offers=res.applicable)
        r = plan(req)
        a = act.prepare(planner, supplier_id=r.lines[0].supplier_id, lines=r.lines, currency="USD", need_by=req.need_by,
                        decision={"knowledge_cutoff": CUTOFF.isoformat(), "effective_date": eff.isoformat(),
                                  "plan_input_hash": r.input_hash},
                        evidence={"terms": [x.term_id for x in r.lines]}, versions={"plan": r.input_hash})
        act.approve(approver, a["id"], payload_hash=a["payload_hash"], expected_row_version=a["row_version"])
        out.append(str(a["id"]))
    return out


def state() -> dict:
    t = tenant_id("demo")
    with tenant_session(t) as s:
        by = {r.status: r.n for r in s.execute(text("SELECT status, count(*) n FROM actions GROUP BY status"))}
        refs = [str(r.id) for r in s.execute(text("SELECT id FROM actions"))]
    with admin_engine().connect() as c:
        orders = c.execute(text("SELECT count(*) n, count(DISTINCT idempotency_key) k FROM sandbox_erp.purchase_orders "
                                "WHERE caller_ref = ANY(:r)"), {"r": refs}).one()
        hb = c.execute(text("SELECT count(*) FILTER (WHERE last_error IS NOT NULL) e, count(*) n, max(last_tick_at) last "
                            "FROM worker_heartbeats")).one()
    return {"actions": by, "sandbox_orders": orders.n, "distinct_keys": orders.k,
            "workers_seen": hb.n, "workers_with_errors": hb.e, "last_tick": str(hb.last)}


def write_loop(seconds: float, log_path: str) -> None:
    with admin_engine().begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS drill_writes (id bigserial PRIMARY KEY, at timestamptz DEFAULT now())"))
    end = time.time() + seconds
    with open(log_path, "a", buffering=1) as log:
        while time.time() < end:
            try:
                with admin_engine().begin() as c:
                    i = c.execute(text("INSERT INTO drill_writes DEFAULT VALUES RETURNING id")).scalar()
                log.write(f"{i} {time.time():.3f}\n")           # acknowledged: the commit returned
            except Exception as e:                             # the database is gone: stop, the drill measures the loss
                log.write(f"# stopped: {type(e).__name__}\n")
                return
            time.sleep(0.2)


def written() -> dict:
    with admin_engine().connect() as c:
        r = c.execute(text("SELECT coalesce(max(id), 0) m, count(*) n FROM drill_writes")).one()
    return {"max_id": r.m, "rows": r.n}


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    if cmd == "setup":
        setup()
    elif cmd == "approve":
        print(json.dumps(approve(int(args[0]))))
    elif cmd == "state":
        print(json.dumps(state()))
    elif cmd == "write-loop":
        write_loop(float(args[0]), args[1])
    elif cmd == "written":
        print(json.dumps(written()))
    else:
        raise SystemExit(__doc__)
