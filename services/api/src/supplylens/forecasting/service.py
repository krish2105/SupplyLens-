"""ForecastService: validated, versioned forecast runs. Never executes model-generated code."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import text

from supplylens_ml.baselines import seasonal_naive
from supplylens_ml.series import dense_series

from .. import alerts, telemetry
from ..config import REPO_ROOT
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


def resolve_model(tenant_id, dataset_id, family: str | None = None) -> dict:
    """The requested family, else the registry CHAMPION, else the seasonal-naive baseline."""
    with tenant_session(tenant_id) as s:
        q = ("SELECT id, family, version, status, training_cutoff, artifact_path, artifact_sha256 FROM model_versions "
             + ("WHERE family = :f ORDER BY created_at DESC LIMIT 1" if family else
                "WHERE status = 'CHAMPION' ORDER BY created_at DESC LIMIT 1"))
        row = s.execute(text(q), {"f": family}).mappings().first()
    if row is None:
        if family not in (None, "seasonal_naive"):
            raise ForecastError("model_not_found", f"no registered model {family}")
        ensure_seasonal_naive(tenant_id, dataset_id)
        return resolve_model(tenant_id, dataset_id, "seasonal_naive")
    return dict(row)


_BOOSTERS: dict[str, list] = {}


def _artifact(model: dict, name_filter) -> tuple[Path, str]:
    arts = model["artifact_sha256"] if isinstance(model["artifact_sha256"], list) else json.loads(model["artifact_sha256"] or "[]")
    picks = [a for a in arts if name_filter(a)]
    if not picks:
        raise ForecastError("artifact_missing", f"model {model['family']} has no artifact")
    return [(REPO_ROOT / model["artifact_path"] / a["file"], a["sha256"]) for a in picks]


def _verify(path: Path, expected: str) -> None:
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ForecastError("artifact_untrusted", f"artifact {path.name} missing or hash mismatch")


def _trained_points(model: dict, daily: pd.DataFrame, sku_ids: list[str], origin: date, horizon: int):
    from supplylens_ml.panel import WINDOW, build_panel, rearrange, save_panel
    flags, ok = {}, []
    for sku in sku_ids:
        rows = daily[daily["sku_id"] == sku]
        if rows.empty or (pd.Timestamp(origin) - pd.to_datetime(rows["day"]).min()).days + 1 < WINDOW:
            flags[sku] = "insufficient_history"
        else:
            ok.append(sku)
    if not ok:
        return pd.DataFrame(columns=["day", "h", "q10", "q50", "q90", "sku_id"]), flags
    panel = build_panel(daily[daily["sku_id"].isin(ok)], pd.to_datetime(daily["day"]).min(), origin).subset(ok)
    i = len(panel.dates) - 1
    if model["family"] == "lightgbm_quantile":
        import lightgbm as lgb
        from supplylens_ml.models import predict_lgbm
        files = sorted(_artifact(model, lambda a: a["file"].startswith("lightgbm")), key=lambda x: x[0].name)
        key = ",".join(h for _, h in files)
        if key not in _BOOSTERS:
            for f, h in files:
                _verify(f, h)
            _BOOSTERS[key] = [lgb.Booster(model_file=str(f)) for f, _ in files]  # q10, q50, q90 by name
        raw = predict_lgbm(_BOOSTERS[key], panel, i)
    else:  # tcn_quantile: PyTorch runs in a separate process (OpenMP conflict with LightGBM)
        (f, h), = _artifact(model, lambda a: a.get("seed") == 0)
        _verify(f, h)
        with tempfile.TemporaryDirectory() as td:
            pnl, out = Path(td) / "p.npz", Path(td) / "y.npy"
            save_panel(panel, pnl)
            r = subprocess.run([sys.executable, "-m", "supplylens_ml.tcn", "predict", "--panel", str(pnl), "--index",
                                str(i), "--model", str(f), "--model-sha256", h, "--pred-out", str(out)],
                               capture_output=True, text=True, timeout=120)
            if r.returncode:
                raise ForecastError("model_failed", r.stderr[-500:])
            raw = np.load(out)
    q = rearrange(raw)[:, :horizon, :]
    frames = []
    for j, sku in enumerate(panel.skus):
        frames.append(pd.DataFrame({"day": [pd.Timestamp(origin) + pd.Timedelta(days=h) for h in range(1, horizon + 1)],
                                    "h": range(1, horizon + 1), "q10": q[j, :, 0], "q50": q[j, :, 1], "q90": q[j, :, 2],
                                    "sku_id": sku}))
    return pd.concat(frames, ignore_index=True), flags


def run_forecast(tenant_id, dataset_id, sku_ids: list[str], origin: date, horizon: int = 28,
                 created_by=None, model_family: str | None = None, allow_baseline_fallback: bool = False) -> ForecastRun:
    """Forecast with the requested model or the champion. With `allow_baseline_fallback`, a champion that
    cannot serve this origin (trained later, or horizon too long) is replaced by seasonal naive and flagged."""
    with telemetry.span("forecast.run", **{"tenant.id": str(tenant_id), "forecast.skus": len(sku_ids),
                                           "forecast.horizon": horizon}):
        return _run_with_fallback(tenant_id, dataset_id, sku_ids, origin, horizon, created_by, model_family,
                                  allow_baseline_fallback)


def _run_with_fallback(tenant_id, dataset_id, sku_ids, origin, horizon, created_by, model_family,
                       allow_baseline_fallback) -> ForecastRun:
    try:
        return _run(tenant_id, dataset_id, sku_ids, origin, horizon, created_by, model_family)
    except ForecastError as e:
        if not allow_baseline_fallback or e.code not in ("model_trained_after_origin", "horizon_exceeds_model"):
            raise
        run = _run(tenant_id, dataset_id, sku_ids, origin, horizon, created_by, "seasonal_naive")
        run.quality_flags["_model"] = f"champion not usable here ({e.code}); seasonal_naive baseline used"
        with tenant_session(tenant_id) as s:
            s.execute(text("UPDATE forecast_runs SET quality_flags = CAST(:q AS jsonb) WHERE id = :i"),
                      {"q": json.dumps(run.quality_flags), "i": run.run_id})
        return run


def _run(tenant_id, dataset_id, sku_ids, origin, horizon, created_by, model_family) -> ForecastRun:
    if not 1 <= horizon <= 90:
        raise ForecastError("invalid_horizon", "horizon must be between 1 and 90 days")
    if not sku_ids or len(sku_ids) > 200:
        raise ForecastError("invalid_selection", "select between 1 and 200 SKUs")
    model = resolve_model(tenant_id, dataset_id, model_family)
    trained = model["family"] != "seasonal_naive"
    if trained and horizon > 28:
        raise ForecastError("horizon_exceeds_model", "trained models forecast at most 28 days")
    if trained and model["training_cutoff"] and origin < model["training_cutoff"]:
        # The model has seen labels after this origin: a replay with it would leak the future.
        raise ForecastError("model_trained_after_origin",
                            f"{model['family']} was trained on data up to {model['training_cutoff']}; "
                            f"use seasonal_naive to replay origins before that date")
    with tenant_session(tenant_id) as s:
        max_day = s.execute(text("SELECT max(day) FROM sales_daily WHERE dataset_id=:d"),
                            {"d": dataset_id}).scalar()
        if max_day is None:
            raise ForecastError("no_data", "dataset has no daily sales")
        if origin > max_day:
            raise ForecastError("origin_after_data", f"origin {origin} is after last observed day {max_day}")
        daily = pd.DataFrame(s.execute(text(
            "SELECT sku_id, day, units FROM sales_daily WHERE dataset_id=:d AND sku_id = ANY(:k) "
            "AND day <= :o"), {"d": dataset_id, "k": sku_ids, "o": origin}).mappings().all(),
            columns=["sku_id", "day", "units"])
    model_id = model["id"]
    frames, flags = [], {}
    if trained:
        try:
            pts, flags = _trained_points(model, daily, sku_ids, origin, horizon)
        except ForecastError as e:
            if e.code in ("artifact_untrusted", "artifact_missing", "model_failed"):
                alerts.raise_alert(tenant_id, "model_unavailable", f"model_unavailable:artifact:{model_id}",
                                   f"{model['family']} {model.get('version', '')} cannot serve forecasts ({e.code})",
                                   {"model_id": str(model_id), "family": model["family"], "error": str(e)[:300]}, "high")
            raise
        if not pts.empty:
            frames.append(pts)
    else:
        for sku in sku_ids:
            hist = dense_series(daily, sku, origin) if not daily.empty else pd.Series(dtype=float)
            if len(hist) < 28:
                flags[sku] = "insufficient_history"
                continue
            f = seasonal_naive(hist, horizon=horizon)
            f["sku_id"] = sku
            frames.append(f)
    for sku in sku_ids:
        recent = daily[daily["sku_id"] == sku]
        if sku not in flags and len(recent) and (pd.to_datetime(recent["day"]) > pd.Timestamp(origin) - pd.Timedelta(days=56)).sum() < 12:
            flags[sku] = "intermittent"
    points = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["day", "h", "q10", "q50", "q90", "sku_id"])
    n_ok = points["sku_id"].nunique() if not points.empty else 0
    run_id = uuid.uuid4()
    status = "SUCCEEDED" if n_ok == len(sku_ids) else ("PARTIAL" if n_ok else "FAILED")
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
