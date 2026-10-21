"""Load the execution pack's FICTIONAL operations data and contracts into the Demo workspace,
plus the spec's reference policy-change case. Nothing here is real business data."""
from __future__ import annotations

import csv
import json
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import text

from ..config import REPO_ROOT
from ..db import tenant_session
from ..knowledge.ingest import ingest_document

OPS = REPO_ROOT / "data" / "synthetic" / "operations"
CONTRACTS = REPO_ROOT / "knowledge" / "synthetic_contracts"
REF = REPO_ROOT / "fixtures" / "reference_case"
DEMO_AS_OF = datetime(2027, 2, 15, 18, 0, tzinfo=timezone.utc)
REF_KNOWN = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _csv(name):
    with (OPS / name).open(newline="") as f:
        return list(csv.DictReader(f))


def _minor(v: str) -> int:
    return int((Decimal(v) * 100).to_integral_value())


def load(tenant_id) -> dict:
    with tenant_session(tenant_id) as s:
        if s.execute(text("SELECT 1 FROM suppliers LIMIT 1")).first():
            return {"reused": True}
    manifest = json.loads((CONTRACTS / "manifest.json").read_text())
    versions: dict[str, tuple] = {}
    for d in manifest["documents"]:
        prior = versions.get(d.get("supersedes"))
        res = ingest_document(
            tenant_id, title=d["title"], doc_type=d["doc_type"], supplier_id=d["supplier_id"],
            source_kind="generated", file_name=d["file"], body=(CONTRACTS / d["file"]).read_text(),
            version_label=d["version_label"], known_at=datetime.fromisoformat(d["known_at"]),
            valid_from=date.fromisoformat(d["valid_from"]),
            valid_to=date.fromisoformat(d["valid_to"]) if d.get("valid_to") else None,
            supersedes_version_id=prior[0] if prior else None, document_id=prior[1] if prior else None)
        versions[d["file"]] = (res["version_id"], res["document_id"], datetime.fromisoformat(d["known_at"]))
    ref_docs = {}
    for key, title, label, eff, known, sup, prior_key in [
        ("A1", "Reference Supplier A agreement", "v1", date(2026, 1, 1), REF_KNOWN, "DEMO-REF-A", None),
        ("A2", "Reference Supplier A agreement", "amendment v2", date(2026, 10, 20),
         datetime(2026, 10, 15, 9, tzinfo=timezone.utc), "DEMO-REF-A", "A1"),
        ("B1", "Reference Supplier B agreement", "v1", date(2026, 1, 1), REF_KNOWN, "DEMO-REF-B", None),
    ]:
        fname = {"A1": "supplier-A-v1.txt", "A2": "supplier-A-amendment-v2.txt", "B1": "supplier-B-v1.txt"}[key]
        prior = ref_docs.get(prior_key)
        res = ingest_document(
            tenant_id, title=title, doc_type="amendment" if prior else "framework_agreement", supplier_id=sup,
            source_kind="generated", file_name=fname, body=(REF / fname).read_text(), version_label=label,
            known_at=known, valid_from=eff, supersedes_version_id=prior[0] if prior else None,
            document_id=prior[1] if prior else None)
        ref_docs[key] = (res["version_id"], res["document_id"], known)

    with tenant_session(tenant_id) as s:
        for r in _csv("suppliers.csv"):
            s.execute(text("INSERT INTO suppliers VALUES (:t,:s,:n,'generated','synthetic')"),
                      {"t": tenant_id, "s": r["supplier_id"], "n": r["supplier_name"] + " (FICTIONAL)"})
        for sid, name in (("DEMO-REF-A", "Reference Supplier A (FICTIONAL)"),
                          ("DEMO-REF-B", "Reference Supplier B (FICTIONAL)")):
            s.execute(text("INSERT INTO suppliers VALUES (:t,:s,:n,'generated','synthetic')"),
                      {"t": tenant_id, "s": sid, "n": name})
        for r in _csv("products.csv"):
            s.execute(text("INSERT INTO products (tenant_id, sku_id, description, unit, source_kind) "
                           "VALUES (:t,:k,:d,:u,'generated')"),
                      {"t": tenant_id, "k": r["sku_id"], "d": r["description"], "u": r["unit"]})
        s.execute(text("INSERT INTO products (tenant_id, sku_id, description, unit, source_kind) VALUES "
                       "(:t,'DEMO-REF-SKU','Reference component (spec test case, FICTIONAL)','unit','generated')"),
                  {"t": tenant_id})
        s.execute(text("INSERT INTO locations VALUES (:t,'DEMO-WH-01','Demo warehouse 01 (FICTIONAL)','warehouse',"
                       "true,'synthetic')"), {"t": tenant_id})
        doc_for = {("DEMO-SUP-001", "v1"): "DEMO-SUP-001-framework-v1.txt",
                   ("DEMO-SUP-001", "v2"): "DEMO-SUP-001-amendment-v2.txt",
                   ("DEMO-SUP-002", "v1"): "DEMO-SUP-002-framework-v1.txt"}
        for r in _csv("supplier_product_terms.csv"):
            doc = versions.get(doc_for.get((r["supplier_id"], r["contract_version"])))
            supersedes = "DEMO-TERM-0001" if r["supplier_term_id"] == "DEMO-TERM-0001-V2" else None
            s.execute(text("""INSERT INTO supplier_terms (term_id, tenant_id, supplier_id, sku_id, unit_cost_minor,
                currency, moq, order_multiple, lead_time_days, valid_from, valid_to, known_at, document_version_id,
                section, value_kind, source_kind, supersedes_term_id) VALUES (:id,:t,:s,:k,:c,:cur,:m,:mu,:lt,:vf,:vt,
                :ka,:v,:sec,'synthetic','generated',:sup)"""),
                {"id": r["supplier_term_id"], "t": tenant_id, "s": r["supplier_id"], "k": r["sku_id"],
                 "c": _minor(r["unit_cost_gbp"]), "cur": r["currency"], "m": int(r["minimum_order_quantity"]),
                 "mu": int(r["order_multiple"]), "lt": int(r["lead_time_days"]),
                 "vf": r["effective_from"], "vt": r["effective_to"] or None,
                 "ka": doc[2] if doc else datetime(2026, 12, 1, 9, tzinfo=timezone.utc),
                 "v": doc[0] if doc else None, "sec": "Preamble" if doc else None, "sup": supersedes})
        for tid, sup, moq, mult, cost, vf, key, supersedes in [
            ("REF-A-v1", "DEMO-REF-A", 20, 10, 500, "2026-01-01", "A1", None),
            ("REF-A-v2", "DEMO-REF-A", 40, 10, 500, "2026-10-20", "A2", "REF-A-v1"),
            ("REF-B-v1", "DEMO-REF-B", 10, 5, 600, "2026-01-01", "B1", None),
        ]:
            vid, _, known = ref_docs[key]
            s.execute(text("""INSERT INTO supplier_terms (term_id, tenant_id, supplier_id, sku_id, unit_cost_minor,
                currency, moq, order_multiple, lead_time_days, valid_from, known_at, document_version_id, section,
                value_kind, source_kind, supersedes_term_id) VALUES (:id,:t,:s,'DEMO-REF-SKU',:c,'USD',:m,:mu,2,:vf,
                :ka,:v,'Schedule item DEMO-REF-SKU (Reference component):','synthetic','generated',:sup)"""),
                {"id": tid, "t": tenant_id, "s": sup, "c": cost, "m": moq, "mu": mult, "vf": vf, "ka": known,
                 "v": vid, "sup": supersedes})
        snaps = _csv("inventory_snapshots.csv")
        for i, r in enumerate(snaps):
            s.execute(text("""INSERT INTO inventory_positions VALUES (:t,:w,:z,:k,:d,:oh,:al,:oo,:cap,'synthetic',NULL)"""),
                      {"t": tenant_id, "w": r["warehouse_id"], "z": r["zone_id"], "k": r["sku_id"],
                       "d": r["snapshot_date"], "oh": int(r["on_hand"]), "al": int(r["allocated"]),
                       "oo": int(r["on_order"]), "cap": int(r["reorder_point"]) * 4})
            zone = r["zone_id"][-1]
            zi = "ABCD".index(zone)
            n = sum(1 for x in snaps[:i] if x["zone_id"] == r["zone_id"])
            s.execute(text("INSERT INTO warehouse_slots VALUES (:t,:w,:id,:z,:a,:r,:x,:zz,:k,true)"),
                      {"t": tenant_id, "w": r["warehouse_id"], "id": f"{zone}-{n // 3 + 1}-{n % 3 + 1}",
                       "z": r["zone_id"], "a": n // 3 + 1, "r": n % 3 + 1, "x": (zi % 2) * 14.0 + (n // 3) * 4.0,
                       "zz": (zi // 2) * 12.0 + (n % 3) * 2.6, "k": r["sku_id"]})
        s.execute(text("INSERT INTO inventory_positions VALUES (:t,'DEMO-WH-01','DEMO-ZONE-D','DEMO-REF-SKU',"
                       "'2027-02-15',0,0,0,200,'synthetic',NULL)"), {"t": tenant_id})
        s.execute(text("INSERT INTO warehouse_slots VALUES (:t,'DEMO-WH-01','D-4-1','DEMO-ZONE-D',4,1,26.0,12.0,"
                       "'DEMO-REF-SKU',true)"), {"t": tenant_id})
        s.execute(text("""INSERT INTO tenant_settings VALUES (:t, :a, 'GBP', NULL, NULL, CAST(:p AS jsonb))
            ON CONFLICT (tenant_id) DO NOTHING"""),
                  {"t": tenant_id, "a": DEMO_AS_OF,
                   "p": json.dumps({"weekly_budget_minor": 500000, "reorder_rule": "reorder_point_from_fixture",
                                    "reference_case": {"sku_id": "DEMO-REF-SKU", "required_units": 30,
                                                       "need_by": "2026-10-22", "budget_minor": 18000,
                                                       "currency": "USD"}})})
    return {"reused": False, "documents": len(versions) + len(ref_docs)}
