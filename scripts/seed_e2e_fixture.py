"""Load a small SYNTHETIC retail workspace so the browser suite can run without the real UCI dataset.

    uv run python scripts/seed_e2e_fixture.py

Writes into the `uci-research` workspace (the one the interface defaults to): 36 products, 420 days of generated
daily sales, stock positions with a spread of healthy / shortage / excess cover, a schematic warehouse layout,
two suppliers and their terms. Everything is generated with a fixed seed and labelled synthetic; the dataset is
named "SYNTHETIC e2e fixture". Never run it against a database holding the real dataset: it refuses to.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone

import numpy as np
from sqlalchemy import text

from supplylens.db import tenant_session
from supplylens.seed import seed, tenant_id

NAME = "SYNTHETIC e2e fixture"
N_SKU, DAYS = 36, 420
LAST_DAY = date(2011, 12, 8)


def load() -> dict:
    seed()
    t = tenant_id("uci-research")
    with tenant_session(t) as s:
        if s.execute(text("SELECT count(*) FROM datasets WHERE name <> :n"), {"n": NAME}).scalar():
            raise SystemExit("uci-research already holds a real dataset; refusing to add the synthetic fixture")
        if s.execute(text("SELECT 1 FROM datasets WHERE name = :n"), {"n": NAME}).first():
            return {"reused": True}
    rng = np.random.default_rng(20111208)
    start = LAST_DAY - timedelta(days=DAYS - 1)
    did = uuid.uuid4()
    skus = [f"SYN{n:03d}" for n in range(1, N_SKU + 1)]
    rates = rng.gamma(2.0, 6.0, N_SKU) + 1.0
    weekly = np.array([1.0, 1.1, 1.0, 1.05, 1.3, 0.6, 0.45])
    total_units = 0
    with tenant_session(t) as s:
        report = {"totals": {"input_rows": N_SKU * DAYS, "accepted": N_SKU * DAYS, "returned": 0, "quarantined": 0},
                  "sheets": {}, "date_span": [start.isoformat(), LAST_DAY.isoformat()], "distinct_skus_accepted": N_SKU,
                  "distinct_customers": 0, "missing_customer_id_rows": 0, "notes": ["Generated for browser tests. Not real data."]}
        s.execute(text("INSERT INTO datasets (id, tenant_id, name, source_kind, license, source_url, file_name, sha256, bytes, "
                       "schema_version, status, report) VALUES (:i,:t,:n,'generated','synthetic',NULL,'e2e-fixture',:h,0,'e2e-v1','READY',"
                       "CAST(:r AS jsonb))"), {"i": did, "t": t, "n": NAME, "h": uuid.uuid4().hex * 2, "r": json.dumps(report)})
        s.execute(text("INSERT INTO locations VALUES (:t,'WH-SYN','Synthetic warehouse','warehouse',true,'synthetic')"), {"t": t})
        s.execute(text("INSERT INTO suppliers VALUES (:t,'SYN-SUP-A','Synthetic Supplier A','generated','synthetic')"), {"t": t})
        s.execute(text("INSERT INTO suppliers VALUES (:t,'SYN-SUP-B','Synthetic Supplier B','generated','synthetic')"), {"t": t})
        rows = []
        for i, sku in enumerate(skus):
            s.execute(text("INSERT INTO products (tenant_id, sku_id, description, unit, source_kind, dataset_id, first_sale, last_sale) "
                           "VALUES (:t,:k,:d,'unit','generated',:ds,:f,:l)"),
                      {"t": t, "k": sku, "d": f"Synthetic product {i + 1}", "ds": did, "f": start, "l": LAST_DAY})
            for d in range(DAYS):
                day = start + timedelta(days=d)
                if rng.random() < 0.12:       # no recorded sales on some days (absence != zero demand)
                    continue
                units = int(rng.poisson(rates[i] * weekly[day.weekday()]))
                if units:
                    rows.append({"t": str(t), "d": str(did), "k": sku, "day": day.isoformat(), "u": units})
                    total_units += units
            # cover spread: some SKUs short, some in excess, most healthy
            cover = [2.5, 4, 12, 20, 35, 60, 150][i % 7]
            on_hand = int(rates[i] * cover)
            s.execute(text("INSERT INTO inventory_positions VALUES (:t,'WH-SYN',:z,:k,:d,:oh,:al,:oo,:cap,'synthetic',NULL)"),
                      {"t": t, "z": f"SYN-ZONE-{'ABCD'[i % 4]}", "k": sku, "d": LAST_DAY, "oh": on_hand, "al": int(on_hand * 0.1),
                       "oo": 0, "cap": max(on_hand * 3, 50)})
            zi, n = i % 4, i // 4
            s.execute(text("INSERT INTO warehouse_slots VALUES (:t,'WH-SYN',:id,:z,:a,:r,:x,:zz,:k,true)"),
                      {"t": t, "id": f"{'ABCD'[zi]}-{n // 3 + 1}-{n % 3 + 1}", "z": f"SYN-ZONE-{'ABCD'[zi]}", "a": n // 3 + 1, "r": n % 3 + 1,
                       "x": (zi % 2) * 14.0 + (n // 3) * 4.0, "zz": (zi // 2) * 12.0 + (n % 3) * 2.6, "k": sku})
            for sup, cost, moq, lt in (("SYN-SUP-A", 480 + i, 20, 5), ("SYN-SUP-B", 520 + i, 10, 3)):
                s.execute(text("""INSERT INTO supplier_terms (term_id, tenant_id, supplier_id, sku_id, unit_cost_minor, currency, moq,
                    order_multiple, lead_time_days, valid_from, known_at, value_kind, source_kind) VALUES (:id,:t,:s,:k,:c,'GBP',:m,5,:lt,
                    '2011-01-01','2011-01-01T00:00:00Z','simulated','generated')"""),
                          {"id": f"{sup}-{sku}", "t": t, "s": sup, "k": sku, "c": cost, "m": moq, "lt": lt})
        for k in range(0, len(rows), 2000):
            s.execute(text("INSERT INTO sales_daily (tenant_id, dataset_id, sku_id, location_id, day, units) "
                           "SELECT x.t::uuid, x.d::uuid, x.k, 'WH-SYN', x.day::date, x.u FROM jsonb_to_recordset(CAST(:r AS jsonb)) "
                           "AS x(t text, d text, k text, day text, u int)"), {"r": json.dumps(rows[k:k + 2000])})
        s.execute(text("INSERT INTO tenant_settings VALUES (:t,:a,'GBP',:d,NULL,CAST(:p AS jsonb)) ON CONFLICT (tenant_id) DO NOTHING"),
                  {"t": t, "a": datetime(2011, 12, 8, 23, 59, tzinfo=timezone.utc), "d": did,
                   "p": json.dumps({"weekly_budget_minor": 2_000_000, "coverage_days": 21, "safety_days": 5})})
    return {"reused": False, "products": N_SKU, "sales_rows": len(rows), "units": total_units}


if __name__ == "__main__":
    print(json.dumps(load()))
