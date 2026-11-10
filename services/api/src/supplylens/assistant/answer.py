"""Answer a status question from this workspace's records, citing every record used (WP6; cite-or-withhold).

All reads run in the caller's tenant session, so row-level security decides what exists: another workspace's products,
orders and terms are never found, and a question about them reads exactly like a question about an id that does not
exist. Stock figures come from the same query as the Inventory screen (routes_core.INVENTORY_SQL) and the supplier terms
from the planner's own resolution (planning.terms_service.applicable_terms), so the assistant cannot disagree with them.

Statuses: "answered" (sentences, each with at least one citation), "withheld" (a reason, no sentences) and "choose"
(several products match: up to five choices; picking one re-asks with its code).
"""
from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from urllib.parse import quote

from sqlalchemy import text

from ..api.routes_core import INVENTORY_SQL
from ..authz import Actor
from ..db import tenant_session
from ..planning.terms_service import applicable_terms
from . import parse

MAX_CHOICES = 5
MAX_PRODUCTS = 3          # products answered in one reply; more named codes are listed but not answered
MAX_SENTENCES = 14

READ_ONLY = ("This assistant only reads records; it cannot order, approve, cancel or change anything. Use Approvals for "
             "drafts and orders, or Scenario studio to try a change.")
OUT_OF_SCOPE = ("This assistant answers questions about this workspace's products, stock, orders and supplier terms, from "
                "its records only. Ask about a product code (for example SYN001), a product name, an order number "
                "(SBX-PO-…) or an action id.")
NAME_SOMETHING = ("Name the product code, product name, order number (SBX-PO-…) or action id you are asking about; "
                  "the assistant answers only from records it can cite.")

STATUS_TEXT = {
    "PENDING_APPROVAL": "awaiting approval", "APPROVED": "approved, not yet queued", "QUEUED": "approved and queued to send",
    "SUBMITTED": "sent to the purchasing system, waiting for its confirmation",
    "CONFIRMED": "confirmed by the purchasing system, with a read-back difference to review",
    "RECONCILED": "confirmed by the purchasing system and matched line by line", "REJECTED": "rejected",
    "STALE": "returned to review because something it relied on changed",
    "UNKNOWN_OUTCOME": "outcome unknown: it must be reconciled before anything is resent", "FAILED": "failed",
}
IN_FLIGHT = ("PENDING_APPROVAL", "APPROVED", "QUEUED", "SUBMITTED", "UNKNOWN_OUTCOME", "CONFIRMED")
HEALTH_TEXT = {"shortage_risk": "shortage risk (under 7 days of cover)", "excess": "excess (over 90 days of cover)",
               "healthy": "healthy (7 to 90 days of cover)"}

STOCK_SQL = "SELECT q.* FROM (" + INVENTORY_SQL + ") q WHERE q.sku_id = ANY(:k) ORDER BY q.sku_id, q.location_id"  # noqa: S608


def ask(a: Actor, question: str) -> dict:
    a.require("read")
    q = " ".join(question.split())
    out = {"mode": "records", "question": q, "status": "withheld", "sentences": [], "reason": None, "reason_code": None,
           "choices": [], "choices_total": 0, "as_of": None, "generated": False}
    if parse.is_mutation(q):
        return _withhold(out, "read_only", READ_ONLY)
    if parse.is_unsafe(q):
        return _withhold(out, "out_of_scope", OUT_OF_SCOPE)

    with tenant_session(a.tenant_id) as s:
        as_of = _as_of(s)
        out["as_of"] = as_of.date()
        found = _resolve(s, q)
        if found["choose"]:
            return {**out, **found["choose"]}
        if not (found["products"] or found["actions"] or found["orders"]):
            return _withhold(out, *found["withhold"])
        facts = _facts(s, found, as_of.date())

    terms = None
    if found["products"] and (parse.wants_terms(q) or found["suppliers"]):
        res = applicable_terms(a.tenant_id, [p["sku_id"] for p in found["products"]], as_of, as_of.date())
        terms = {"applicable": res.applicable, "conflicts": res.conflicts}
    sentences = _compose(q, found, facts, terms, as_of.date())[:MAX_SENTENCES]
    if not sentences:                       # cannot happen with a found record, but never answer without a citation
        return _withhold(out, "no_match", NAME_SOMETHING)
    return {**out, "status": "answered", "sentences": sentences}


# ------------------------------------------------------------------------------------------ resolution
def _resolve(s, q: str) -> dict:
    """Which records the question names. Identifiers first; product words only when no identifier matched."""
    ids, pos, codes = parse.uuids(q), parse.po_numbers(q), parse.candidate_codes(q)
    actions = [dict(r) for r in s.execute(text(
        "SELECT * FROM actions WHERE id = ANY(CAST(:i AS uuid[])) ORDER BY created_at"), {"i": ids}).mappings()] if ids else []
    orders = []
    if pos:
        orders = [dict(r) for r in s.execute(text("""SELECT l.*, l.ordered_units - l.received_units - l.cancelled_units AS open_units
            FROM purchase_order_lines l WHERE upper(l.external_ref) = ANY(:p) ORDER BY l.external_ref, l.sku_id"""),
            {"p": pos}).mappings()]
        known = {o["external_ref"].upper() for o in orders}
        # submitted but not yet reconciled: the number is on the action, there are no ledger lines yet
        rest = [p for p in pos if p not in known]
        for r in (s.execute(text("SELECT * FROM actions WHERE upper(external_ref) = ANY(:p)"), {"p": rest}).mappings()
                  if rest else []):
            if r["id"] not in {x["id"] for x in actions}:
                actions.append(dict(r))
    products = []
    if codes:
        products = [dict(r) for r in s.execute(text("""SELECT sku_id, description, unit, source_kind FROM products
            WHERE upper(sku_id) = ANY(:k) ORDER BY sku_id"""), {"k": codes}).mappings()]
    matched = {p["sku_id"].upper() for p in products}
    for c in codes:                          # the first characters of an action id ("action 3f2a9c1b")
        if c not in matched and parse.HEX_PREFIX_RE.match(c):
            rows = s.execute(text("SELECT * FROM actions WHERE id::text LIKE :p LIMIT 2"), {"p": c.lower() + "%"}).mappings().all()
            if len(rows) == 1 and rows[0]["id"] not in {x["id"] for x in actions}:
                actions.append(dict(rows[0]))
                matched.add(c)
    suppliers, names = _suppliers(s, q, codes)
    unmatched = [c for c in codes if c not in matched and c not in {x["supplier_id"].upper() for x in suppliers}]
    unmatched += [p for p in pos if p not in {o["external_ref"].upper() for o in orders}
                  and p not in {(x.get("external_ref") or "").upper() for x in actions}]
    unmatched += [i for i in ids if i not in {str(x["id"]) for x in actions}]
    found = {"products": products, "actions": actions, "orders": orders, "suppliers": suppliers, "names": names,
             "choose": None, "withhold": None, "extra_codes": []}
    if products or actions or orders:
        found["extra_codes"] = [p["sku_id"] for p in products[MAX_PRODUCTS:]]
        found["products"] = products[:MAX_PRODUCTS]
        return found

    # no identifier matched: product words (descriptions), then a supplier without a product (KNOW-P7-01)
    drop = set(codes) | {w for x in suppliers for w in re.findall(r"[a-z0-9]+", f"{x['name']} {x['supplier_id']}".lower())}
    words = parse.content_words(q, drop)
    if parse.describes(words):
        hits, total = _describe(s, words, q)
        if len(hits) == 1:
            found["products"] = hits
            return found
        if hits:
            shown = ", ".join(words)
            found["choose"] = _choose(hits, total, f"{total} products match “{shown}”. Which one do you mean?")
            return found
    if suppliers:
        sup = suppliers[0]
        rows = s.execute(text("""SELECT p.sku_id, p.description, count(*) OVER () AS n FROM products p
            WHERE p.sku_id IN (SELECT sku_id FROM supplier_terms WHERE supplier_id = :s) ORDER BY p.sku_id LIMIT :l"""),
            {"s": sup["supplier_id"], "l": MAX_CHOICES}).mappings().all()
        if rows:
            found["choose"] = _choose([dict(r) for r in rows], rows[0]["n"],
                                      f"{sup['name']} ({sup['supplier_id']}) has different terms for each product it supplies "
                                      f"({rows[0]['n']} products). Which product do you mean?")
            return found
    if unmatched:
        found["withhold"] = ("unknown_id", "No product, order or action with the id " + ", ".join(unmatched[:3]) +
                             " exists in this workspace, so there is nothing to cite.")
    elif not parse.mentions_records(q):
        found["withhold"] = ("out_of_scope", OUT_OF_SCOPE)          # "what is the weather in Dubai?"
    elif parse.describes(words):
        found["withhold"] = ("no_match", f"No product in this workspace matches “{' '.join(words)}”. " + NAME_SOMETHING)
    else:
        found["withhold"] = ("no_match", NAME_SOMETHING)
    return found


def _suppliers(s, q: str, codes: list[str]) -> tuple[list[dict], dict[str, str]]:
    """Suppliers the question names (by id or full name), and every supplier's name for the sentences."""
    low = q.lower()
    out, names = [], {}
    for r in s.execute(text("SELECT supplier_id, name FROM suppliers ORDER BY supplier_id")).mappings():
        names[r["supplier_id"]] = r["name"]
        named = r["name"] and re.search(r"(?<![a-z0-9])" + re.escape(r["name"].lower()) + r"(?![a-z0-9])", low)
        if r["supplier_id"].upper() in codes or named:
            out.append(dict(r))
    return out, names


def _describe(s, words: list[str], q: str) -> tuple[list[dict], int]:
    """Products whose description holds the most question words (whole words), when that is most of them."""
    pats = [r"\m" + w + r"\M" for w in words]             # words are [a-z0-9]+ only: nothing to escape
    rows = s.execute(text("""SELECT sku_id, description, hits, count(*) OVER () AS n FROM (
            SELECT sku_id, description, hits, max(hits) OVER () AS best FROM (
                SELECT sku_id, description,
                       (SELECT count(*) FROM unnest(CAST(:p AS text[])) w WHERE description ~* w) AS hits
                FROM products WHERE description ~* ANY(CAST(:p AS text[]))) x) y
        WHERE hits = best
        ORDER BY sku_id LIMIT 50"""), {"p": pats}).mappings().all()
    if not rows or rows[0]["hits"] < max(1, -(-len(words) * 3 // 5)):     # at least 60 % of the words
        return [], 0
    hits = [{"sku_id": r["sku_id"], "description": r["description"]} for r in rows]
    low = q.lower()
    exact = [h for h in hits if h["description"]
             and re.search(r"(?<![a-z0-9])" + re.escape(h["description"].lower()) + r"(?![a-z0-9])", low)]
    if len(exact) == 1:
        return exact, 1
    return hits, rows[0]["n"]


def _choose(rows: list[dict], total: int, reason: str) -> dict:
    return {"status": "choose", "reason": reason, "reason_code": "ambiguous", "choices_total": int(total),
            "choices": [{"id": r["sku_id"], "label": f"{r['sku_id']} — {r['description']}" if r["description"] else r["sku_id"]}
                        for r in rows[:MAX_CHOICES]]}


def _withhold(out: dict, code: str, reason: str) -> dict:
    return {**out, "status": "withheld", "reason_code": code, "reason": reason}


def _as_of(s) -> datetime:
    v = s.execute(text("SELECT operational_as_of FROM tenant_settings")).scalar()
    return v or datetime.now(UTC)


# ------------------------------------------------------------------------------------------ facts
def _facts(s, found: dict, eff: date) -> dict:
    skus = [p["sku_id"] for p in found["products"]]
    facts: dict = {"stock": [], "open_lines": [], "drafts": [], "approvals": {}, "action_lines": {}}
    if skus:
        facts["stock"] = [dict(r) for r in s.execute(text(STOCK_SQL), {"eff": eff, "k": skus}).mappings()]
        facts["open_lines"] = [dict(r) for r in s.execute(text("""SELECT action_id, external_ref, supplier_id, sku_id,
            location_id, ordered_units - received_units - cancelled_units AS open_units, status, ordered_on, expected_on
            FROM purchase_order_lines WHERE sku_id = ANY(:k) AND status IN ('OPEN', 'PARTIAL')
              AND ordered_units - received_units - cancelled_units > 0
            ORDER BY sku_id, ordered_on DESC LIMIT 10"""), {"k": skus}).mappings()]
        for k in skus:
            facts["drafts"] += [dict(r, sku_id=k) for r in s.execute(text("""SELECT id, status, payload->>'supplier_id' AS supplier_id
                FROM actions WHERE status = ANY(:st) AND payload->'lines' @> CAST(:j AS jsonb)
                AND id NOT IN (SELECT action_id FROM purchase_order_lines) ORDER BY created_at DESC LIMIT 3"""),
                {"st": list(IN_FLIGHT), "j": json.dumps([{"sku_id": k}])}).mappings()]
    action_ids = [x["id"] for x in found["actions"]] + [o["action_id"] for o in found["orders"]]
    if action_ids:
        for r in s.execute(text("""SELECT action_id, decision, reason, expires_at, created_at FROM approvals
                WHERE action_id = ANY(:i) ORDER BY created_at"""), {"i": action_ids}).mappings():
            facts["approvals"][r["action_id"]] = dict(r)          # the latest decision wins
        for r in s.execute(text("""SELECT action_id, external_ref, sku_id, ordered_units, received_units, cancelled_units,
                ordered_units - received_units - cancelled_units AS open_units, status, expected_on
                FROM purchase_order_lines WHERE action_id = ANY(:i) ORDER BY sku_id"""), {"i": action_ids}).mappings():
            facts["action_lines"].setdefault(r["action_id"], []).append(dict(r))
        facts["order_actions"] = {r["id"]: dict(r) for r in s.execute(text(
            "SELECT id, status, payload, external_ref, created_at FROM actions WHERE id = ANY(:i)"), {"i": action_ids}).mappings()}
    return facts


# ------------------------------------------------------------------------------------------ sentences
def _cite(kind: str, id_: str, href: str) -> dict:
    return {"kind": kind, "id": id_, "href": href}


def _product_href(sku: str) -> str:
    return f"/inventory?sku={quote(sku, safe='')}"


def _action_href(action_id) -> str:
    return f"/approvals?action={action_id}"


def _units(unit: str | None) -> str:
    return "units" if not unit or unit == "unit" else unit


def _utc(v: datetime) -> str:
    return f"{v.astimezone(UTC):%Y-%m-%d %H:%M} UTC"


def _n(v) -> str:
    return f"{int(v):,}" if float(v).is_integer() else f"{float(v):,.1f}"


def _health(available: int, avg: float | None) -> tuple[float | None, str]:
    """Same rule as GET /api/v1/inventory (routes_core.inventory)."""
    if not avg:
        return None, "no_sales_data"
    cover = round(available / avg, 1)
    return cover, "shortage_risk" if cover < 7 else "excess" if cover > 90 else "healthy"


def _compose(q: str, found: dict, facts: dict, terms: dict | None, eff: date) -> list[dict]:
    out: list[dict] = []
    stock_wanted = parse.wants_stock(q) or not parse.wants_terms(q)
    for p in found["products"]:
        sku = p["sku_id"]
        pc = _cite("product", sku, _product_href(sku))
        name = f"{sku} ({p['description']})" if p["description"] else sku
        if stock_wanted:
            rows = [r for r in facts["stock"] if r["sku_id"] == sku]
            if not rows:
                out.append({"text": f"No stock position is recorded for {name} on or before {eff}.", "citations": [pc]})
            for r in rows[:3]:
                sc = _cite("stock", f"{sku}@{r['location_id']}/{r['as_of']}", _product_href(sku))
                kind = (r["value_kind"] or "").lower()
                note = f" These are {kind} stock figures, not a measured count." if kind and kind != "observed" else ""
                out.append({"text": f"{name} at {r['location_id']} on {r['as_of']}: {_n(r['available'])} {_units(p.get('unit'))} "
                                    f"available ({_n(r['on_hand'])} on hand, {_n(r['allocated'])} allocated), "
                                    f"{_n(r['on_order'])} on order in the stock record.{note}", "citations": [pc, sc]})
                cover, health = _health(r["available"], r["avg_daily"])
                if cover is None:
                    out.append({"text": f"No sales were recorded for {sku} at {r['location_id']} in the 28 days to {eff}, so "
                                        "days of cover cannot be worked out.", "citations": [sc]})
                else:
                    out.append({"text": f"That is {_n(cover)} days of cover at {_n(round(r['avg_daily'], 1))} units a day "
                                        f"(mean of the last 28 days): {HEALTH_TEXT[health]}.", "citations": [sc]})
            if len(rows) > 3:
                out.append({"text": f"{sku} is stocked at {len(rows)} locations; the Inventory screen lists all of them.",
                            "citations": [pc]})
            lines = [x for x in facts["open_lines"] if x["sku_id"] == sku]
            drafts = [x for x in facts["drafts"] if x["sku_id"] == sku]
            for x in lines[:3]:
                due = f", expected {x['expected_on']}" if x["expected_on"] else ""
                out.append({"text": f"Open order {x['external_ref']} from {x['supplier_id']}: {_n(x['open_units'])} units of {sku} "
                                    f"still to arrive{due} ({x['status'].lower()}).",
                            "citations": [_cite("order", x["external_ref"], _action_href(x["action_id"])), pc]})
            for d in drafts[:3]:
                out.append({"text": f"Purchase-order draft {str(d['id'])[:8]} for {sku} from {d['supplier_id']} is "
                                    f"{STATUS_TEXT.get(d['status'], d['status'].lower())}.",
                            "citations": [_cite("action", str(d["id"]), _action_href(d["id"])), pc]})
            if not lines and not drafts:
                out.append({"text": f"No open purchase order or draft in progress includes {sku}.", "citations": [pc]})
        if terms is not None:
            out += _terms_sentences(sku, pc, terms, found["suppliers"], found["names"], eff)
    if found["extra_codes"]:
        out.append({"text": "Ask separately about " + ", ".join(found["extra_codes"]) +
                            f": one reply covers at most {MAX_PRODUCTS} products.",
                    "citations": [_cite("product", c, _product_href(c)) for c in found["extra_codes"]]})
    for ref in _unique([o["external_ref"] for o in found["orders"]]):
        lines = [o for o in found["orders"] if o["external_ref"] == ref]
        out += _order_sentences(ref, lines, facts)
    for act in found["actions"]:
        out += _action_sentences(act, facts)
    return out


def _terms_sentences(sku: str, pc: dict, terms: dict, suppliers: list[dict], names: dict[str, str],
                     eff: date) -> list[dict]:
    wanted = {x["supplier_id"] for x in suppliers}
    rows = [t for t in terms["applicable"] if t.sku_id == sku and (not wanted or t.supplier_id in wanted)]
    in_conflict = {i for ids in terms["conflicts"] for i in ids}
    out = []
    for t in sorted(rows, key=lambda t: (t.supplier_id, t.term_id)):
        if t.term_id in in_conflict:
            continue
        who = f"{names[t.supplier_id]} ({t.supplier_id})" if names.get(t.supplier_id) else t.supplier_id
        kind = f" ({t.value_kind} terms)" if t.value_kind and t.value_kind != "observed" else ""
        out.append({"text": f"{who} terms for {sku} in force on {eff}{kind}: lead time {t.lead_time_days} days, minimum "
                            f"order {_n(t.moq)} units, pack size {_n(t.order_multiple)} units.",
                    "citations": [_cite("terms", t.term_id, _product_href(sku))]})
    for ids in terms["conflicts"]:
        hit = [t for t in terms["applicable"] if t.term_id in ids and t.sku_id == sku and (not wanted or t.supplier_id in wanted)]
        if hit:
            out.append({"text": f"Two terms from {hit[0].supplier_id} for {sku} are both in force ({', '.join(ids)}); they "
                                "conflict and need review before either is used.",
                        "citations": [_cite("terms", i, _product_href(sku)) for i in ids]})
    if not out:
        who = " from " + ", ".join(sorted(wanted)) if wanted else ""
        out.append({"text": f"No supplier terms{who} for {sku} are in force on {eff}.", "citations": [pc]})
    return out


def _order_sentences(ref: str, lines: list[dict], facts: dict) -> list[dict]:
    action_id = lines[0]["action_id"]
    oc = _cite("order", ref, _action_href(action_id))
    act = facts.get("order_actions", {}).get(action_id)
    out = [{"text": f"Order {ref} from {lines[0]['supplier_id']} has {len(lines)} line{'s' if len(lines) != 1 else ''}"
                    f" (ordered {lines[0]['ordered_on']}).", "citations": [oc]}]
    for x in lines[:5]:
        due = f", expected {x['expected_on']}" if x["expected_on"] else ""
        out.append({"text": f"{x['sku_id']}: {_n(x['ordered_units'])} ordered, {_n(x['received_units'])} received, "
                            f"{_n(x['cancelled_units'])} cancelled, {_n(x['open_units'])} still open{due} "
                            f"({x['status'].lower()}).", "citations": [oc, _cite("product", x["sku_id"], _product_href(x["sku_id"]))]})
    if act:
        out.append({"text": f"It was placed from purchase-order draft {str(action_id)[:8]}, now "
                            f"{STATUS_TEXT.get(act['status'], act['status'].lower())}.",
                    "citations": [_cite("action", str(action_id), _action_href(action_id))]})
    return out


def _action_sentences(act: dict, facts: dict) -> list[dict]:
    aid = str(act["id"])
    ac = _cite("action", aid, _action_href(aid))
    p = act["payload"] or {}
    out = [{"text": f"Purchase-order draft {aid[:8]} for supplier {p.get('supplier_id', 'unknown')} is "
                    f"{STATUS_TEXT.get(act['status'], act['status'].lower())} (status {act['status']}).", "citations": [ac]}]
    lines = p.get("lines") or []
    if lines:
        listed = "; ".join(f"{x['sku_id']}{'@' + x['location_id'] if x.get('location_id') else ''} {_n(x['quantity'])} "
                           f"{_units(x.get('unit'))}" for x in lines[:6])
        more = f" and {len(lines) - 6} more lines" if len(lines) > 6 else ""
        need = f", needed by {p['need_by']}" if p.get("need_by") else ""
        out.append({"text": f"Quantities: {listed}{more}{need}.", "citations": [ac]})
    ap = facts["approvals"].get(act["id"])
    if ap is None:
        out.append({"text": "No approval decision is recorded for it yet.", "citations": [ac]})
    elif ap["decision"] == "APPROVED":
        out.append({"text": f"Approved on {_utc(ap['created_at'])}; that approval is bound to this exact payload "
                            f"and expires {_utc(ap['expires_at'])}.", "citations": [ac]})
    else:
        why = f": {ap['reason']}" if ap.get("reason") else ""
        out.append({"text": f"{ap['decision'].capitalize()} on {_utc(ap['created_at'])}{why}.", "citations": [ac]})
    if act.get("external_ref"):
        lines_ = facts["action_lines"].get(act["id"], [])
        open_units = sum(x["open_units"] for x in lines_)
        tail = f"; {_n(open_units)} units are still open on it" if lines_ else "; it is not in the open-order ledger yet"
        out.append({"text": f"The purchasing system's order number is {act['external_ref']}{tail}.",
                    "citations": [_cite("order", act["external_ref"], _action_href(aid)), ac]})
    return out


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
