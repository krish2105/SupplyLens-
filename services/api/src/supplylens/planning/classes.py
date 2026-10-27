"""Inventory classes and statistical safety stock (F4: ABC analysis, a safety-stock calculator and
service-level trade-offs).

ABC ranks products by their share of sales value over the last 365 days (by units when the workspace has no prices):
A = the products that make up the first 80 % of value, B = the next 15 %, C = the rest. XYZ ranks demand variability by
the coefficient of variation (CV) of weekly units over the last 52 weeks: X < 0.5, Y < 1.0, Z >= 1.0.

Safety stock for each stocked product: SS = z(service level) x sigma(daily demand, last 91 days) x sqrt(lead time).
This is the textbook cycle-service-level form: demand variability only, lead time taken as fixed (the shortest lead time
among the supplier terms in force). The holding cost of that stock uses the assumed annual holding rate of the decision
studies (25 % of unit cost). Every figure here is derived or assumed, never observed; the response says which.
"""
from __future__ import annotations

import math
from datetime import UTC, date, datetime, time
from statistics import NormalDist

import numpy as np
from sqlalchemy import text

from ..db import tenant_session
from .terms_service import applicable_terms

ABC_CUTS = (0.80, 0.95)               # cumulative value share closing A and B
XYZ_CUTS = (0.5, 1.0)                 # weekly-demand CV closing X and Y
WINDOW_DAYS, SIGMA_DAYS, WEEKS = 365, 91, 52
HOLDING_RATE_ANNUAL = 0.25            # assumed, as in the S2 decision study (ml/configs/decision_study_s2.json)
DEFAULT_POLICY = {"A": 0.98, "B": 0.95, "C": 0.90}
CURVE_LEVELS = (0.80, 0.85, 0.90, 0.95, 0.975, 0.99, 0.995)


def z_for(service_level: float) -> float:
    return NormalDist().inv_cdf(service_level)


def abc_of(cum_share_before: float) -> str:
    """Class of a product whose higher-value predecessors already make up `cum_share_before` of the total."""
    return "A" if cum_share_before < ABC_CUTS[0] else "B" if cum_share_before < ABC_CUTS[1] else "C"


def xyz_of(cv: float | None) -> str | None:
    if cv is None:
        return None
    return "X" if cv < XYZ_CUTS[0] else "Y" if cv < XYZ_CUTS[1] else "Z"


def safety_stock(z: float, sigma_daily: float, lead_time_days: float) -> float:
    return max(0.0, z) * sigma_daily * math.sqrt(max(lead_time_days, 0.0))


def classify(tenant_id, eff: date, policy: dict[str, float] | None = None, replay: bool = False) -> dict:
    """`replay`: the user chose the date, so terms are cut at the end of that day (as the exceptions do)."""
    policy = {**DEFAULT_POLICY, **(policy or {})}
    with tenant_session(tenant_id) as s:
        st = s.execute(text("SELECT currency, operational_as_of FROM tenant_settings")).first()
        value = s.execute(text("""SELECT sku_id, sum(quantity * unit_price_minor)::float AS v FROM sales_lines
            WHERE invoiced_at::date > CAST(:e AS date) - :w AND invoiced_at::date <= :e AND quantity > 0
            GROUP BY sku_id"""), {"e": eff, "w": WINDOW_DAYS}).all()
        basis = "revenue"
        if not value:
            basis = "units"
            value = s.execute(text("""SELECT sku_id, sum(units)::float AS v FROM sales_daily
                WHERE day > CAST(:e AS date) - :w AND day <= :e GROUP BY sku_id"""), {"e": eff, "w": WINDOW_DAYS}).all()
        weekly = s.execute(text("""SELECT sku_id, (CAST(:e AS date) - day) / 7 AS wk, sum(units)::float AS u FROM sales_daily
            WHERE day > CAST(:e AS date) - :n AND day <= :e GROUP BY 1, 2"""), {"e": eff, "n": WEEKS * 7}).all()
        stocked = [r[0] for r in s.execute(text("""SELECT DISTINCT sku_id FROM inventory_positions WHERE as_of <= :e"""),
                                           {"e": eff}).all()]
        daily = s.execute(text("""SELECT sku_id, CAST(:e AS date) - day AS d, sum(units)::float AS u FROM sales_daily
            WHERE sku_id = ANY(:k) AND day > CAST(:e AS date) - :n AND day <= :e GROUP BY 1, 2"""),
                          {"e": eff, "n": SIGMA_DAYS, "k": stocked}).all()
    currency = st.currency.strip() if st else None

    # ABC on value share
    value = sorted(((k, v) for k, v in value if v and v > 0), key=lambda r: (-r[1], r[0]))
    total = sum(v for _, v in value) or 1.0
    abc, cum = {}, 0.0
    for k, v in value:
        abc[k] = abc_of(cum / total)
        cum += v
    # XYZ on weekly CV (dense: weeks without sales count as zero)
    weeks: dict[str, np.ndarray] = {}
    for k, wk, u in weekly:
        if 0 <= wk < WEEKS:
            weeks.setdefault(k, np.zeros(WEEKS))[int(wk)] += u
    cv = {k: (float(w.std(ddof=1) / w.mean()) if w.mean() > 0 else None) for k, w in weeks.items()}
    matrix: dict[tuple[str, str], dict] = {}
    for k, v in value:
        key = (abc[k], xyz_of(cv.get(k)) or "Z")
        cell = matrix.setdefault(key, {"products": 0, "value": 0.0})
        cell["products"] += 1
        cell["value"] += v

    # Safety stock for stocked products
    days: dict[str, np.ndarray] = {}
    for k, d, u in daily:
        if 0 <= d < SIGMA_DAYS:
            days.setdefault(k, np.zeros(SIGMA_DAYS))[int(d)] += u
    cutoff = (st.operational_as_of if st and st.operational_as_of and not replay
              else datetime.combine(eff, time.max, tzinfo=UTC))
    lead, cost = {}, {}
    for t in applicable_terms(tenant_id, stocked, cutoff, eff).applicable if stocked else []:
        lead[t.sku_id] = min(lead.get(t.sku_id, t.lead_time_days), t.lead_time_days)
        if currency and t.currency == currency:
            cost[t.sku_id] = min(cost.get(t.sku_id, t.unit_cost_minor), t.unit_cost_minor)
    rows = []
    for k in sorted(stocked):
        series = days.get(k, np.zeros(SIGMA_DAYS))
        sigma, mean = float(series.std(ddof=1)), float(series.mean())
        cls = abc.get(k, "C")
        sl = policy[cls]
        L = lead.get(k)
        ss = safety_stock(z_for(sl), sigma, L) if L is not None else None
        rows.append({"sku_id": k, "abc": cls, "xyz": xyz_of(cv.get(k)), "cv": None if cv.get(k) is None else round(cv[k], 3),
                     "mean_daily": round(mean, 3), "sd_daily": round(sigma, 3), "lead_time_days": L,
                     "unit_cost_minor": cost.get(k), "service_level": sl,
                     "safety_stock_units": None if ss is None else math.ceil(ss),
                     "holding_cost_minor_per_year": None if ss is None or k not in cost
                     else round(math.ceil(ss) * cost[k] * HOLDING_RATE_ANNUAL)})

    def portfolio(level_of) -> dict:
        units = held = 0
        for r in rows:
            if r["lead_time_days"] is None:
                continue
            u = math.ceil(safety_stock(z_for(level_of(r)), r["sd_daily"], r["lead_time_days"]))
            units += u
            if r["unit_cost_minor"] is not None:
                held += u * r["unit_cost_minor"] * HOLDING_RATE_ANNUAL
        return {"safety_stock_units": units, "holding_cost_minor_per_year": round(held)}

    curve = [{"service_level": sl, **portfolio(lambda _r, sl=sl: sl)} for sl in CURVE_LEVELS]
    weighted = sum(r["service_level"] * r["mean_daily"] for r in rows) / (sum(r["mean_daily"] for r in rows) or 1)
    return {
        "effective_date": eff, "basis": basis, "currency": currency if basis == "revenue" else None,
        "window_days": WINDOW_DAYS, "abc_cuts": list(ABC_CUTS), "xyz_cuts": list(XYZ_CUTS),
        "products_classified": len(value),
        "matrix": [{"abc": a, "xyz": x, "products": c["products"], "value_share": round(c["value"] / total, 4)}
                   for (a, x), c in sorted(matrix.items())],
        "policy": policy, "holding_rate_annual": HOLDING_RATE_ANNUAL,
        "stocked": rows,
        "curve": curve,
        "policy_point": {"service_level": round(weighted, 4), **portfolio(lambda r: r["service_level"])},
        "value_kind": "derived",
        "assumptions": ["cycle service level, demand variability only (lead time fixed at the shortest term in force)",
                        f"holding cost {int(HOLDING_RATE_ANNUAL * 100)} % of unit cost per year (assumed)",
                        "sigma from the last 91 days of daily unit sales, days without sales counted as zero"],
    }
