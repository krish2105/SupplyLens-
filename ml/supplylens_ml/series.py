"""Dense daily series construction with explicit missing-day semantics."""
from __future__ import annotations

from datetime import date

from .lazy import LazyModule

pd = LazyModule("pandas")


def dense_series(daily: pd.DataFrame, sku_id: str, end: date, start: date | None = None) -> pd.Series:
    """Units per day for one SKU from its first recorded sale (or `start`) to `end` inclusive.

    Days with no recorded sale are 0: in transaction data this means "no recorded sales",
    not observed zero demand (stockouts and closures are indistinguishable).
    """
    rows = daily[daily["sku_id"] == sku_id]
    rows = rows[pd.to_datetime(rows["day"]) <= pd.Timestamp(end)]
    if rows.empty:
        return pd.Series(dtype=float)
    first = pd.Timestamp(start) if start else pd.to_datetime(rows["day"]).min()
    idx = pd.date_range(first, pd.Timestamp(end), freq="D")
    s = rows.assign(day=pd.to_datetime(rows["day"])).set_index("day")["units"].astype(float)
    return s.reindex(idx, fill_value=0.0)
