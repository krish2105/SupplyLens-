"""Forecast metrics. Undefined values are returned as None, never patched with epsilons."""
from __future__ import annotations

from .lazy import LazyModule

np = LazyModule("numpy")



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


# Standard point metrics (F6). MAPE is undefined where an actual is zero (UCI does not trade on Saturdays), so it
# is computed over non-zero actuals only and returns None when there are none; WAPE is the scale-free metric to compare.
def rmse(y: np.ndarray, yhat: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y - yhat) ** 2)))


def wape(y: np.ndarray, yhat: np.ndarray) -> float | None:
    total = float(np.sum(np.abs(y)))
    return None if total == 0 else float(np.sum(np.abs(y - yhat)) / total)


def mape(y: np.ndarray, yhat: np.ndarray) -> float | None:
    nz = y != 0
    return None if not nz.any() else float(np.mean(np.abs((y[nz] - yhat[nz]) / y[nz])))
