"""Stock positions for planning: the latest snapshot per SKU, plus SupplyLens' own open orders and receipts.

Grain (audit S21). Planning is per SKU at a single location. A SKU whose latest snapshots sit at more than one location is
not collapsed into one number: it is excluded with an explicit reason, because adding stock across sites would hide a
shortage at one of them. SKU-location planning is a declared limit of this pilot slice.

Open supply (audit S12). The imported snapshot is the source system's view and never contains orders SupplyLens placed.
For each SKU the position adds, from purchase_order_lines, the units still open on SupplyLens orders dated on or after
the snapshot date and on or before the decision date, and moves units received in that interval from on-order to
on-hand. Business dates are used throughout (the research workspaces run on a simulated clock). Cancelled units release
the open quantity. Orders dated before the snapshot are assumed to be inside it already.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import text

MAX_SKUS_PER_RUN = 60   # declared pilot limit for one agent run or scenario (see DECISIONS D-043)


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
    """Return ({sku: position}, {sku: reason not assessed}). `s` is a tenant session."""
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
        elif len(snaps) > 1:
            excluded[sku] = (f"held at {len(snaps)} locations ({', '.join(x['location_id'] for x in snaps)}); "
                             "SKU-location planning is not supported in this pilot, so the SKU is not assessed")
        else:
            positions[sku] = {**snaps[0], "open_order_units": 0, "received_since_snapshot": 0}
    if positions:
        supply = s.execute(text("""
            SELECT l.sku_id, min(p.as_of) AS snap,
              sum(CASE WHEN l.ordered_on BETWEEN p.as_of AND :e
                       THEN l.ordered_units - l.cancelled_units
                            - COALESCE((SELECT sum(r.quantity) FROM receipts r WHERE r.po_line_id = l.id
                                        AND r.received_on <= :e), 0) ELSE 0 END) AS open_units,
              sum(CASE WHEN l.ordered_on BETWEEN p.as_of AND :e
                       THEN COALESCE((SELECT sum(r.quantity) FROM receipts r WHERE r.po_line_id = l.id
                                      AND r.received_on BETWEEN p.as_of AND :e), 0) ELSE 0 END) AS received_units
            FROM purchase_order_lines l
            JOIN (SELECT sku_id, max(as_of) AS as_of FROM inventory_positions
                  WHERE sku_id = ANY(:k) AND as_of <= :e GROUP BY sku_id) p ON p.sku_id = l.sku_id
            WHERE l.sku_id = ANY(:k) GROUP BY l.sku_id"""), {"k": list(positions), "e": decision_date}).mappings()
        for r in supply:
            p = positions[r["sku_id"]]
            p["open_order_units"] = max(int(r["open_units"] or 0), 0)
            p["received_since_snapshot"] = int(r["received_units"] or 0)
            p["on_order"] += p["open_order_units"]
            p["on_hand"] += p["received_since_snapshot"]
    return positions, excluded
