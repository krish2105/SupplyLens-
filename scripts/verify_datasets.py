#!/usr/bin/env python3
"""Inspect source availability, licensing separation, and synthetic fixture integrity.

A success exit code does NOT mean unavailable external datasets were downloaded.
Use --require-core only after executing the acquisition scripts.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "source_manifest.json"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def validate_synthetic():
    base = ROOT / "data" / "synthetic" / "operations"
    files = ["suppliers.csv", "products.csv", "supplier_product_terms.csv",
             "inventory_snapshots.csv", "purchase_order_lines.csv"]
    rows = {n: read_csv(base / n) for n in files}
    suppliers = {r["supplier_id"] for r in rows["suppliers.csv"]}
    products = {r["sku_id"] for r in rows["products.csv"]}
    errors = []
    for name, group in rows.items():
        if not group:
            errors.append(f"Empty fixture: {name}")
        for i, r in enumerate(group, start=2):
            if r.get("data_origin") != "synthetic":
                errors.append(f"Missing synthetic provenance in {name}:{i}")
            if r.get("supplier_id") and r["supplier_id"] not in suppliers:
                errors.append(f"Bad supplier key in {name}:{i}")
            if r.get("sku_id") and r["sku_id"] not in products:
                errors.append(f"Bad SKU key in {name}:{i}")
    for i, r in enumerate(rows["supplier_product_terms.csv"], start=2):
        moq, multiple = int(r["minimum_order_quantity"]), int(r["order_multiple"])
        if multiple <= 0 or moq <= 0 or moq % multiple != 0:
            errors.append(f"Invalid order multiple in terms:{i}")
    for i, r in enumerate(rows["inventory_snapshots.csv"], start=2):
        if int(r["on_hand"]) != int(r["available"]) + int(r["allocated"]):
            errors.append(f"Snapshot balance mismatch:{i}")
    for i, r in enumerate(rows["purchase_order_lines.csv"], start=2):
        if int(r["quantity_ordered"]) <= 0:
            errors.append(f"Invalid order quantity:{i}")
    special = [r for r in rows["supplier_product_terms.csv"] if r["sku_id"] == "DEMO-SKU-001"]
    if len(special) != 2 or sorted(int(r["minimum_order_quantity"]) for r in special) != [40, 60]:
        errors.append("Temporal amendment test fixture is missing or inconsistent")
    docs = ROOT / "knowledge" / "synthetic_contracts"
    for filename in ("DEMO-SUP-001-framework-v1.txt", "DEMO-SUP-001-amendment-v2.txt"):
        text = (docs / filename).read_text(encoding="utf-8")
        if "FICTIONAL DOCUMENT" not in text:
            errors.append(f"Unmarked fictional document: {filename}")
    return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--require-core", action="store_true",
                    help="Fail if any core dataset is absent, including manual-only sources")
    ap.add_argument("--check-archives", action="store_true", help="Scan downloaded ZIP CRCs (may take time)")
    ns = ap.parse_args()
    catalog = json.loads(MANIFEST.read_text(encoding="utf-8"))["datasets"]
    rows = read_csv(ROOT / "data" / "DATASET_CATALOG.csv")
    errors = validate_synthetic()
    if [d["id"] for d in catalog] != [r["id"] for r in rows]:
        errors.append("Source manifest and CSV catalog entries are not aligned")
    present = missing = 0
    for d in catalog:
        target = ROOT / d["destination"]
        if d["method"].startswith("manual"):
            # A manual dataset may have a differently named downloaded artifact.
            detected = target.is_dir() and any(p.is_file() for p in target.rglob("*"))
        else:
            detected = target.exists() and (target.is_dir() or target.stat().st_size > 0)
        if detected:
            present += 1
        else:
            missing += 1
            if ns.require_core and d["profile"] == "core":
                errors.append(f"Core dataset missing: {d['id']}")
        print(f"{'PRESENT' if detected else 'MISSING':7} {d['id']:24} {d['origin']}")
        if detected and ns.check_archives and target.is_file() and target.suffix == ".zip":
            try:
                with zipfile.ZipFile(target) as zf:
                    bad = zf.testzip()
                    if bad:
                        errors.append(f"Corrupt member in {target}: {bad}")
            except (OSError, zipfile.BadZipFile) as e:
                errors.append(f"Invalid zip {target}: {e}")
    for e in errors:
        print("ERROR:", e, file=sys.stderr)
    print(f"\nCatalog: {len(catalog)} sources; externally present: {present}; missing: {missing}.")
    print("Synthetic fixtures:", "PASS" if not validate_synthetic() else "FAIL")
    print("Real datasets are NOT bundled in the ZIP; check acquisition receipts for downloaded content.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
