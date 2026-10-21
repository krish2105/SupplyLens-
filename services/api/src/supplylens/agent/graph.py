"""Deterministic procurement investigation agent (LangGraph state machine).

No generative model is used: every node calls typed, authorised tools (forecast, terms
resolution, retrieval, optimisation, validation, action preparation). After each node
the state is checkpointed to `agent_runs.state` and an observable event is appended to
`agent_events` (tenant-scoped by RLS). A restarted worker resumes at `next_node`.

Documents are treated as data. Retrieved text is quoted as evidence, never executed or
used to change scope, budget, permissions or destinations.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy import text

from supplylens_opt.planner import Need, PlanRequest, plan
from supplylens_opt.replenishment import Position, assess

from .. import alerts, telemetry
from ..actions import service as actions
from ..authz import Actor, resolve_actor
from ..db import tenant_session
from ..forecasting.service import run_forecast
from ..knowledge.retrieve import search
from ..planning.terms_service import applicable_terms

DEFAULT_BUDGET = {"max_tool_calls": 400, "max_seconds": 120, "max_check_loops": 1}
NODES = ["ACCEPT", "PLAN", "GATHER_EVIDENCE", "COMPUTE", "CHECK", "PREPARE_ACTION"]


class RunState(TypedDict, total=False):
    run_id: str
    tenant_id: str
    actor_id: str
    mode: str
    input: dict
    next_node: str
    status: str
    tool_calls: int
    started: float
    check_loops: int
    settings: dict
    skus: list[str]
    needs: dict
    forecast: dict
    terms: dict
    citations: dict
    upcoming_changes: list
    plan: dict
    checks: dict
    actions: list
    summary: str


class BudgetExceeded(Exception):
    pass


def _event(tenant_id, run_id, node, kind, summary, data=None):
    with tenant_session(tenant_id) as s:
        s.execute(text("INSERT INTO agent_events (tenant_id, run_id, node, kind, summary, data) "
                       "VALUES (:t,:r,:n,:k,:s,CAST(:d AS jsonb))"),
                  {"t": tenant_id, "r": run_id, "n": node, "k": kind, "s": summary,
                   "d": json.dumps(data or {}, default=str)})


def _checkpoint(state: RunState):
    persist = {k: v for k, v in state.items() if k not in ("tenant_id",)}
    with tenant_session(state["tenant_id"]) as s:
        s.execute(text("UPDATE agent_runs SET state=CAST(:s AS jsonb), status=:st, updated_at=now() WHERE id=:i"),
                  {"s": json.dumps(persist, default=str), "st": state.get("status", "RUNNING"),
                   "i": state["run_id"]})


def _tool(state: RunState, n: int = 1):
    state["tool_calls"] = state.get("tool_calls", 0) + n
    b = state["input"].get("budget", DEFAULT_BUDGET)
    if state["tool_calls"] > b["max_tool_calls"]:
        raise BudgetExceeded(f"tool-call budget {b['max_tool_calls']} exhausted")
    if time.time() - state["started"] > b["max_seconds"]:
        raise BudgetExceeded(f"time budget {b['max_seconds']}s exhausted")


def _actor(state: RunState) -> Actor:
    a = resolve_actor(uuid.UUID(state["actor_id"]), uuid.UUID(state["tenant_id"]))
    if a is None:
        raise PermissionError("actor no longer has a membership in this tenant")
    return a


def node(name: str, nxt):
    """Wrap a node: reauthorise, run, record an event, checkpoint, choose the next node."""
    def run(state: RunState) -> RunState:
        _actor(state).require("agent.start")
        with telemetry.span(f"agent.{name.lower()}", **{"agent.run_id": state["run_id"], "tenant.id": state["tenant_id"]}):
            summary, data = FUNCS[name](state)
        target = nxt(state) if callable(nxt) else nxt
        state["next_node"] = target
        _event(state["tenant_id"], state["run_id"], name, "node_completed", summary, data)
        _checkpoint(state)
        return state
    return run


# ----------------------------------------------------------------- node bodies

def accept(state):
    with tenant_session(state["tenant_id"]) as s:
        st = s.execute(text("SELECT operational_as_of, currency, dataset_id, planning FROM tenant_settings")).first()
    if st is None:
        raise ValueError("tenant has no operational settings; load data first")
    inp = state["input"]
    cutoff = datetime.fromisoformat(inp["knowledge_cutoff"]) if inp.get("knowledge_cutoff") else st.operational_as_of
    eff = date.fromisoformat(inp["effective_date"]) if inp.get("effective_date") else cutoff.date()
    state["settings"] = {"knowledge_cutoff": cutoff.isoformat(), "effective_date": eff.isoformat(),
                         "currency": inp.get("currency") or st.currency.strip(),
                         "dataset_id": str(st.dataset_id) if st.dataset_id else None,
                         "planning": st.planning,
                         "budget_minor": int(inp.get("budget_minor") or st.planning.get("weekly_budget_minor", 0))}
    return (f"Accepted {state['mode']} run as of {cutoff:%Y-%m-%d %H:%M} UTC, effective {eff}, "
            f"budget {state['settings']['budget_minor'] / 100:.2f} {state['settings']['currency']}",
            state["settings"])


def plan_steps(state):
    inp = state["input"]
    with tenant_session(state["tenant_id"]) as s:
        if inp.get("sku_ids"):
            skus = list(inp["sku_ids"])
        else:
            skus = [r.sku_id for r in s.execute(text(
                "SELECT DISTINCT sku_id FROM inventory_positions ORDER BY sku_id"))]
    state["skus"] = skus[:60]
    return (f"Investigate {len(state['skus'])} SKU(s): forecast or reorder rule, applicable terms, plan, checks",
            {"skus": state["skus"]})


def gather(state):
    st = state["settings"]
    cutoff = datetime.fromisoformat(st["knowledge_cutoff"])
    eff = date.fromisoformat(st["effective_date"])
    skus = state["skus"]
    _tool(state)
    with tenant_session(state["tenant_id"]) as s:
        rows = s.execute(text("""SELECT DISTINCT ON (sku_id) sku_id, on_hand, allocated, on_order, capacity, value_kind,
            as_of FROM inventory_positions WHERE sku_id = ANY(:k) AND as_of <= :e ORDER BY sku_id, as_of DESC"""),
            {"k": skus, "e": eff}).mappings().all()
    positions = {r["sku_id"]: dict(r) for r in rows}
    forecast = {"available": False}
    if st["dataset_id"]:
        _tool(state)
        fr = run_forecast(uuid.UUID(state["tenant_id"]), uuid.UUID(st["dataset_id"]), skus, cutoff.date(),
                          horizon=28, created_by=uuid.UUID(state["actor_id"]), allow_baseline_fallback=True)
        forecast = {"available": True, "run_id": str(fr.run_id), "model_version_id": str(fr.model_version_id),
                    "origin": fr.origin.isoformat(), "quality_flags": fr.quality_flags,
                    "points": {sku: [{"day": r.day.date().isoformat(), "q50": r.q50, "q90": r.q90}
                                     for r in g.itertuples()] for sku, g in fr.points.groupby("sku_id")}}
    _tool(state)
    res = applicable_terms(uuid.UUID(state["tenant_id"]), skus, cutoff, eff)
    # Upcoming policy changes: known now, effective later. Surfaced, not applied.
    future = applicable_terms(uuid.UUID(state["tenant_id"]), skus, cutoff, eff + timedelta(days=60))
    current_ids = {t.term_id for t in res.applicable}
    upcoming = [t.model_dump(mode="json") for t in future.applicable if t.term_id not in current_ids]
    citations = {}
    with tenant_session(state["tenant_id"]) as s:
        for t in res.applicable:
            if not t.document_version_id:
                continue
            _tool(state)
            c = s.execute(text("""SELECT c.id, c.section, c.body, c.char_start, c.char_end, dv.version_label,
                dv.valid_from, dv.known_at, dv.sha256, d.title FROM chunks c JOIN document_versions dv ON dv.id=c.version_id
                JOIN documents d ON d.id = dv.document_id WHERE c.version_id = :v AND c.section = :sec
                AND dv.known_at <= :cut ORDER BY c.ordinal LIMIT 1"""),
                {"v": t.document_version_id, "sec": t.section, "cut": cutoff}).mappings().first()
            if c:
                citations[t.term_id] = {**{k: str(v) if k == "id" else v for k, v in c.items()},
                                        "document_version_id": t.document_version_id}
    state["needs"] = {"positions": positions, "missing_positions": [k for k in skus if k not in positions]}
    state["forecast"] = forecast
    state["terms"] = {"applicable": [t.model_dump(mode="json") for t in res.applicable],
                      "ignored": [i.model_dump() for i in res.ignored], "conflicts": res.conflicts}
    state["citations"] = citations
    state["upcoming_changes"] = upcoming
    # Retrieval is also run once over the policy corpus so the evidence drawer can show related clauses.
    _tool(state)
    rel = search(uuid.UUID(state["tenant_id"]), "minimum order quantity lead time amendment supersedes",
                 as_of=cutoff, role=_actor(state).role, effective_date=eff, k=5)
    state["citations"]["_related"] = [{"title": e.title, "version": e.version_label, "section": e.section,
                                       "excerpt": e.excerpt[:400], "chunk_id": e.chunk_id} for e in rel["results"]]
    missing = state["needs"]["missing_positions"]
    return (f"Gathered {len(positions)} stock positions"
            f"{f' ({len(missing)} SKU(s) have no stock record at this date and are not assessed)' if missing else ''}, "
            f"{'forecast run ' + forecast['run_id'][:8] if forecast['available'] else 'no forecast (no sales history)'}, "
            f"{len(res.applicable)} applicable terms ({len(res.ignored)} excluded, {len(res.conflicts)} conflicts), "
            f"{len(upcoming)} upcoming policy changes",
            {"ignored": state["terms"]["ignored"][:20], "conflicts": res.conflicts, "upcoming": upcoming[:10],
             "retrieval_mode": rel["mode"], "missing_positions": missing})


def compute(state):
    st = state["settings"]
    eff = date.fromisoformat(st["effective_date"])
    planning = st["planning"]
    assessments = {}
    for sku, p in state["needs"]["positions"].items():
        if state["forecast"]["available"]:
            pts = [{"day": date.fromisoformat(x["day"]), "q50": x["q50"], "q90": x["q90"]}
                   for x in state["forecast"]["points"].get(sku, [])]
            if not pts:
                continue
            a = assess(Position(**{k: p[k] for k in ("on_hand", "allocated", "on_order", "capacity")}, sku_id=sku),
                       pts, eff, planning.get("coverage_days", 21), planning.get("safety_days", 5))
            assessments[sku] = a.model_dump(mode="json")
        else:
            # No sales history (demo): reorder-point rule from the fixture; required units only if below it.
            ref = planning.get("reference_case", {})
            if sku == ref.get("sku_id"):
                req = ref["required_units"]
                need_by = ref["need_by"]
            else:
                with tenant_session(state["tenant_id"]) as s:
                    rp = s.execute(text("SELECT capacity FROM inventory_positions WHERE sku_id=:k ORDER BY as_of DESC "
                                        "LIMIT 1"), {"k": sku}).scalar() or 0
                reorder_point = rp // 4
                avail = p["on_hand"] - p["allocated"] + p["on_order"]
                req = max(0, reorder_point - avail)
                need_by = (eff + timedelta(days=14)).isoformat()
            assessments[sku] = {"sku_id": sku, "required_units": req, "need_by": need_by,
                                "status": "reorder" if req else "healthy",
                                "method": "reorder point rule (synthetic fixture)"}
    to_buy = {k: v for k, v in assessments.items() if v["required_units"] > 0}
    state["needs"]["assessments"] = assessments
    if not to_buy:
        state["plan"] = {"status": "NO_ACTION", "lines": []}
        return "No SKU requires replenishment within the coverage window", {"assessed": len(assessments)}
    offers = [t for t in state["terms"]["applicable"] if t["sku_id"] in to_buy
              and t["currency"] == st["currency"]]
    # Offers must arrive within the coverage window; arrivals after a SKU's projected stockout
    # are allowed (late stock still serves later demand) but flagged as warnings below.
    window_end = eff + timedelta(days=planning.get("coverage_days", 21))
    if state["forecast"]["available"]:
        need_by = max([window_end] + [date.fromisoformat(v["need_by"]) for v in to_buy.values()])
    else:
        # Explicit fixture deadlines (reorder rule / reference case) are hard: late offers are infeasible.
        need_by = min(date.fromisoformat(v["need_by"]) for v in to_buy.values())
    req = PlanRequest(decision_date=eff, need_by=need_by, currency=st["currency"],
                      budget_minor=st["budget_minor"],
                      needs=[Need(sku_id=k, required_units=v["required_units"]) for k, v in to_buy.items()],
                      offers=offers, allow_shortfall=bool(state["input"].get("allow_shortfall", True)),
                      shortage_penalty_minor=int(state["input"].get("shortage_penalty_minor", 500)))
    _tool(state)
    result = plan(req)
    late = []
    for line in result.lines:
        stockout = to_buy[line.sku_id].get("projected_stockout")
        if stockout and line.arrival_date > date.fromisoformat(stockout):
            late.append({"sku_id": line.sku_id, "supplier_id": line.supplier_id,
                         "warning": f"arrives {line.arrival_date}, after projected stockout {stockout}"})
    state["plan"] = {**result.model_dump(mode="json"), "arrival_warnings": late,
                     "request": {"budget_minor": req.budget_minor, "currency": req.currency,
                                 "allow_shortfall": req.allow_shortfall,
                                 "shortage_penalty_minor": req.shortage_penalty_minor,
                                 "shortage_penalty_value_kind": "assumed",
                                 "needs": [n.model_dump() for n in req.needs]}}
    return (f"Planned {len(to_buy)} SKU need(s): {result.status}, {len(result.lines)} line(s), total "
            f"{result.total_minor / 100:.2f} {st['currency']}, shortfall {sum(result.shortfall.values())} units",
            {"status": result.status, "explanation": result.explanation, "input_hash": result.input_hash})


def check(state):
    p = state["plan"]
    issues = []
    if state["terms"]["conflicts"]:
        issues.append({"kind": "conflict", "detail": state["terms"]["conflicts"]})
    if p.get("status") in ("INFEASIBLE", "UNKNOWN", "MODEL_INVALID"):
        issues.append({"kind": "infeasible", "detail": p.get("explanation") or p.get("violations")})
    if p.get("violations"):
        issues.append({"kind": "validator", "detail": p["violations"]})
    missing = [l["term_id"] for l in p.get("lines", []) if l.get("document_version_id")
               and l["term_id"] not in state["citations"]]
    if missing:
        issues.append({"kind": "missing_citation", "detail": missing})
    state["checks"] = {"passed": not issues, "issues": issues,
                       "lines_checked": len(p.get("lines", [])),
                       "independent_validator": "passed" if not p.get("violations") else "failed"}
    max_loops = state["input"].get("budget", DEFAULT_BUDGET)["max_check_loops"]
    state["retry_gather"] = bool(missing) and state.get("check_loops", 0) < max_loops
    if state["retry_gather"]:
        state["check_loops"] = state.get("check_loops", 0) + 1
    return ("All checks passed" if not issues else
            "Checks raised: " + ", ".join(i["kind"] for i in issues)), state["checks"]


def prepare_action(state):
    p = state["plan"]
    st = state["settings"]
    actor = _actor(state)
    by_supplier: dict[str, list] = {}
    from supplylens_opt.planner import PlanLine
    for l in p["lines"]:
        by_supplier.setdefault(l["supplier_id"], []).append(PlanLine(**l))
    created = []
    with tenant_session(state["tenant_id"]) as s:
        existing = {r.payload["supplier_id"]: str(r.id) for r in s.execute(
            text("SELECT id, payload FROM actions WHERE agent_run_id = :r"), {"r": state["run_id"]})}
    for supplier, lines in sorted(by_supplier.items()):
        if supplier in existing:  # resumed run: never prepare the same draft twice
            created.append(existing[supplier])
            continue
        evidence = {
            "data_cutoff": st["knowledge_cutoff"], "effective_date": st["effective_date"],
            "forecast": {k: state["forecast"].get(k) for k in ("run_id", "model_version_id", "origin", "available")},
            "terms": [{**next(t for t in state["terms"]["applicable"] if t["term_id"] == l.term_id),
                       "citation": state["citations"].get(l.term_id)} for l in lines],
            "ignored_terms": [i for i in state["terms"]["ignored"]
                              if i["sku_id"] in {l.sku_id for l in lines}][:20],
            "upcoming_changes": [u for u in state["upcoming_changes"] if u["supplier_id"] == supplier],
            "needs": {l.sku_id: state["needs"]["assessments"].get(l.sku_id) for l in lines},
            "plan": {k: p.get(k) for k in ("status", "input_hash", "solver", "objective", "explanation")},
            "checks": state["checks"],
            "provenance": {"stock": "simulated" if state["forecast"]["available"] else "synthetic",
                           "terms": lines and next(t["value_kind"] for t in state["terms"]["applicable"]
                                                   if t["term_id"] == lines[0].term_id),
                           "budget": "assumed"},
        }
        decision = {"knowledge_cutoff": st["knowledge_cutoff"], "effective_date": st["effective_date"],
                    "plan_input_hash": p["input_hash"], "agent_run_id": state["run_id"]}
        a = actions.prepare(actor, supplier_id=supplier, lines=lines, currency=st["currency"],
                            need_by=max(l.arrival_date for l in lines), decision=decision, evidence=evidence,
                            versions={"forecast_run": state["forecast"].get("run_id"),
                                      "terms": [l.term_id for l in lines], "plan_input_hash": p["input_hash"]},
                            agent_run_id=uuid.UUID(state["run_id"]))
        created.append(str(a["id"]))
    state["actions"] = created
    state["status"] = "WAITING_FOR_APPROVAL"
    return f"Prepared {len(created)} purchase-order draft(s) for approval", {"action_ids": created}


FUNCS = {"ACCEPT": accept, "PLAN": plan_steps, "GATHER_EVIDENCE": gather, "COMPUTE": compute, "CHECK": check,
         "PREPARE_ACTION": prepare_action}


def _after_check(state: RunState) -> str:
    c = state["checks"]
    if c["passed"] and state["plan"].get("lines") and state["mode"] in ("draft", "execute"):
        return "PREPARE_ACTION"
    kinds = {i["kind"] for i in c["issues"]}
    if state.get("retry_gather") and kinds == {"missing_citation"}:
        return "GATHER_EVIDENCE"
    state["status"] = ("REVIEW_REQUIRED" if c["issues"] else "SUCCEEDED")
    return "END"


def build_graph():
    g = StateGraph(RunState)
    g.add_node("ACCEPT", node("ACCEPT", "PLAN"))
    g.add_node("PLAN", node("PLAN", "GATHER_EVIDENCE"))
    g.add_node("GATHER_EVIDENCE", node("GATHER_EVIDENCE", "COMPUTE"))
    g.add_node("COMPUTE", node("COMPUTE", "CHECK"))
    g.add_node("CHECK", node("CHECK", _after_check))
    g.add_node("PREPARE_ACTION", node("PREPARE_ACTION", "END"))
    g.set_conditional_entry_point(lambda s: s.get("next_node") or "ACCEPT",
                                  {n: n for n in NODES})
    for n in NODES:
        targets = {x: x for x in NODES}
        targets["END"] = END
        g.add_conditional_edges(n, lambda s: s["next_node"], targets)
    return g.compile()


GRAPH = build_graph()


def create_run(actor: Actor, *, mode: str, inp: dict) -> uuid.UUID:
    """Persist the run and its job in one transaction (HTTP 202 path)."""
    actor.require("agent.start")
    if mode not in ("observe", "recommend", "draft"):
        raise ValueError("mode must be observe, recommend or draft (execute is gated by approvals)")
    run_id, job_id = uuid.uuid4(), uuid.uuid4()
    budget = {**DEFAULT_BUDGET, **(inp.get("budget") or {})}
    inp = {**inp, "budget": budget}
    with tenant_session(actor.tenant_id) as s:
        s.execute(text("INSERT INTO agent_runs (id, tenant_id, status, mode, input, budget, created_by) "
                       "VALUES (:i,:t,'QUEUED',:m,CAST(:inp AS jsonb),CAST(:b AS jsonb),:u)"),
                  {"i": run_id, "t": actor.tenant_id, "m": mode, "inp": json.dumps(inp), "b": json.dumps(budget),
                   "u": actor.user_id})
        s.execute(text("INSERT INTO jobs (id, tenant_id, kind, payload, status, created_by) VALUES "
                       "(:i,:t,'agent_run',CAST(:p AS jsonb),'QUEUED',:u)"),
                  {"i": job_id, "t": actor.tenant_id,
                   "p": json.dumps({"run_id": str(run_id), "trace": telemetry.inject_context()}), "u": actor.user_id})
    return run_id


def execute_run(tenant_id, run_id) -> dict[str, Any]:
    with tenant_session(tenant_id) as s:
        r = s.execute(text("SELECT * FROM agent_runs WHERE id=:i"), {"i": run_id}).mappings().first()
    if r is None:
        raise LookupError("run not found")
    if r["status"] in ("SUCCEEDED", "FAILED", "CANCELLED", "REVIEW_REQUIRED", "WAITING_FOR_APPROVAL", "COMPLETE"):
        return {"status": r["status"]}
    state: RunState = {**r["state"], "run_id": str(run_id), "tenant_id": str(tenant_id),
                       "actor_id": str(r["created_by"]), "mode": r["mode"], "input": r["input"],
                       "status": "RUNNING", "started": time.time()}
    state.setdefault("tool_calls", 0)
    resumed = bool(r["state"].get("next_node"))
    _event(tenant_id, run_id, state.get("next_node") or "ACCEPT", "run_resumed" if resumed else "run_started",
           "Resumed from checkpoint" if resumed else "Run started")
    try:
        final = GRAPH.invoke(state, {"recursion_limit": 25})
    except BudgetExceeded as e:
        state["status"] = "PARTIAL"
        _event(tenant_id, run_id, state.get("next_node", "?"), "budget_exceeded", str(e))
        _checkpoint(state)
        alerts.raise_alert(tenant_id, "budget_exhausted", f"budget_exhausted:run:{run_id}",
                           "Investigation stopped: run budget exhausted",
                           {"run_id": str(run_id), "reason": str(e), "tool_calls": state.get("tool_calls")}, "medium")
        return {"status": "PARTIAL"}
    except Exception as e:  # recorded, not hidden
        state["status"] = "FAILED"
        _event(tenant_id, run_id, state.get("next_node", "?"), "failed", f"{type(e).__name__}: {e}")
        _checkpoint(state)
        return {"status": "FAILED", "error": str(e)}
    if final.get("status") == "RUNNING":
        final["status"] = "SUCCEEDED"
    _event(tenant_id, run_id, "END", "run_finished", f"Run finished: {final['status']}")
    _checkpoint(final)
    return {"status": final["status"], "actions": final.get("actions", [])}
