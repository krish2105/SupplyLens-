"""Wide daily panel (dates x SKUs) with explicit availability.

Values before a SKU's first recorded sale are NaN (the product was not observable);
after it, days without sales are 0 ("no recorded sales"). All feature functions take
an origin row index `i` and read only rows <= i.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

HORIZON = 28
WINDOW = 56
QUANTILES = (0.1, 0.5, 0.9)


@dataclass
class Panel:
    dates: pd.DatetimeIndex
    skus: list[str]
    y: np.ndarray  # shape (T, S), float64, NaN before first sale

    def idx(self, day) -> int:
        return int(self.dates.get_loc(pd.Timestamp(day)))

    def subset(self, skus: list[str]) -> "Panel":
        cols = [self.skus.index(s) for s in skus]
        return Panel(self.dates, list(skus), self.y[:, cols])


def build_panel(daily: pd.DataFrame, start, end) -> Panel:
    """daily: columns sku_id, day, units (gold table)."""
    dates = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
    wide = daily.assign(day=pd.to_datetime(daily["day"])).pivot_table(
        index="day", columns="sku_id", values="units", aggfunc="sum").reindex(dates)
    first = wide.notna().idxmax()
    y = wide.to_numpy(dtype=float, copy=True)
    for j, f in enumerate(first):
        k = dates.get_loc(f)
        col = y[:, j]
        col[k:] = np.nan_to_num(col[k:], nan=0.0)
        col[:k] = np.nan
    return Panel(dates, list(wide.columns), y)


def select_cohort(panel: Panel, selection_end, lookback_days: int = 365, min_selling_days: int = 150,
                  max_n: int | None = None) -> list[str]:
    """Cohort chosen with information available at `selection_end` only (no future sales)."""
    i = panel.idx(selection_end)
    w = panel.y[max(0, i - lookback_days + 1): i + 1]
    selling = np.nansum(w > 0, axis=0)
    has_window = ~np.isnan(panel.y[max(0, i - WINDOW + 1)])
    order = sorted(((-int(selling[j]), panel.skus[j]) for j in range(len(panel.skus))
                    if selling[j] >= min_selling_days and has_window[j]))
    skus = [s for _, s in order]
    return skus[:max_n] if max_n else skus


def scale_at(panel: Panel, i: int) -> np.ndarray:
    """Per-series scale: mean of the last WINDOW days (floor 0.1). Uses rows <= i only."""
    w = panel.y[i - WINDOW + 1: i + 1]
    return np.maximum(np.nanmean(w, axis=0), 0.1)


def mase_scale(panel: Panel, i: int, season: int = 7) -> np.ndarray:
    """Mean absolute seasonal difference over all history <= i; NaN where undefined (zero/short)."""
    y = panel.y[: i + 1]
    d = np.abs(y[season:] - y[:-season])
    with np.errstate(invalid="ignore"):
        m = np.nanmean(d, axis=0)
    m[(m == 0) | np.isnan(m)] = np.nan
    return m


def actuals(panel: Panel, i: int, horizon: int = HORIZON) -> np.ndarray:
    """(S, H) labels for origin index i."""
    return panel.y[i + 1: i + 1 + horizon].T


def rearrange(q: np.ndarray) -> np.ndarray:
    """Sort quantiles along the last axis (declared post-processing, applied to every model)."""
    return np.sort(np.maximum(q, 0.0), axis=-1)


def save_panel(panel: Panel, path) -> None:
    np.savez(path, dates=panel.dates.asi8, skus=np.array(panel.skus), y=panel.y)


def load_panel(path) -> Panel:
    z = np.load(path, allow_pickle=False)
    return Panel(pd.DatetimeIndex(z["dates"]), [str(s) for s in z["skus"]], z["y"])
