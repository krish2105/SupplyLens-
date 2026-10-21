"""Turn a sales forecast and a stock position into a replenishment need.

Default basis `q90_sum`: order up to the sum of daily q90 over the coverage window. Study S1
showed that median-based targets under-stock heavily on heavy-tailed daily sales (summed q50 of
the trained models covered only 42-50% of held-out volume). Summing daily quantiles is NOT a
calibrated lead-time quantile (temporal dependence); it is a declared heuristic chosen on
simulated evidence. `q50_plus_safety` (q50 path + `safety_days` of mean daily q50) remains available.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from pydantic import BaseModel


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
    basis: str = "q90_sum"
    method: str = ""


def assess(pos: Position, forecast: list[dict], decision_date: date, coverage_days: int,
           safety_days: int, basis: str = "q90_sum") -> NeedAssessment:
    """forecast: rows with day (date), q50, q90 starting after decision_date."""
    available = pos.on_hand - pos.allocated
    position = available + pos.on_order
    window = [f for f in forecast if f["day"] <= decision_date + timedelta(days=coverage_days)]
    q50 = sum(f["q50"] for f in window)
    q90 = sum(f["q90"] for f in window)
    mean_daily = q50 / max(len(window), 1)
    if basis == "q90_sum":
        safety = math.ceil(max(q90 - q50, 0))
        required = max(0, math.ceil(q90 - position))
        method = "order up to sum of daily q90 over the window (heuristic, not a calibrated quantile; see study S1)"
    else:
        safety = math.ceil(mean_daily * safety_days)
        required = max(0, math.ceil(q50 + safety - position))
        method = "q50 path + assumed safety days"
    if pos.capacity is not None:
        required = min(required, max(pos.capacity - position, 0))
    stockout, running = None, float(available)
    for f in sorted(forecast, key=lambda r: r["day"]):
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
    return NeedAssessment(sku_id=pos.sku_id, available=available, inventory_position=position,
                          coverage_days=coverage_days, demand_q50=round(q50, 2),
                          demand_q90_sum_uncalibrated=round(q90, 2), safety_units=safety,
                          required_units=required, projected_stockout=stockout, need_by=need_by,
                          days_of_cover=round(cover, 1) if cover is not None else None, status=status,
                          basis=basis, method=method)
