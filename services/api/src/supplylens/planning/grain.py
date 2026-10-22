"""SKU-location planning grain (audit S21).

A SKU stocked at one location is planned under its plain SKU id, exactly as before. A SKU stocked at several locations is
planned once per location under the key `SKU@LOCATION`: its own stock snapshot, its own capacity, its own share of the
SKU's demand forecast and its own order line. The optimiser and the independent validator see each key as a separate
need with separately keyed copies of the supplier offers (`TERM@LOCATION`), so nothing is pooled across sites; plan lines
are mapped back to the real SKU, term and location before anything is shown, stored or sent.

Demand split. Forecasts are made per SKU. Each location receives the share of that SKU's sales recorded at the location
over the 56 days up to the decision date; when no sales are recorded at any of the stocked locations (the sales feed uses
other location ids, or the SKU is new) the forecast is split equally and the need says so. The split rule is declared in
every assessment (`demand_share`, `demand_share_basis`).
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text

from supplylens_opt.planner import Offer, PlanLine

SEP = "@"
SHARE_WINDOW_DAYS = 56


def plan_key(sku: str, location: str, multi: bool) -> str:
    return f"{sku}{SEP}{location}" if multi else sku


def split_key(key: str) -> tuple[str, str | None]:
    sku, _, loc = key.partition(SEP)
    return sku, (loc or None)


def demand_shares(s, dataset_id, positions: dict[str, dict], decision_date: date) -> dict[str, tuple[float, str]]:
    """{plan key: (share of the SKU's forecast, basis)} for every key of a multi-location SKU; single-location keys get 1."""
    by_sku: dict[str, list[str]] = {}
    for k, p in positions.items():
        by_sku.setdefault(p["sku_id"], []).append(k)
    out = {}
    multi = {sku: keys for sku, keys in by_sku.items() if len(keys) > 1}
    for sku, keys in by_sku.items():
        if sku not in multi:
            out[keys[0]] = (1.0, "single location")
    if not multi:
        return out
    sales = {}
    if dataset_id:
        sales = {(r.sku_id, r.location_id): float(r.units) for r in s.execute(text("""
            SELECT sku_id, location_id, sum(units) AS units FROM sales_daily
            WHERE dataset_id = :d AND sku_id = ANY(:k) AND day > :lo AND day <= :hi GROUP BY sku_id, location_id"""),
            {"d": dataset_id, "k": list(multi), "lo": decision_date - timedelta(days=SHARE_WINDOW_DAYS), "hi": decision_date})}
    for sku, keys in multi.items():
        vols = {k: sales.get((sku, positions[k]["location_id"]), 0.0) for k in keys}
        total = sum(vols.values())
        for k in keys:
            if total > 0:
                out[k] = (vols[k] / total, f"share of the SKU's sales at this location over {SHARE_WINDOW_DAYS} days")
            else:
                out[k] = (1.0 / len(keys), "equal split: no sales recorded at these locations")
    return out


def expand_offers(offers: list[Offer], keys: list[str]) -> list[Offer]:
    """One copy of each SKU offer per plan key of that SKU; location keys get location-suffixed term ids."""
    by_sku: dict[str, list[str]] = {}
    for k in keys:
        by_sku.setdefault(split_key(k)[0], []).append(k)
    out = []
    for o in offers:
        for k in by_sku.get(o.sku_id, []):
            _, loc = split_key(k)
            out.append(o if loc is None else o.model_copy(update={"sku_id": k, "term_id": f"{o.term_id}{SEP}{loc}"}))
    return out


def restore_line(line: PlanLine) -> tuple[PlanLine, str | None]:
    """Plan line at the real SKU and term, plus its location (None for single-location SKUs)."""
    sku, loc = split_key(line.sku_id)
    if loc is None:
        return line, None
    return line.model_copy(update={"sku_id": sku, "term_id": line.term_id.rsplit(SEP, 1)[0]}), loc
