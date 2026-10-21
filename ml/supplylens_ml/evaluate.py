"""Forecast evaluation (ML-005). Undefined MASE is reported with counts, never patched."""
from __future__ import annotations

import numpy as np

from .panel import QUANTILES, rearrange


def crossing_rate(raw: np.ndarray) -> float:
    return float(np.mean((raw[..., 0] > raw[..., 1]) | (raw[..., 1] > raw[..., 2])))


def pinball(y: np.ndarray, q: np.ndarray, tau: float) -> np.ndarray:
    e = y - q
    return np.maximum(tau * e, (tau - 1) * e)


def score(raw: np.ndarray, y: np.ndarray, mscale: np.ndarray) -> dict:
    """raw: (S, H, 3) model output; y: (S, H) actuals; mscale: (S,) MASE denominators (NaN = undefined)."""
    cross = crossing_rate(raw)
    q = rearrange(raw)
    valid = ~np.isnan(y)
    ae = np.abs(y - q[..., 1])
    per_series_mae = np.nanmean(np.where(valid, ae, np.nan), axis=1)
    defined = ~np.isnan(mscale)
    per_series_mase = np.where(defined, per_series_mae / np.where(defined, mscale, 1), np.nan)
    pin = {f"q{int(t * 100):02d}": float(np.nanmean(np.where(valid, pinball(y, q[..., k], t), np.nan)))
           for k, t in enumerate(QUANTILES)}
    pin_by_h = {f"q{int(t * 100):02d}": np.nanmean(np.where(valid, pinball(y, q[..., k], t), np.nan), axis=0).round(4).tolist()
                for k, t in enumerate(QUANTILES)}
    inside = (y >= q[..., 0]) & (y <= q[..., 2])
    return {
        "series": int(y.shape[0]), "points": int(valid.sum()),
        "mae": float(np.nanmean(per_series_mae)),
        "mase": float(np.nanmean(per_series_mase)) if defined.any() else None,
        "mase_defined_series": int(defined.sum()), "mase_undefined_series": int((~defined).sum()),
        "pinball": pin, "pinball_mean": float(np.mean(list(pin.values()))), "pinball_by_horizon": pin_by_h,
        "coverage_80": float(np.mean(inside[valid])), "width_80": float(np.nanmean((q[..., 2] - q[..., 0])[valid])),
        "crossing_rate_raw": cross,
        "per_series_mae": per_series_mae.tolist(),
    }


def paired_bootstrap(a: np.ndarray, b: np.ndarray, n: int = 2000, seed: int = 0) -> dict:
    """Mean per-series difference (a - b) with a series-level bootstrap 95% interval.

    Resampling whole series keeps the 28 dependent horizon errors of a series together.
    """
    d = np.asarray(a) - np.asarray(b)
    d = d[~np.isnan(d)]
    rng = np.random.default_rng(seed)
    boots = rng.choice(d, size=(n, len(d)), replace=True).mean(axis=1)
    lo, hi = np.quantile(boots, [0.025, 0.975])
    return {"mean_diff": float(d.mean()), "ci95": [float(lo), float(hi)], "n_series": int(len(d)),
            "share_a_better": float(np.mean(d < 0))}
