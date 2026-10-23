"""Forecast monitoring: realized accuracy, shadow baseline, calibration and demand drift (Phase 5, MLOps).

Every forecast run is stored (forecast_points). Once sales for those days are known, this compares what each model
predicted with what was sold, and recomputes the seasonal-naive baseline for the SAME products, origins and days from the
history available at each origin (a shadow comparison that needs no extra storage). It also measures demand drift: a
population stability index (PSI) between each product's daily units in the latest window and in the year before the
serving model's training cutoff.

The report recommends; it never acts. Rolling back (setting another model CHAMPION) stays an audited administrative
decision behind the promotion gate (governance.py). Sales are fulfilled units, not unconstrained demand, and the first
day after an origin is the earliest that can be scored.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text

from supplylens_ml.baselines import seasonal_naive
from supplylens_ml.series import dense_series

from ..db import tenant_session

MIN_POINTS = 200            # fewer scored points than this: "insufficient evidence", never a recommendation
DEGRADED_RATIO = 1.0        # champion MAE / shadow-baseline MAE above this on enough points: recommend rollback
COVERAGE_BAND = (0.65, 0.95)
PSI_DRIFT = 0.25            # conventional threshold for a material shift


def psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float | None:
    """Population stability index of `actual` against `expected` on the expected distribution's quantile bins."""
    expected, actual = expected[~np.isnan(expected)], actual[~np.isnan(actual)]
    if len(expected) < 28 or len(actual) < 14:
        return None
    edges = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        edges = np.array([-np.inf, np.median(expected), np.inf])
    edges[0], edges[-1] = -np.inf, np.inf
    e = np.histogram(expected, edges)[0] / len(expected)
    a = np.histogram(actual, edges)[0] / len(actual)
    e, a = np.clip(e, 1e-4, None), np.clip(a, 1e-4, None)
    return float(np.sum((a - e) * np.log(a / e)))


def report(tenant_id, dataset_id, as_of: date, lookback_days: int = 90, drift_window: int = 28) -> dict:
    with tenant_session(tenant_id) as s:
        runs = pd.DataFrame(s.execute(text("""
            SELECT r.id AS run_id, r.origin, m.id AS model_id, m.family, m.version, m.status, m.training_cutoff
            FROM forecast_runs r JOIN model_versions m ON m.id = r.model_version_id
            WHERE r.dataset_id = :d AND r.origin BETWEEN :lo AND :hi"""),
            {"d": dataset_id, "lo": as_of - timedelta(days=lookback_days), "hi": as_of - timedelta(days=1)}).mappings().all())
        if runs.empty:
            points = pd.DataFrame(columns=["run_id", "sku_id", "day", "q10", "q50", "q90"])
        else:
            points = pd.DataFrame(s.execute(text("""SELECT run_id, sku_id, day, q10, q50, q90 FROM forecast_points
                WHERE run_id = ANY(:r) AND day <= :a"""), {"r": [str(r) for r in runs["run_id"]], "a": as_of}).mappings().all())
        skus = sorted(set(points["sku_id"])) if not points.empty else []
        daily = pd.DataFrame(s.execute(text("""SELECT sku_id, day, sum(units)::float AS units FROM sales_daily
            WHERE dataset_id = :d AND sku_id = ANY(:k) AND day <= :a GROUP BY sku_id, day"""),
            {"d": dataset_id, "k": skus, "a": as_of}).mappings().all(), columns=["sku_id", "day", "units"])
        champion = s.execute(text("""SELECT family, version, training_cutoff FROM model_versions WHERE status = 'CHAMPION'
            AND (dataset_id = :d OR family = 'seasonal_naive') ORDER BY (family = 'seasonal_naive'), created_at DESC LIMIT 1"""),
            {"d": dataset_id}).mappings().first()
    out = {"as_of": as_of.isoformat(), "lookback_days": lookback_days, "champion": dict(champion) if champion else None,
           "models": {}, "drift": None, "recommendations": [], "notes": [
               "Sales are fulfilled units (censored by stock-outs), not unconstrained demand.",
               "The shadow baseline is recomputed from history available at each forecast origin."]}
    if points.empty:
        out["recommendations"].append("no scored forecasts in the window: nothing to judge")
        return out
    runs["run_id"], points["run_id"] = runs["run_id"].astype(str), points["run_id"].astype(str)
    points = points.merge(runs[["run_id", "origin", "family", "version"]], on="run_id")
    points["day"] = pd.to_datetime(points["day"]).dt.date
    actual = {(r.sku_id, r.day): r.units for r in daily.assign(day=pd.to_datetime(daily["day"]).dt.date).itertuples()}
    sold = {sku for sku, _ in actual}
    points["y"] = [actual.get((k, d), 0.0 if k in sold else np.nan) for k, d in zip(points["sku_id"], points["day"], strict=True)]
    points = points.dropna(subset=["y"])
    # shadow baseline: seasonal naive from the history up to each (run origin, SKU)
    shadow = {}
    for (origin, sku), _ in points.groupby(["origin", "sku_id"]):
        hist = dense_series(daily, sku, origin)
        if len(hist) >= 28:
            f = seasonal_naive(hist, horizon=90)
            shadow.update({(origin, sku, d.date()): v for d, v in zip(f["day"], f["q50"], strict=True)})
    points["baseline_q50"] = [shadow.get((o, k, d), np.nan) for o, k, d in zip(points["origin"], points["sku_id"], points["day"], strict=True)]
    for (fam, ver), g in points.groupby(["family", "version"]):
        both = g.dropna(subset=["baseline_q50"])
        mae = float(np.mean(np.abs(g["y"] - g["q50"])))
        base_mae = float(np.mean(np.abs(both["y"] - both["baseline_q50"]))) if len(both) else None
        model_mae_same = float(np.mean(np.abs(both["y"] - both["q50"]))) if len(both) else None
        cov = float(np.mean((g["y"] >= g["q10"]) & (g["y"] <= g["q90"])))
        entry = {"points": int(len(g)), "products": int(g["sku_id"].nunique()), "runs": int(g["run_id"].nunique()),
                 "mae": mae, "coverage_80": cov, "median_to_volume": float(g["q50"].sum() / g["y"].sum()) if g["y"].sum() else None,
                 "shadow_baseline_mae_same_points": base_mae, "mae_same_points": model_mae_same,
                 "ratio_to_baseline": (model_mae_same / base_mae) if base_mae else None}
        out["models"][f"{fam} {ver}"] = entry
        if fam == "seasonal_naive":
            continue
        if len(both) < MIN_POINTS:
            out["recommendations"].append(f"{fam} {ver}: {len(both)} scored points; at least {MIN_POINTS} are needed to judge")
        elif entry["ratio_to_baseline"] and entry["ratio_to_baseline"] > DEGRADED_RATIO:
            out["recommendations"].append(f"{fam} {ver}: realized MAE {entry['ratio_to_baseline']:.2f}x the shadow seasonal-naive "
                                          "baseline on the same points; consider rolling back to the baseline (audited)")
        if len(g) >= MIN_POINTS and not COVERAGE_BAND[0] <= cov <= COVERAGE_BAND[1]:
            out["recommendations"].append(f"{fam} {ver}: realized 80% coverage {cov:.0%} is outside {COVERAGE_BAND}; "
                                          "recalibrate the intervals before relying on q10/q90")
    # demand drift against the serving model's training year
    cutoff = (champion or {}).get("training_cutoff") or (as_of - timedelta(days=drift_window))
    values = []
    for sku in skus:
        hist = dense_series(daily, sku, as_of)
        ref = hist[(hist.index > pd.Timestamp(cutoff) - pd.Timedelta(days=365)) & (hist.index <= pd.Timestamp(cutoff))]
        cur = hist[hist.index > pd.Timestamp(as_of) - pd.Timedelta(days=drift_window)]
        v = psi(ref.to_numpy(dtype=float), cur.to_numpy(dtype=float))
        if v is not None:
            values.append(v)
    if values:
        share = float(np.mean(np.array(values) > PSI_DRIFT))
        out["drift"] = {"products_measured": len(values), "median_psi": float(np.median(values)),
                        "share_above_threshold": share, "threshold": PSI_DRIFT, "reference_end": str(cutoff)}
        if share > 0.5:
            out["recommendations"].append(f"demand drift: {share:.0%} of products shifted (PSI > {PSI_DRIFT}) since the "
                                          "model's training year; schedule a retraining study")
    if not out["recommendations"]:
        out["recommendations"].append("no action: no model is worse than the shadow baseline and intervals are in band")
    return out
