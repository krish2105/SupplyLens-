"""Seasonal-naive baseline with interval estimates from training-period errors only."""
from __future__ import annotations

import math

from .lazy import LazyModule

np = LazyModule("numpy")
pd = LazyModule("pandas")

QUANTILES = (0.1, 0.5, 0.9)


def seasonal_naive(history: pd.Series, horizon: int = 28, season: int = 7) -> pd.DataFrame:
    """Forecast days origin+1..origin+horizon where origin is history's last index.

    Point (q50): value on the same weekday in the last observed season, for every horizon (the last
    observed week repeats; it is never a value from k seasons back). Interval: for k = ceil(h/season) seasons ahead, empirical 10%/90% quantiles of the
    k-season-lag errors y_t - y_{t-k*season} computed on `history` only (no future data).
    Negative bounds are clipped to zero, applied identically at every origin.
    """
    if len(history) < season:
        raise ValueError("history shorter than one season")
    y = history.to_numpy(dtype=float)
    origin = history.index[-1]
    rows = []
    for h in range(1, horizon + 1):
        k = math.ceil(h / season)
        point = y[len(y) - season + (h - 1) % season]
        lag = k * season
        errs = y[lag:] - y[:-lag] if len(y) > lag else np.array([0.0])
        lo, hi = np.quantile(errs, [0.1, 0.9])
        rows.append({
            "day": origin + pd.Timedelta(days=h),
            "h": h,
            "q10": max(point + lo, 0.0),
            "q50": max(point, 0.0),
            "q90": max(point + hi, 0.0),
        })
    out = pd.DataFrame(rows)
    out["q10"] = np.minimum(out["q10"], out["q50"])
    out["q90"] = np.maximum(out["q90"], out["q50"])
    return out


def mase_scale(train: pd.Series, season: int = 7) -> float | None:
    """Mean absolute seasonal difference on training data; None when undefined (zero/short)."""
    y = train.to_numpy(dtype=float)
    if len(y) <= season:
        return None
    scale = float(np.mean(np.abs(y[season:] - y[:-season])))
    return scale if scale > 0 else None
