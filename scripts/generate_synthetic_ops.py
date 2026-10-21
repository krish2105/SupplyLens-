#!/usr/bin/env python3
"""Generate reproducible, clearly labelled FICTIONAL SupplyLens operational demo records.

No line in these generated files describes a real supplier, transaction, stock level,
contract, delivery or warehouse. Never use these records to claim business ROI.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 271828
SUPPLIERS = [
    ("DEMO-SUP-001", "Demo Northstar Supplies Ltd"),
    ("DEMO-SUP-002", "Demo Meridian Distribution Ltd"),
    ("DEMO-SUP-003", "Demo Cedar Logistics Ltd"),
    ("DEMO-SUP-004", "Demo Cobalt Wholesale Ltd"),
    ("DEMO-SUP-005", "Demo Summit Components Ltd"),
    ("DEMO-SUP-006", "Demo Harbor Procurement Ltd"),
]


def save_csv(target: Path, rows: list[dict]):
    if not rows:
        raise ValueError("Refusing empty dataset")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build(seed: int = SEED, output_dir: Path | None = None) -> dict:
    rng = random.Random(seed)
    out = output_dir or (ROOT / "data" / "synthetic" / "operations")
    docs = ROOT / "knowledge" / "synthetic_contracts"
    out.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    common = {"data_origin": "synthetic", "generation_seed": seed, "scenario_id": "DEMO-BASELINE"}
    suppliers = [{"supplier_id": sid, "supplier_name": name, "country": "FICTIONAL", **common}
                 for sid, name in SUPPLIERS]
    products = []
    terms = []
    snapshots = []
    orders = []
    zone_names = ["A", "B", "C", "D"]
    for idx in range(1, 37):
        sku = f"DEMO-SKU-{idx:03d}"
        supplier_id = SUPPLIERS[(idx - 1) % len(SUPPLIERS)][0]
        sku_name = f"Fictional Packaging Component {idx:03d}"
        unit_cost = round(1.8 + (idx % 8) * 1.15, 2)
        min_order = [20, 40, 60, 80][idx % 4]
        multiple = [5, 10, 20][idx % 3]
        if min_order % multiple:
            min_order += multiple - min_order % multiple
        lead_days = [3, 5, 7, 10, 14][idx % 5]
        on_hand = rng.randint(12, 220)
        allocated = rng.randint(0, min(25, on_hand))
        products.append({"sku_id": sku, "description": sku_name, "unit": "unit", **common})
        terms.append({"supplier_term_id": f"DEMO-TERM-{idx:04d}", "supplier_id": supplier_id,
                      "sku_id": sku, "unit_cost_gbp": unit_cost, "currency": "GBP",
                      "minimum_order_quantity": min_order, "order_multiple": multiple,
                      "lead_time_days": lead_days, "effective_from": "2027-01-01",
                      "effective_to": "", "contract_version": "v1", **common})
        snapshots.append({"snapshot_date": "2027-02-15", "warehouse_id": "DEMO-WH-01",
                          "zone_id": f"DEMO-ZONE-{zone_names[(idx - 1) % 4]}", "sku_id": sku,
                          "on_hand": on_hand, "allocated": allocated,
                          "available": on_hand - allocated, "on_order": rng.randint(0, 120),
                          "reorder_point": rng.randint(25, 85), **common})
        if idx % 2 == 0:
            qty = ((max(min_order, rng.randint(35, 105)) + multiple - 1) // multiple) * multiple
            order_date = dt.date(2027, 2, 1) + dt.timedelta(days=idx % 5)
            orders.append({"po_id": f"DEMO-PO-{idx:05d}", "line_no": 1,
                           "sku_id": sku, "supplier_id": supplier_id,
                           "warehouse_id": "DEMO-WH-01", "order_date": order_date.isoformat(),
                           "promised_date": (order_date + dt.timedelta(days=lead_days)).isoformat(),
                           "quantity_ordered": qty, "unit_cost_gbp": unit_cost,
                           "status": "draft", "actual_receipt_date": "", **common})

    # A designated date-change fixture for temporal-RAG regression tests.
    special = terms[0]
    special["minimum_order_quantity"] = 40
    special["order_multiple"] = 10
    special["lead_time_days"] = 7
    special["effective_to"] = "2027-03-31"
    special["contract_version"] = "v1"
    new_term = {**special, "supplier_term_id": "DEMO-TERM-0001-V2",
                "minimum_order_quantity": 60, "lead_time_days": 10,
                "effective_from": "2027-04-01", "effective_to": "",
                "contract_version": "v2"}
    terms.append(new_term)

    files = {
        "suppliers.csv": suppliers,
        "products.csv": products,
        "supplier_product_terms.csv": terms,
        "inventory_snapshots.csv": snapshots,
        "purchase_order_lines.csv": orders,
    }
    for fname, rows in files.items():
        save_csv(out / fname, rows)

    (docs / "DEMO-SUP-001-framework-v1.txt").write_text(
        "FICTIONAL DOCUMENT - GENERATED FOR SOFTWARE TESTING - NOT A REAL CONTRACT\n"
        "Buyer: SupplyLens Demo Company (FICTIONAL)\n"
        "Supplier: Demo Northstar Supplies Ltd (FICTIONAL)\n"
        "Agreement: DEMO-CTR-001, version v1, effective 2027-01-01\n"
        "For DEMO-SKU-001 minimum order quantity is 40 units, in multiples of 10.\n"
        "The contractual standard lead time is 7 calendar days.\n"
        "Amendments override incompatible terms only from the amendment's effective date.\n"
        "data_origin=synthetic; generation_seed=" + str(seed) + "\n",
        encoding="utf-8")
    (docs / "DEMO-SUP-001-amendment-v2.txt").write_text(
        "FICTIONAL DOCUMENT - GENERATED FOR SOFTWARE TESTING - NOT A REAL CONTRACT\n"
        "Amendment: DEMO-AMD-001, version v2, applies to DEMO-CTR-001.\n"
        "Effective date: 2027-04-01.\n"
        "From 2027-04-01, minimum order quantity of DEMO-SKU-001 is 60 units;\n"
        "orders remain in multiples of 10. Standard lead time becomes 10 days.\n"
        "Earlier terms are superseded only from the effective date.\n"
        "Supplier: Demo Northstar Supplies Ltd (FICTIONAL).\n"
        "data_origin=synthetic; generation_seed=" + str(seed) + "\n",
        encoding="utf-8")
    (docs / "DEMO-SUP-002-framework-v1.txt").write_text(
        "FICTIONAL DOCUMENT - GENERATED FOR SOFTWARE TESTING - NOT A REAL CONTRACT\n"
        "Agreement DEMO-CTR-002 effective 2027-01-01; supplier Demo Meridian Distribution Ltd.\n"
        "This agreement covers Demo Meridian's scheduled product SKUs only.\n"
        "Each SKU's minimum quantity and lead time are listed in supplier_product_terms.csv.\n"
        "Do not infer any terms for suppliers not named in this agreement.\n"
        "data_origin=synthetic; generation_seed=" + str(seed) + "\n",
        encoding="utf-8")
    truth = {
        "dataset": "SupplyLens FICTIONAL temporal supplier-policy fixture",
        "data_origin": "synthetic", "seed": seed,
        "as_of_2027_03_31": {"supplier_id": "DEMO-SUP-001", "sku_id": "DEMO-SKU-001",
                             "minimum_order_quantity": 40, "lead_time_days": 7,
                             "applies_from": "2027-01-01", "evidence": "DEMO-SUP-001-framework-v1.txt"},
        "as_of_2027_04_01": {"supplier_id": "DEMO-SUP-001", "sku_id": "DEMO-SKU-001",
                             "minimum_order_quantity": 60, "lead_time_days": 10,
                             "applies_from": "2027-04-01", "evidence": "DEMO-SUP-001-amendment-v2.txt"}
    }
    (out / "policy_ground_truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    (out / "README_SYNTHETIC.txt").write_text(
        "SYNTHETIC OPERATIONS DATA, NOT ACTUAL ENTERPRISE TRANSACTIONS.\n"
        "Only use for a labelled application demonstration, offline tests and controlled\n"
        "simulation experiments. DO NOT merge with public records by coincidental IDs.\n"
        "Generator: scripts/generate_synthetic_ops.py\n"
        f"Seed: {seed}\n"
        "All entities deliberately fictional; no measured operational costs or delivery\n"
        "reliability are implied. Source-of-truth dates are in policy_ground_truth.json.\n",
        encoding="utf-8")
    return {k: len(v) for k, v in files.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()
    print(json.dumps(build(args.seed), indent=2))


if __name__ == "__main__":
    main()
