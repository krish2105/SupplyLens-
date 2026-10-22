"""Turn a sales forecast and a stock position into a replenishment need.

Default basis `leadtime_demand`: order up to the `service_level` quantile of demand over the protection interval
(supplier lead time + coverage days), from the lead-time-demand model in `leadtime_demand.py` (daily moments from the
forecast quantiles, day-to-day dependence measured from the SKU's own history, gamma window distribution).

Study S1 showed that median-based targets under-stock heavily on heavy-tailed daily sales (summed q50 of the trained
models covered only 42-50% of held-out volume). The first answer was `q90_sum`, the sum of daily q90 over the window: a
declared heuristic, not a calibrated window quantile, because it assumes every day is at its 90th percentile at once.
`leadtime_demand` replaces it as the default; `q90_sum` and `q50_plus_safety` (q50 path + `safety_days` of mean daily
q50) stay selectable so the three can be compared on the same inputs (evaluations/leadtime_demand_study.py).

Clock rules (audit F02). Only forecast days strictly after the decision date count: the coverage window is
decision_date < day <= decision_date + coverage_days (plus the lead time under `leadtime_demand`). A forecast that starts
later than the day after the decision date is rejected (the gap would be silently treated as zero demand). Under
`leadtime_demand` days beyond the forecast horizon are extrapolated and counted in `extrapolated_days`; the summed bases
cannot extrapolate, so they reject a forecast that does not cover every window day. The stockout projection walks the
same window and nothing beyond it.

Controls (audit F03). `safety_days` changes the result only under `q50_plus_safety`; `safety_days_applied` says whether
it did. Capacity (audit F04): `uncapped_required_units` keeps the demand-driven need visible when storage capacity caps
`required_units`, and `capacity_headroom_units` is the residual capacity the planner and validator must respect. Headroom
is measured against physical occupancy, on hand + on order: allocated units still occupy storage until they ship, and
scheduled receipts (including SupplyLens' own open orders) will occupy it when they arrive. It is not measured against the
inventory position, which subtracts allocations and would overstate free space.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, timedelta

from pydantic import BaseModel

from .leadtime_demand import window_demand

BASES = ("leadtime_demand", "q90_sum", "q50_plus_safety")


class Position(BaseModel):
    sku_id: str
    on_hand: int
    allocated: int
    on_order: int
    capacity: int | None = None


class NeedAssessment(BaseModel):
    sku_id: str
    available: int
    inventory_position: int
    coverage_days: int
    demand_q50: float
    demand_q90_sum_uncalibrated: float
    safety_units: int
    required_units: int
    projected_stockout: date | None
    need_by: date
    days_of_cover: float | None
    status: str
    basis: str = "leadtime_demand"
    method: str = ""
    # lead-time-demand model outputs (None under the older bases)
    service_level: float | None = None
    protection_days: int | None = None
    lead_time_days: int | None = None
    demand_mean: float | None = None
    demand_sd: float | None = None
    demand_quantile: float | None = None
    variance_inflation: float | None = None
    dependence_lag1: float | None = None
    dependence_basis: str | None = None
    extrapolated_days: int | None = None
    calibration: str | None = None
    safety_days_applied: bool = False
    uncapped_required_units: int = 0
    capacity_headroom_units: int | None = None


CALIBRATION_NOTE = "simulation-checked, not validated on real data"


def assess(pos: Position, forecast: list[dict], decision_date: date, coverage_days: int,
           safety_days: int, basis: str = "leadtime_demand", *, lead_time_days: int = 0, service_level: float = 0.9,
           acf: Sequence[float] | None = None, dependence_basis: str = "assumed default",
           lead_time_sd_days: float = 0.0) -> NeedAssessment:
    """forecast: rows with day (date), q10 (leadtime_demand only), q50, q90; days on or before decision_date are ignored."""
    if basis not in BASES:
        raise ValueError(f"unknown replenishment basis {basis!r}; expected one of {', '.join(BASES)}")
    if coverage_days < 1:
        raise ValueError("coverage_days must be at least 1")
    available = pos.on_hand - pos.allocated
    position = available + pos.on_order
    future = sorted((f for f in forecast if f["day"] > decision_date), key=lambda r: r["day"])
    if not future:
        raise ValueError(f"the forecast has no days after the decision date {decision_date}")
    first = decision_date + timedelta(days=1)
    if future[0]["day"] != first:
        raise ValueError(f"the forecast starts on {future[0]['day']}, not on {first} (the day after the decision date); "
                         "regenerate it from an origin on or before the decision date")
    ltd = None
    if basis == "leadtime_demand":
        if any("q10" not in f for f in future):
            raise ValueError("the lead-time-demand basis needs q10, q50 and q90 for every forecast day")
        protection = max(coverage_days + max(lead_time_days, 0), 1)
        end = decision_date + timedelta(days=protection)
        window = [f for f in future if f["day"] <= end]
        ltd = window_demand(window, protection, service_level, acf, dependence_basis, lead_time_sd_days)
    else:
        end = decision_date + timedelta(days=coverage_days)
        window = [f for f in future if f["day"] <= end]
        if len({f["day"] for f in window}) < coverage_days:
            raise ValueError(f"the forecast covers {len(window)} of the {coverage_days} coverage days; the {basis} basis "
                             "sums daily values and cannot extrapolate, so it needs a forecast for every day")
    q50 = sum(f["q50"] for f in window)
    q90 = sum(f["q90"] for f in window)
    mean_daily = q50 / max(len(window), 1)
    if ltd is not None:
        safety = math.ceil(max(ltd.quantile - ltd.mean, 0))
        required = max(0, math.ceil(ltd.quantile - position))
        method = (f"order up to the {ltd.service_level:.0%} quantile of demand over {ltd.protection_days} days "
                  f"(lead time {max(lead_time_days, 0)} + coverage {coverage_days}); day-to-day dependence "
                  f"inflates the variance x{ltd.variance_inflation:.2f} ({ltd.dependence_basis}); lead-time variability "
                  f"{'modelled' if lead_time_sd_days > 0 else 'not modelled (terms carry point lead times)'}")
    elif basis == "q90_sum":
        safety = math.ceil(max(q90 - q50, 0))
        required = max(0, math.ceil(q90 - position))
        method = "order up to sum of daily q90 over the window (heuristic, not a calibrated quantile; see study S1)"
    else:
        safety = math.ceil(mean_daily * safety_days)
        required = max(0, math.ceil(q50 + safety - position))
        method = "q50 path + assumed safety days"
    uncapped = required
    headroom = None
    if pos.capacity is not None:
        headroom = max(pos.capacity - (pos.on_hand + pos.on_order), 0)
        required = min(required, headroom)
    stockout, running = None, float(available)
    for f in window:
        running -= f["q50"]
        if running < 0:
            stockout = f["day"]
            break
    need_by = stockout or decision_date + timedelta(days=coverage_days)
    cover = (available / mean_daily) if mean_daily > 0 else None
    if stockout and stockout <= decision_date + timedelta(days=7):
        status = "shortage_risk"
    elif required > 0:
        status = "reorder"
    elif cover is not None and cover > 90:
        status = "excess"
    else:
        status = "healthy"
    extra = {}
    if ltd is not None:
        extra = dict(service_level=ltd.service_level, protection_days=ltd.protection_days, lead_time_days=max(lead_time_days, 0),
                     demand_mean=round(ltd.mean, 2), demand_sd=round(ltd.sd, 2), demand_quantile=round(ltd.quantile, 2),
                     variance_inflation=round(ltd.variance_inflation, 3), dependence_lag1=round(ltd.lag1, 3),
                     dependence_basis=ltd.dependence_basis, extrapolated_days=ltd.extrapolated_days,
                     calibration=CALIBRATION_NOTE)
    return NeedAssessment(sku_id=pos.sku_id, available=available, inventory_position=position,
                          coverage_days=coverage_days, demand_q50=round(q50, 2),
                          demand_q90_sum_uncalibrated=round(q90, 2), safety_units=safety,
                          required_units=required, projected_stockout=stockout, need_by=need_by,
                          days_of_cover=round(cover, 1) if cover is not None else None, status=status,
                          basis=basis, method=method, safety_days_applied=basis == "q50_plus_safety",
                          uncapped_required_units=uncapped, capacity_headroom_units=headroom, **extra)
