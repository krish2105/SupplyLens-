"""Seasonal naive and LightGBM quantile models (no PyTorch here).

LightGBM and PyTorch ship different OpenMP runtimes that crash when loaded in one process,
so the TCN lives in `supplylens_ml.tcn` and runs in its own process.
All models return raw quantile arrays of shape (S, H, 3) for one origin; crossing is measured
on raw output and `panel.rearrange` is applied identically before scoring.
"""
from __future__ import annotations

import math
import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd

from .panel import HORIZON, QUANTILES, WINDOW, Panel, scale_at

warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*(empty slice|All-NaN|Degrees of freedom).*")

# ---------------------------------------------------------------- seasonal naive


def seasonal_naive_panel(panel: Panel, i: int, horizon: int = HORIZON, season: int = 7,
                         error_lookback: int = 365) -> np.ndarray:
    y = panel.y
    out = np.zeros((y.shape[1], horizon, 3))
    lo_hist = max(0, i - error_lookback + 1)
    for h in range(1, horizon + 1):
        k = math.ceil(h / season)
        point = y[i + 1 - k * season + (h - 1) % season]
        lag = k * season
        hist = y[lo_hist: i + 1]
        errs = hist[lag:] - hist[:-lag]
        lo, hi = np.nanquantile(errs, [0.1, 0.9], axis=0)
        out[:, h - 1, 0] = point + lo
        out[:, h - 1, 1] = point
        out[:, h - 1, 2] = point + hi
    return np.nan_to_num(out, nan=0.0)

# ---------------------------------------------------------------- LightGBM features

FEATURES = ["h", "t_dow", "t_month", "t_dom", "days_to_xmas", "log_scale", "age",
            *[f"lag_{k}" for k in range(1, 8)], "mean_7", "mean_14", "mean_28", "mean_56", "std_28",
            "zero_frac_28", "max_28", "days_since_sale", "sdow_mean_4", "sdow_last", "trend_28"]


def _xmas_gap(d: pd.Timestamp) -> int:
    x = pd.Timestamp(year=d.year, month=12, day=25)
    if d > x:
        x = pd.Timestamp(year=d.year + 1, month=12, day=25)
    return int((x - d).days)


def lgbm_features(panel: Panel, i: int, horizon: int = HORIZON) -> tuple[pd.DataFrame, np.ndarray]:
    """Rows for every (series, h) at origin i, using rows <= i only. Returns (X, scale)."""
    y = panel.y
    S = y.shape[1]
    sc = scale_at(panel, i)
    w = y[i - WINDOW + 1: i + 1] / sc  # (56, S) scaled
    first_idx = np.argmax(~np.isnan(y), axis=0)
    base = {
        "log_scale": np.log1p(sc), "age": np.minimum(i - first_idx, 730),
        **{f"lag_{k}": w[-k] for k in range(1, 8)},
        "mean_7": np.nanmean(w[-7:], 0), "mean_14": np.nanmean(w[-14:], 0), "mean_28": np.nanmean(w[-28:], 0),
        "mean_56": np.nanmean(w, 0), "std_28": np.nanstd(w[-28:], 0), "zero_frac_28": np.nanmean(w[-28:] == 0, 0),
        "max_28": np.nanmax(w[-28:], 0), "trend_28": np.nanmean(w[-14:], 0) - np.nanmean(w[-28:-14], 0),
    }
    sold = (y[: i + 1] > 0)
    last_sale = np.where(sold.any(0), i - (sold.shape[0] - 1 - np.argmax(sold[::-1], 0)), 999)
    base["days_since_sale"] = np.minimum(last_sale, 56)
    rows = []
    origin = panel.dates[i]
    for h in range(1, horizon + 1):
        t = origin + pd.Timedelta(days=h)
        ks = range(math.ceil(h / 7), math.ceil(h / 7) + 4)
        same = np.stack([y[i + h - 7 * k] for k in ks]) / sc
        d = {**base, "h": np.full(S, h), "t_dow": np.full(S, t.dayofweek), "t_month": np.full(S, t.month),
             "t_dom": np.full(S, t.day), "days_to_xmas": np.full(S, _xmas_gap(t)),
             "sdow_mean_4": np.nanmean(same, 0), "sdow_last": same[0]}
        rows.append(pd.DataFrame(d))
    X = pd.concat(rows, ignore_index=True)[FEATURES]  # order: h-major, then series
    return X, sc


def lgbm_training_set(panel: Panel, origins: list[int], horizon: int = HORIZON):
    Xs, ys = [], []
    for i in origins:
        X, sc = lgbm_features(panel, i, horizon)
        lab = panel.y[i + 1: i + 1 + horizon] / sc  # (H, S) -> flatten h-major to match X
        # Series must be observable for the whole input window (no pre-launch rows).
        started = ~np.isnan(panel.y[i - WINDOW + 1])
        lab = np.where(started[None, :], lab, np.nan)
        Xs.append(X)
        ys.append(lab.reshape(-1))
    X = pd.concat(Xs, ignore_index=True)
    yv = np.concatenate(ys)
    ok = ~np.isnan(yv)
    return X[ok].reset_index(drop=True), yv[ok]


LGBM_PARAMS = {"learning_rate": 0.05, "num_leaves": 31, "min_data_in_leaf": 200, "feature_fraction": 0.8,
               "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 1.0, "verbose": -1, "num_threads": 8}


def train_lgbm(X: pd.DataFrame, y: np.ndarray, seed: int, rounds: int = 400, params: dict | None = None):
    boosters = []
    for q in QUANTILES:
        p = {**LGBM_PARAMS, **(params or {}), "objective": "quantile", "alpha": q, "seed": seed}
        boosters.append(lgb.train(p, lgb.Dataset(X, y, categorical_feature=["t_dow"], free_raw_data=False),
                                  num_boost_round=rounds))
    return boosters


def predict_lgbm(boosters, panel: Panel, i: int, horizon: int = HORIZON) -> np.ndarray:
    X, sc = lgbm_features(panel, i, horizon)
    S = panel.y.shape[1]
    out = np.zeros((S, horizon, 3))
    for qi, b in enumerate(boosters):
        pred = b.predict(X).reshape(horizon, S).T  # (S, H)
        out[:, :, qi] = pred * sc[:, None]
    return out
