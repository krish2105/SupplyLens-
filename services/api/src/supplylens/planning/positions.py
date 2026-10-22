"""Stock positions for planning: the latest snapshot per SKU, plus SupplyLens' own open orders and receipts.

Grain (audit S21). A SKU stocked at one location is keyed by its SKU id; a SKU stocked at several locations gets one
position per location, keyed `SKU@LOCATION` (planning/grain.py), so stock is never pooled across sites and a shortage at
one site cannot hide behind surplus at another.

Open supply (audit S12). The imported snapshot is the source system's view and never contains orders SupplyLens placed.
For each SKU the position adds, from purchase_order_lines, the units still open on SupplyLens orders dated on or after
the snapshot date and on or before the decision date, and moves units received in that interval from on-order to
on-hand. Business dates are used throughout (the research workspaces run on a simulated clock). Cancelled units release
the open quantity. Orders dated before the snapshot are assumed to be inside it already.

Committed orders not yet reconciled (audit P1-ACT-02). An approved order is committed money before the target system
confirms it: QUEUED, SUBMITTED, UNKNOWN_OUTCOME (it may exist) and CONFIRMED (it exists but its read-back differs) are
counted as open supply from their approved payload, so a second run cannot buy the same need while the first order is in
flight. They enter the ledger, and leave this count, when reconciled. Drafts awaiting approval are not counted (they may be
rejected); planning reports them instead.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import text

from .grain import plan_key

MAX_SKUS_PER_RUN = 60   # declared pilot limit for one agent run or scenario (see DECISIONS D-043)
COMMITTED_UNRECONCILED = ("QUEUED", "SUBMITTED", "UNKNOWN_OUTCOME", "CONFIRMED")


class ScopeTooLarge(ValueError):
    pass


def bounded_scope(skus: list[str], explicit: bool) -> tuple[list[str], dict]:
    """Apply the per-run SKU limit. An explicit list over the limit is rejected; the implicit "all SKUs" scope is cut
    to the first MAX_SKUS_PER_RUN by SKU id and the cut is reported, never silent."""
    if len(skus) <= MAX_SKUS_PER_RUN:
        return skus, {"requested": len(skus), "assessed": len(skus), "limit": MAX_SKUS_PER_RUN, "truncated": 0}
    if explicit:
        raise ScopeTooLarge(f"{len(skus)} SKUs requested; one run plans at most {MAX_SKUS_PER_RUN}. Split the request.")
    kept = sorted(skus)[:MAX_SKUS_PER_RUN]
    return kept, {"requested": len(skus), "assessed": len(kept), "limit": MAX_SKUS_PER_RUN,
                  "truncated": len(skus) - len(kept),
                  "note": f"workspace has {len(skus)} stocked SKUs; this run assessed the first {len(kept)} by SKU id"}


def load_positions(s, skus: list[str], decision_date: date) -> tuple[dict[str, dict], dict[str, str]]:
    """Return ({plan key: position}, {sku: reason not assessed}). `s` is a tenant session. Each position carries its real
    `sku_id` and `location_id`; the key is the SKU id, or `SKU@LOCATION` when the SKU is stocked at several locations."""
    rows = s.execute(text("""SELECT DISTINCT ON (sku_id, location_id) sku_id, location_id, on_hand, allocated, on_order,
            capacity, value_kind, as_of
        FROM inventory_positions WHERE sku_id = ANY(:k) AND as_of <= :e
        ORDER BY sku_id, location_id, as_of DESC"""), {"k": skus, "e": decision_date}).mappings().all()
    by_sku: dict[str, list[dict]] = {}
    for r in rows:
        by_sku.setdefault(r["sku_id"], []).append(dict(r))
    positions, excluded = {}, {}
    for sku in skus:
        snaps = by_sku.get(sku)
        if not snaps:
            excluded[sku] = "no stock record on or before the decision date"
            continue
        multi = len(snaps) > 1
        for snap in snaps:
            positions[plan_key(sku, snap["location_id"], multi)] = {**snap, "multi_location": multi,
                                                                    "open_order_units": 0, "received_since_snapshot": 0}
    if positions:
        # Open supply per SKU and location; ledger lines without a location belong to a single-location SKU only.
        supply = s.execute(text("""
            SELECT l.sku_id, l.location_id,
              sum(CASE WHEN l.ordered_on BETWEEN p.as_of AND :e
                       THEN l.ordered_units - l.cancelled_units
                            - COALESCE((SELECT sum(r.quantity) FROM receipts r WHERE r.po_line_id = l.id
                                        AND r.received_on <= :e), 0) ELSE 0 END) AS open_units,
              sum(CASE WHEN l.ordered_on BETWEEN p.as_of AND :e
                       THEN COALESCE((SELECT sum(r.quantity) FROM receipts r WHERE r.po_line_id = l.id
                                      AND r.received_on BETWEEN p.as_of AND :e), 0) ELSE 0 END) AS received_units
            FROM purchase_order_lines l
            JOIN (SELECT sku_id, location_id, max(as_of) AS as_of FROM inventory_positions
                  WHERE sku_id = ANY(:k) AND as_of <= :e GROUP BY sku_id, location_id) p
              ON p.sku_id = l.sku_id AND (l.location_id IS NULL OR l.location_id = p.location_id)
            WHERE l.sku_id = ANY(:k) GROUP BY l.sku_id, l.location_id"""),
            {"k": sorted({p["sku_id"] for p in positions.values()}), "e": decision_date}).mappings()
        committed = s.execute(text("""
            SELECT l->>'sku_id' AS sku_id, l->>'location_id' AS location_id,
                   sum((l->>'quantity')::int) AS open_units, 0 AS received_units
            FROM actions a CROSS JOIN LATERAL jsonb_array_elements(a.payload->'lines') l
            JOIN (SELECT sku_id, location_id, max(as_of) AS as_of FROM inventory_positions
                  WHERE sku_id = ANY(:k) AND as_of <= :e GROUP BY sku_id, location_id) p
              ON p.sku_id = l->>'sku_id' AND (l->>'location_id' IS NULL OR l->>'location_id' = p.location_id)
            WHERE a.status = ANY(:st) AND l->>'sku_id' = ANY(:k)
              AND CAST(a.payload->'decision'->>'effective_date' AS date) BETWEEN p.as_of AND :e
            GROUP BY 1, 2"""), {"k": sorted({p["sku_id"] for p in positions.values()}), "e": decision_date,
                                 "st": list(COMMITTED_UNRECONCILED)}).mappings().all()
        for r in [*supply, *committed]:
            multi = len(by_sku[r["sku_id"]]) > 1
            if r["location_id"] is None and multi:
                continue          # a location-less order line cannot be attributed to one of several sites
            key = r["sku_id"] if not multi else plan_key(r["sku_id"], r["location_id"], True)
            p = positions.get(key)
            if p is None:
                continue
            p["open_order_units"] += max(int(r["open_units"] or 0), 0)
            p["received_since_snapshot"] += int(r["received_units"] or 0)
            p["on_order"] += max(int(r["open_units"] or 0), 0)
            p["on_hand"] += int(r["received_units"] or 0)
    return positions, excluded
