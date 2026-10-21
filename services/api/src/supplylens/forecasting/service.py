"""ForecastService: validated, versioned forecast runs. Never executes model-generated code."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date

import pandas as pd
from sqlalchemy import text

from supplylens_ml.baselines import seasonal_naive
from supplylens_ml.series import dense_series

from ..db import tenant_session

SEASONAL_NAIVE = ("seasonal_naive", "1.0.0")


class ForecastError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class ForecastRun:
    run_id: uuid.UUID
    model_version_id: uuid.UUID
    origin: date
    horizon: int
    points: pd.DataFrame
    quality_flags: dict


def ensure_seasonal_naive(tenant_id, dataset_id) -> uuid.UUID:
    family, version = SEASONAL_NAIVE
    with tenant_session(tenant_id) as s:
        row = s.execute(text("SELECT id FROM model_versions WHERE family=:f AND version=:v"),
                        {"f": family, "v": version}).first()
        if row:
            return row.id
        mid = uuid.uuid4()
        s.execute(text(
            "INSERT INTO model_versions (id, tenant_id, family, version, status, dataset_id, config, "
            "code_version) VALUES (:i, :t, :f, :v, 'CHAMPION', :d, CAST(:c AS jsonb), 'supplylens_ml.baselines')"),
            {"i": mid, "t": tenant_id, "f": family, "v": version, "d": dataset_id,
             "c": json.dumps({"season": 7, "interval": "k-season-lag training errors, q0.1/q0.9",
                              "clip_negative": True})})
        return mid


def run_forecast(tenant_id, dataset_id, sku_ids: list[str], origin: date, horizon: int = 28,
                 created_by=None) -> ForecastRun:
    if not 1 <= horizon <= 90:
        raise ForecastError("invalid_horizon", "horizon must be between 1 and 90 days")
    if not sku_ids or len(sku_ids) > 200:
        raise ForecastError("invalid_selection", "select between 1 and 200 SKUs")
    with tenant_session(tenant_id) as s:
        max_day = s.execute(text("SELECT max(day) FROM sales_daily WHERE dataset_id=:d"),
                            {"d": dataset_id}).scalar()
        if max_day is None:
            raise ForecastError("no_data", "dataset has no daily sales")
        if origin > max_day:
            raise ForecastError("origin_after_data", f"origin {origin} is after last observed day {max_day}")
        daily = pd.DataFrame(s.execute(text(
            "SELECT sku_id, day, units FROM sales_daily WHERE dataset_id=:d AND sku_id = ANY(:k) "
            "AND day <= :o"), {"d": dataset_id, "k": sku_ids, "o": origin}).mappings().all())
    model_id = ensure_seasonal_naive(tenant_id, dataset_id)
    frames, flags = [], {}
    for sku in sku_ids:
        hist = dense_series(daily, sku, origin) if not daily.empty else pd.Series(dtype=float)
        if len(hist) < 28:
            flags[sku] = "insufficient_history"
            continue
        recent = hist.iloc[-56:]
        if (recent == 0).mean() > 0.8:
            flags[sku] = "intermittent"
        f = seasonal_naive(hist, horizon=horizon)
        f["sku_id"] = sku
        frames.append(f)
    points = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["day", "h", "q10", "q50", "q90", "sku_id"])
    run_id = uuid.uuid4()
    status = "SUCCEEDED" if len(frames) == len(sku_ids) else ("PARTIAL" if frames else "FAILED")
    with tenant_session(tenant_id) as s:
        s.execute(text(
            "INSERT INTO forecast_runs (id, tenant_id, model_version_id, dataset_id, origin, horizon, status, "
            "sku_ids, quality_flags, created_by) VALUES (:i,:t,:m,:d,:o,:h,:st,:k,CAST(:q AS jsonb),:u)"),
            {"i": run_id, "t": tenant_id, "m": model_id, "d": dataset_id, "o": origin, "h": horizon,
             "st": status, "k": sku_ids, "q": json.dumps(flags), "u": created_by})
        if not points.empty:
            s.execute(text(
                "INSERT INTO forecast_points (tenant_id, run_id, sku_id, day, q10, q50, q90) "
                "SELECT :t, :r, x.sku_id, x.day, x.q10, x.q50, x.q90 FROM jsonb_to_recordset(CAST(:p AS jsonb)) "
                "AS x(sku_id text, day date, q10 float8, q50 float8, q90 float8)"),
                {"t": tenant_id, "r": run_id,
                 "p": points.assign(day=points["day"].dt.strftime("%Y-%m-%d"))[
                     ["sku_id", "day", "q10", "q50", "q90"]].to_json(orient="records")})
    return ForecastRun(run_id, model_id, origin, horizon, points, flags)
