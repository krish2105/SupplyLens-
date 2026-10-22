"""Import batches through their lifecycle, workspace creation and membership administration (audit S18)."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from ..authz import Actor
from ..db import control_session, tenant_session
from . import csv_import as ci


class OnboardingError(Exception):
    def __init__(self, code: str, message: str, http: int = 422):
        super().__init__(message)
        self.code, self.http = code, http


def _audit(s, actor: Actor, action: str, entity_id, detail: dict) -> None:
    s.execute(text("INSERT INTO audit_events (tenant_id, actor_id, action, entity, entity_id, detail) "
                   "VALUES (:t,:a,:ac,'import_batch',:e,CAST(:d AS jsonb))"),
              {"t": actor.tenant_id, "a": actor.user_id, "ac": action, "e": str(entity_id),
               "d": json.dumps(detail, default=str)})


# ------------------------------------------------------------------------------------------ workspaces and members
def create_workspace(actor: Actor, *, slug: str, name: str, currency: str, weekly_budget_minor: int,
                     coverage_days: int) -> dict:
    """A tenant administrator creates an empty customer workspace and becomes its administrator. Nothing operational
    is seeded: stock, sales and terms arrive only through published imports."""
    actor.require("admin.write")
    wid = uuid.uuid4()
    try:
        with control_session() as s:
            s.execute(text("SELECT sl_create_workspace(:i, :s, :n, :u)"), {"i": wid, "s": slug, "n": name, "u": actor.user_id})
    except Exception as e:
        msg = str(getattr(e, "orig", e)).split("\n")[0]
        if "tenants_slug_key" in msg:
            raise OnboardingError("slug_taken", "a workspace with that address already exists", 409) from e
        raise OnboardingError("workspace_refused", msg) from e
    with tenant_session(wid) as s:
        s.execute(text("""INSERT INTO tenant_settings (tenant_id, operational_as_of, currency, planning)
            VALUES (:t, now(), :c, CAST(:p AS jsonb))"""),
            {"t": wid, "c": currency, "p": json.dumps({"weekly_budget_minor": weekly_budget_minor,
                                                       "coverage_days": coverage_days, "service_level": 0.9})})
        s.execute(text("INSERT INTO audit_events (tenant_id, actor_id, action, entity, entity_id, detail) VALUES "
                       "(:t,:a,'workspace.created','tenant',:e,CAST(:d AS jsonb))"),
                  {"t": wid, "a": actor.user_id, "e": str(wid),
                   "d": json.dumps({"slug": slug, "created_from": str(actor.tenant_id)})})
    return {"tenant_id": str(wid), "slug": slug, "name": name}


def set_membership(actor: Actor, *, email: str, role: str | None) -> dict:
    actor.require("admin.write")
    try:
        with tenant_session(actor.tenant_id) as s:
            out = s.execute(text("SELECT sl_set_membership(:t, :a, :e, :r)"),
                            {"t": actor.tenant_id, "a": actor.user_id, "e": email, "r": role}).scalar()
            s.execute(text("INSERT INTO audit_events (tenant_id, actor_id, action, entity, entity_id, detail) VALUES "
                           "(:t,:a,'membership.changed','user',:e,CAST(:d AS jsonb))"),
                      {"t": actor.tenant_id, "a": actor.user_id, "e": email, "d": json.dumps({"role": role})})
    except Exception as e:
        raise OnboardingError("membership_refused", str(getattr(e, "orig", e)).split("\n")[0], 409) from e
    return {"email": email, "result": out}


# ------------------------------------------------------------------------------------------ import batches
def upload(actor: Actor, *, kind: str, file_name: str, data: bytes, rights: str) -> dict:
    actor.require("admin.write")
    if kind not in ci.TEMPLATES:
        raise OnboardingError("unknown_kind", "kind must be sales, stock, terms or receipts")
    if len(rights.strip()) < 5:
        raise OnboardingError("rights_required", "state the rights basis for this file (for example 'our own ERP export')")
    try:
        header, rows = ci.parse(data)
    except ci.ImportError_ as e:
        raise OnboardingError(e.code, str(e)) from e
    sha = hashlib.sha256(data).hexdigest()
    bid = uuid.uuid4()
    mapping = ci.suggest_mapping(kind, header)
    with tenant_session(actor.tenant_id) as s:
        dup = s.execute(text("SELECT id, status FROM import_batches WHERE kind=:k AND sha256=:h"),
                        {"k": kind, "h": sha}).first()
        if dup:
            raise OnboardingError("duplicate_file", f"this exact file was already uploaded (batch {dup.id}, {dup.status})", 409)
        s.execute(text("""INSERT INTO import_batches (id, tenant_id, kind, status, file_name, sha256, bytes, header, mapping,
            report, rows_total, created_by) VALUES (:i,:t,:k,'UPLOADED',:f,:h,:b,:hd,CAST(:m AS jsonb),CAST(:r AS jsonb),:n,:u)"""),
            {"i": bid, "t": actor.tenant_id, "k": kind, "f": file_name[:200], "h": sha, "b": len(data), "hd": header,
             "m": json.dumps(mapping), "r": json.dumps({"rights": rights.strip()[:300]}), "n": len(rows), "u": actor.user_id})
        s.execute(text("""INSERT INTO import_rows (tenant_id, batch_id, row_no, raw)
            SELECT :t, :b, (x->>'n')::int, x->'r' FROM jsonb_array_elements(CAST(:rows AS jsonb)) x"""),
            {"t": actor.tenant_id, "b": bid, "rows": json.dumps([{"n": i + 2, "r": r} for i, r in enumerate(rows)])})
        _audit(s, actor, "import.uploaded", bid, {"kind": kind, "file": file_name, "sha256": sha, "rows": len(rows)})
    return get(actor, bid)


def get(actor: Actor, batch_id) -> dict:
    actor.require("read")
    with tenant_session(actor.tenant_id) as s:
        b = s.execute(text("SELECT * FROM import_batches WHERE id=:i"), {"i": batch_id}).mappings().first()
        if not b:
            raise OnboardingError("not_found", "import batch not found", 404)
        bad = s.execute(text("""SELECT row_no, raw, errors FROM import_rows WHERE batch_id=:i AND cardinality(errors) > 0
            ORDER BY row_no LIMIT 50"""), {"i": batch_id}).mappings().all()
        sample = s.execute(text("SELECT row_no, raw FROM import_rows WHERE batch_id=:i ORDER BY row_no LIMIT 5"),
                           {"i": batch_id}).mappings().all()
    return {**dict(b), "columns": [c.__dict__ for c in ci.TEMPLATES[b["kind"]]],
            "quarantined_sample": [dict(r) for r in bad], "preview": [dict(r) for r in sample]}


def list_batches(actor: Actor) -> list[dict]:
    actor.require("read")
    with tenant_session(actor.tenant_id) as s:
        rows = s.execute(text("""SELECT id, kind, status, file_name, sha256, rows_total, rows_valid, rows_quarantined,
            snapshot_sha256, created_at, published_at FROM import_batches ORDER BY created_at DESC LIMIT 100""")).mappings()
        return [dict(r) for r in rows]


def validate_batch(actor: Actor, batch_id, mapping: dict[str, str | None]) -> dict:
    actor.require("admin.write")
    with tenant_session(actor.tenant_id) as s:
        b = s.execute(text("SELECT * FROM import_batches WHERE id=:i FOR UPDATE"), {"i": batch_id}).mappings().first()
        if not b:
            raise OnboardingError("not_found", "import batch not found", 404)
        if b["status"] not in ("UPLOADED", "VALIDATED"):
            raise OnboardingError("invalid_state", f"a {b['status']} batch cannot be validated again", 409)
        unknown = [v for v in mapping.values() if v and v not in b["header"]]
        if unknown:
            raise OnboardingError("unknown_column", f"not in the file: {', '.join(unknown)}")
        raw = s.execute(text("SELECT row_no, raw FROM import_rows WHERE batch_id=:i ORDER BY row_no"),
                        {"i": batch_id}).mappings().all()
        try:
            results = ci.validate(b["kind"], mapping, [r["raw"] for r in raw])
        except ci.ImportError_ as e:
            raise OnboardingError(e.code, str(e)) from e
        if b["kind"] == "stock":      # snapshots already published for the same key would collide
            existing = {(str(r.as_of), r.location_id, r.sku_id) for r in s.execute(text(
                "SELECT as_of, location_id, sku_id FROM inventory_positions"))}
            results = [(n, e + ["a snapshot for this date, location and SKU is already published"])
                       if n and (n["as_of"], n["location_id"], n["sku_id"]) in existing else (n, e) for n, e in results]
            results = [(None if e else n, e) for n, e in results]
        if b["kind"] == "receipts":
            results = _check_receipts(s, results)
        if b["kind"] == "terms":
            existing = {r[0] for r in s.execute(text("SELECT term_id FROM supplier_terms"))}
            results = [(None, e + ["term_id already published"]) if n and n["term_id"] in existing else (n, e)
                       for n, e in results]
        s.execute(text("""UPDATE import_rows r SET normalized = CAST(x->>'n' AS jsonb), errors = ARRAY(
                SELECT jsonb_array_elements_text(x->'e')) FROM jsonb_array_elements(CAST(:res AS jsonb)) x
            WHERE r.batch_id = :b AND r.row_no = (x->>'row')::int"""),
            {"b": batch_id, "res": json.dumps([{"row": r["row_no"], "n": json.dumps(n) if n else None, "e": e}
                                               for r, (n, e) in zip(raw, results, strict=True)])})
        valid = sum(1 for n, _ in results if n)
        reasons: dict[str, int] = {}
        for _, e in results:
            for msg in e:
                reasons[msg.split(":")[0]] = reasons.get(msg.split(":")[0], 0) + 1
        report = {**(b["report"] or {}), "validated_at": datetime.now(UTC).isoformat(), "mapping": mapping,
                  "ignored_columns": [h for h in b["header"] if h not in mapping.values()],
                  "quarantine_reasons": reasons}
        s.execute(text("""UPDATE import_batches SET status='VALIDATED', mapping=CAST(:m AS jsonb), report=CAST(:r AS jsonb),
            rows_valid=:v, rows_quarantined=:q WHERE id=:i"""),
            {"m": json.dumps(mapping), "r": json.dumps(report), "v": valid, "q": len(results) - valid, "i": batch_id})
        _audit(s, actor, "import.validated", batch_id, {"valid": valid, "quarantined": len(results) - valid})
    return get(actor, batch_id)


def publish(actor: Actor, batch_id) -> dict:
    """Write the valid rows into the operational tables and freeze the batch, all in one transaction."""
    actor.require("admin.write")
    with tenant_session(actor.tenant_id) as s:
        b = s.execute(text("SELECT * FROM import_batches WHERE id=:i FOR UPDATE"), {"i": batch_id}).mappings().first()
        if not b:
            raise OnboardingError("not_found", "import batch not found", 404)
        if b["status"] != "VALIDATED":
            raise OnboardingError("invalid_state", "validate the batch before publishing", 409)
        if b["rows_valid"] == 0:
            raise OnboardingError("nothing_valid", "no valid rows to publish; fix the file or the mapping")
        rows = [r[0] for r in s.execute(text("""SELECT normalized FROM import_rows WHERE batch_id=:i AND normalized IS NOT NULL
            ORDER BY row_no"""), {"i": batch_id})]
        sha = ci.snapshot_sha(b["kind"], rows)
        t, payload = actor.tenant_id, json.dumps(rows)
        dataset_id = None
        if b["kind"] == "sales":
            dataset_id = uuid.uuid4()
            s.execute(text("""INSERT INTO datasets (id, tenant_id, name, source_kind, license, file_name, sha256, bytes,
                schema_version, status, report) VALUES (:i,:t,:n,'user_supplied',:lic,:f,:h,:b,:v,'READY',CAST(:r AS jsonb))"""),
                {"i": dataset_id, "t": t, "n": f"CSV sales: {b['file_name']}", "lic": b["report"].get("rights", ""),
                 "f": b["file_name"], "h": sha, "b": b["bytes"], "v": f"{ci.SCHEMA_VERSION}/sales",
                 "r": json.dumps({"import_batch": str(batch_id), "rows": len(rows), "quarantined": b["rows_quarantined"]})})
            s.execute(text("""INSERT INTO locations (tenant_id, location_id, name, kind, is_schematic, value_kind)
                SELECT DISTINCT :t, x->>'location_id', x->>'location_id', 'site', true, 'observed'
                FROM jsonb_array_elements(CAST(:rows AS jsonb)) x ON CONFLICT DO NOTHING"""), {"t": t, "rows": payload})
            s.execute(text("""INSERT INTO products (tenant_id, sku_id, source_kind, dataset_id, first_sale, last_sale)
                SELECT :t, x->>'sku_id', 'user_supplied', :d, min((x->>'day')::date), max((x->>'day')::date)
                FROM jsonb_array_elements(CAST(:rows AS jsonb)) x GROUP BY x->>'sku_id' ON CONFLICT DO NOTHING"""),
                {"t": t, "d": dataset_id, "rows": payload})
            s.execute(text("""INSERT INTO sales_daily (tenant_id, dataset_id, sku_id, location_id, day, units)
                SELECT :t, :d, x->>'sku_id', x->>'location_id', (x->>'day')::date, (x->>'units')::int
                FROM jsonb_array_elements(CAST(:rows AS jsonb)) x"""), {"t": t, "d": dataset_id, "rows": payload})
            s.execute(text("""INSERT INTO quarantine (tenant_id, dataset_id, source_sheet, source_row, reason, raw)
                SELECT :t, :d, :f, row_no, array_to_string(errors, '; '), raw FROM import_rows
                WHERE batch_id = :b AND cardinality(errors) > 0"""), {"t": t, "d": dataset_id, "f": b["file_name"], "b": batch_id})
            # the workspace clock follows the published data (end of the last observed sales day, UTC), never wall time:
            # a stale export stays visibly stale instead of being forecast from days that were never observed
            s.execute(text("""UPDATE tenant_settings SET dataset_id = :d,
                operational_as_of = (SELECT (max(day) + time '23:59:59') AT TIME ZONE 'UTC' FROM sales_daily
                                     WHERE dataset_id = :d)"""), {"d": dataset_id})
        elif b["kind"] == "stock":
            s.execute(text("""INSERT INTO locations (tenant_id, location_id, name, kind, is_schematic, value_kind)
                SELECT DISTINCT :t, x->>'location_id', x->>'location_id', 'warehouse', true, 'observed'
                FROM jsonb_array_elements(CAST(:rows AS jsonb)) x ON CONFLICT DO NOTHING"""), {"t": t, "rows": payload})
            s.execute(text("""INSERT INTO products (tenant_id, sku_id, source_kind)
                SELECT DISTINCT :t, x->>'sku_id', 'user_supplied' FROM jsonb_array_elements(CAST(:rows AS jsonb)) x
                ON CONFLICT DO NOTHING"""), {"t": t, "rows": payload})
            s.execute(text("""INSERT INTO inventory_positions (tenant_id, location_id, zone_id, sku_id, as_of, on_hand,
                allocated, on_order, capacity, value_kind) SELECT :t, x->>'location_id', 'DEFAULT', x->>'sku_id',
                (x->>'as_of')::date, (x->>'on_hand')::int, (x->>'allocated')::int, (x->>'on_order')::int,
                (x->>'capacity')::int, 'observed' FROM jsonb_array_elements(CAST(:rows AS jsonb)) x"""), {"t": t, "rows": payload})
        elif b["kind"] == "receipts":
            # re-check against the ledger as it is now (another import or a manual booking may have happened since)
            again = _check_receipts(s, [(r, []) for r in rows])
            if any(e for _, e in again):
                raise OnboardingError("stale_validation", "the order ledger changed since validation; validate again", 409)
            for r in rows:
                line = s.execute(text("""SELECT id, ordered_units, received_units, cancelled_units FROM purchase_order_lines
                    WHERE external_ref=:x AND sku_id=:k AND (CAST(:l AS text) IS NULL OR location_id = :l) FOR UPDATE"""),
                    {"x": r["po_number"], "k": r["sku_id"], "l": r.get("location_id")}).mappings().one()
                s.execute(text("""INSERT INTO receipts (id, tenant_id, po_line_id, sku_id, quantity, received_on, idempotency_key,
                    created_by) VALUES (:i,:t,:l,:k,:q,:d,:key,:u)"""),
                    {"i": uuid.uuid4(), "t": t, "l": line["id"], "k": r["sku_id"], "q": r["quantity"], "d": r["received_on"],
                     "key": f"erp:{r['receipt_id']}", "u": actor.user_id})
                got = line["received_units"] + r["quantity"]
                s.execute(text("""UPDATE purchase_order_lines SET received_units=:g, updated_at=now(),
                    status = CASE WHEN :g + cancelled_units = ordered_units THEN 'RECEIVED' ELSE 'PARTIAL' END WHERE id=:i"""),
                    {"g": got, "i": line["id"]})
        else:
            s.execute(text("""INSERT INTO suppliers (tenant_id, supplier_id, name, source_kind, value_kind)
                SELECT DISTINCT ON (x->>'supplier_id') :t, x->>'supplier_id', COALESCE(NULLIF(x->>'supplier_name', ''),
                x->>'supplier_id'), 'user_supplied', 'observed' FROM jsonb_array_elements(CAST(:rows AS jsonb)) x
                ON CONFLICT DO NOTHING"""), {"t": t, "rows": payload})
            s.execute(text("""INSERT INTO supplier_terms (term_id, tenant_id, supplier_id, sku_id, unit_cost_minor, currency,
                moq, order_multiple, lead_time_days, valid_from, valid_to, known_at, value_kind, source_kind)
                SELECT x->>'term_id', :t, x->>'supplier_id', x->>'sku_id', (x->>'unit_cost_minor')::bigint, x->>'currency',
                (x->>'moq')::int, (x->>'order_multiple')::int, (x->>'lead_time_days')::int, (x->>'valid_from')::date,
                NULLIF(x->>'valid_to', '')::date, (x->>'known_at')::timestamptz, 'observed', 'user_supplied'
                FROM jsonb_array_elements(CAST(:rows AS jsonb)) x"""), {"t": t, "rows": payload})
        s.execute(text("""UPDATE import_batches SET status='PUBLISHED', snapshot_sha256=:h, dataset_id=:d, published_at=now(),
            published_by=:u WHERE id=:i"""), {"h": sha, "d": dataset_id, "u": actor.user_id, "i": batch_id})
        _audit(s, actor, "import.published", batch_id, {"kind": b["kind"], "rows": len(rows), "snapshot_sha256": sha,
                                                        "dataset_id": dataset_id})
    return get(actor, batch_id)


def _check_receipts(s, results: list[tuple[dict | None, list[str]]]) -> list[tuple[dict | None, list[str]]]:
    """Receipts must match a reconciled SupplyLens order line, not be booked already, not predate the order and never take a
    line above its open quantity (counting earlier rows of the same file)."""
    booked = {r[0] for r in s.execute(text("SELECT idempotency_key FROM receipts WHERE idempotency_key LIKE 'erp:%'"))}
    lines: dict[tuple, list] = {}
    for r in s.execute(text("""SELECT external_ref, sku_id, location_id, ordered_units, received_units, cancelled_units,
            ordered_on FROM purchase_order_lines""")):
        lines.setdefault((r.external_ref, r.sku_id), []).append(r)
    pending: dict[tuple, int] = {}
    out = []
    for n, e in results:
        if n is None:
            out.append((None, e))
            continue
        errs = []
        cands = [x for x in lines.get((n["po_number"], n["sku_id"]), [])
                 if not n.get("location_id") or x.location_id == n["location_id"]]
        line = cands[0] if len(cands) == 1 else None
        if f"erp:{n['receipt_id']}" in booked:
            errs.append("receipt_id already booked")
        elif len(cands) > 1:
            errs.append("this order carries the SKU for several locations; fill location_id")
        elif line is None:
            errs.append("no reconciled SupplyLens order line for this PO number and SKU")
        else:
            key = (n["po_number"], n["sku_id"], line.location_id)
            open_units = line.ordered_units - line.received_units - line.cancelled_units - pending.get(key, 0)
            if n["quantity"] > open_units:
                errs.append(f"quantity exceeds the {max(open_units, 0)} unit(s) still open on this line")
            elif n["received_on"] < str(line.ordered_on):
                errs.append("received before the order date")
            else:
                pending[key] = pending.get(key, 0) + n["quantity"]
        out.append((None, errs) if errs else (n, e))
    return out
