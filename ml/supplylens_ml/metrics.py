"""Forecast metrics. Undefined values are returned as None, never patched with epsilons."""
from __future__ import annotations

import numpy as np


def mae(y: np.ndarray, yhat: np.ndarray) -> float:
    return float(np.mean(np.abs(y - yhat)))


def mase(y: np.ndarray, yhat: np.ndarray, scale: float | None) -> float | None:
    return None if scale is None else mae(y, yhat) / scale


def pinball(y: np.ndarray, q_pred: np.ndarray, q: float) -> float:
    diff = y - q_pred
    return float(np.mean(np.maximum(q * diff, (q - 1) * diff)))


def coverage(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    return float(np.mean((y >= lo) & (y <= hi)))


def mean_width(lo: np.ndarray, hi: np.ndarray) -> float:
    return float(np.mean(hi - lo))


def crossing_rate(q10: np.ndarray, q50: np.ndarray, q90: np.ndarray) -> float:
    return float(np.mean((q10 > q50) | (q50 > q90)))
