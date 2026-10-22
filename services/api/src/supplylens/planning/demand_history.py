"""Day-to-day demand dependence (autocorrelation curve) per SKU, measured from recorded sales, for the lead-time-demand model."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import text

from supplylens_opt.leadtime_demand import estimate_dependence, pooled_dependence

from ..db import tenant_session

HISTORY_DAYS = 120


def dependence_by_sku(tenant_id: uuid.UUID, dataset_id: uuid.UUID | str, skus: list[str], as_of: date,
                      days: int = HISTORY_DAYS) -> dict[str, tuple[list[float] | None, str]]:
    """{sku: (autocorrelations at lags 1.., basis)}. basis is "history" (own sales), "pooled" (lag-wise median over the
    SKUs that have enough history) or "assumed default" (None: the model's declared default applies). Only recorded days
    are used: a missing day is not a zero."""
    with tenant_session(tenant_id) as s:
        rows = s.execute(text("""SELECT sku_id, day, sum(units)::float AS units, extract(isodow FROM day)::int - 1 AS dow
            FROM sales_daily WHERE dataset_id = :d AND sku_id = ANY(:k) AND day > CAST(:a AS date) - :n AND day <= :a
            GROUP BY sku_id, day ORDER BY sku_id, day"""), {"d": dataset_id, "k": skus, "a": as_of, "n": days}).all()
    series: dict[str, tuple[list[float], list[int]]] = {}
    for r in rows:
        v, w = series.setdefault(r.sku_id, ([], []))
        v.append(r.units)
        w.append(r.dow)
    own = {k: estimate_dependence(v, w) for k, (v, w) in series.items()}
    pooled = pooled_dependence([e[0] for e in own.values() if e is not None])
    out: dict[str, tuple[list[float] | None, str]] = {}
    for k in skus:
        e = own.get(k)
        if e is not None:
            out[k] = (list(e[0]), "history")
        elif pooled is not None:
            out[k] = (list(pooled), "pooled")
        else:
            out[k] = (None, "assumed default")
    return out
