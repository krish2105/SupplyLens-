"""S1: do better forecasts produce better (simulated) inventory outcomes? (ML-006 study F, ML-007)

Lost-sales simulation on the F1 cohort over the held-out window (2011-11-11 .. 2011-12-08).
Held fixed across conditions: policy, review period, lead time, costs, initial stock, demand path.
Only the forecaster changes. Demand = recorded unit sales (a proxy; stockouts are unobserved).

Event order each day: receive due orders -> realise demand -> sell up to stock -> record lost
sales -> accrue holding on ending stock. Orders are placed at weekly review origins after
observing sales up to and including the origin day.

Policy (same for all): order-up-to S = sum(q50 over L+R days) + z * sqrt(sum(sigma_d^2)), sigma_d =
(q90 - q10) / 2.563. Treating days as independent is a declared simplification (spec ML-005).
uv run python evaluations/simulation_study.py
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sqlalchemy import text

from supplylens.db import tenant_session
from supplylens.seed import tenant_id
from supplylens_ml.models import predict_lgbm, seasonal_naive_panel
from supplylens_ml.panel import build_panel, rearrange, save_panel

REPO = Path(__file__).resolve().parents[1]
ASSUME = {"lead_time_days": 3, "review_days": 7, "z": 1.2816, "holding_rate_annual": 0.25,
          "unit_cost_share_of_price": 0.55, "currency": "GBP",
          "notes": "All cost parameters are assumptions (UCI has selling prices only); lost margin = price - cost per lost unit."}


def latest(prefix):
    return sorted(p for p in (REPO / "artifacts/experiments").glob(prefix + "-2*") if (p / "metrics.json").exists())[-1]


def forecasts(model: str, panel, origins_i, f1: Path) -> dict[int, np.ndarray]:
    out = {}
    if model == "seasonal_naive":
        for i in origins_i:
            out[i] = rearrange(seasonal_naive_panel(panel, i))
    elif model == "lightgbm":
        b = [lgb.Booster(model_file=str(f1 / f"lightgbm_q{q}.txt")) for q in (10, 50, 90)]
        for i in origins_i:
            out[i] = rearrange(predict_lgbm(b, panel, i))
    else:
        with tempfile.TemporaryDirectory() as td:
            pnl = Path(td) / "p.npz"
            save_panel(panel, pnl)
            for i in origins_i:
                y = Path(td) / f"{i}.npy"
                r = subprocess.run([sys.executable, "-m", "supplylens_ml.tcn", "predict", "--panel", str(pnl), "--index", str(i),
                                    "--model", str(f1 / "tcn_seed0.pt"), "--pred-out", str(y)], capture_output=True, text=True)
                if r.returncode:
                    raise RuntimeError(r.stderr[-800:])
                out[i] = rearrange(np.load(y))
    return out


def order_up_to(q: np.ndarray, L: int, R: int, z: float, policy: str = "median_plus_safety") -> np.ndarray:
    w = q[:, : L + R, :]
    if policy == "sum_q90":
        # Declared heuristic: summing daily q90 is NOT a calibrated lead-time quantile (spec ML-005).
        return w[..., 2].sum(1)
    sigma = (w[..., 2] - w[..., 0]) / 2.563
    return w[..., 1].sum(1) + z * np.sqrt((sigma ** 2).sum(1))


def simulate(panel, start_i, end_i, fc: dict[int, np.ndarray] | None, price, cost, a, init, oracle=False,
             policy: str = "median_plus_safety"):
    S_count = panel.y.shape[1]
    L, R, z = a["lead_time_days"], a["review_days"], a["z"]
    h_day = cost * a["holding_rate_annual"] / 365
    stock = init.copy()
    pipeline: dict[int, np.ndarray] = {}
    sold = lost = hold = 0.0
    sold_v = np.zeros(S_count); dem_v = np.zeros(S_count); stockout_days = 0; inv_units = []
    orders = 0
    for i in range(start_i, end_i + 1):
        origin = i - 1  # decisions at the end of the previous day
        if (i - start_i) % R == 0:
            if oracle:
                target = np.nansum(panel.y[i + L: min(i + L + R, end_i + 1)], axis=0)  # perfect foresight of the cover window
            else:
                target = order_up_to(fc[origin], L, R, z, policy)
            position = stock + sum(pipeline.values()) if pipeline else stock.copy()
            q = np.maximum(0, np.ceil(target - position))
            orders += int((q > 0).sum())
            pipeline[i + L] = pipeline.get(i + L, 0) + q
        stock = stock + pipeline.pop(i, 0)
        d = np.nan_to_num(panel.y[i])
        s = np.minimum(d, stock)
        stock = stock - s
        sold_v += s; dem_v += d
        lost += float(((d - s) * (price - cost)).sum())
        hold += float((stock * h_day).sum())
        stockout_days += int(((d - s) > 0).sum())
        inv_units.append(stock.sum())
    fill = sold_v.sum() / dem_v.sum()
    return {"fill_rate": float(fill), "lost_margin": lost, "holding_cost": hold, "total_cost": lost + hold,
            "stockout_product_days": stockout_days, "avg_inventory_units": float(np.mean(inv_units)),
            "orders_placed": orders,
            "per_product_fill": (sold_v / np.maximum(dem_v, 1e-9)).tolist()}


def main():
    f1 = latest("F1")
    conf = json.loads((f1 / "config.json").read_text())
    cohort = json.loads((f1 / "cohort.json").read_text())
    t = tenant_id("uci-research")
    with tenant_session(t) as s:
        ds = s.execute(text("SELECT id FROM datasets WHERE name='UCI Online Retail II'")).scalar()
        daily = pd.DataFrame(s.execute(text("SELECT sku_id, day, units FROM sales_daily WHERE dataset_id=:d AND sku_id = ANY(:k)"),
                                       {"d": ds, "k": cohort}).all(), columns=["sku_id", "day", "units"])
        prices = dict(s.execute(text("""SELECT sku_id, percentile_disc(0.5) WITHIN GROUP (ORDER BY unit_price_minor)
            FROM sales_lines WHERE dataset_id=:d AND sku_id = ANY(:k) AND invoiced_at < '2011-11-11' GROUP BY sku_id"""),
            {"d": ds, "k": cohort}).all())
    panel = build_panel(daily, conf["data"]["start"], conf["data"]["end"]).subset(cohort)
    price = np.array([prices.get(sk, 100) / 100 for sk in cohort], dtype=float)
    start_i = panel.idx(conf["test_origin"]) + 1
    end_i = len(panel.dates) - 1
    origins = [i - 1 for i in range(start_i, end_i + 1, ASSUME["review_days"])]
    fcs = {m: forecasts(m, panel, origins, f1) for m in ("seasonal_naive", "lightgbm", "tcn")}
    results, sens = {}, {}
    for (L, hr) in [(3, 0.25), (1, 0.25), (7, 0.25), (3, 0.15), (3, 0.40)]:
        a = {**ASSUME, "lead_time_days": L, "holding_rate_annual": hr}
        cost = price * a["unit_cost_share_of_price"]
        # Same initial stock for every condition: the seasonal-naive order-up-to level at the first origin.
        init = np.maximum(0, np.ceil(order_up_to(fcs["seasonal_naive"][origins[0]], L, a["review_days"], a["z"])))
        cond = {m: simulate(panel, start_i, end_i, fcs[m], price, cost, a, init) for m in fcs}
        cond.update({f"{m}__sum_q90": simulate(panel, start_i, end_i, fcs[m], price, cost, a, init, policy="sum_q90") for m in fcs})
        cond["perfect_foresight_reference"] = simulate(panel, start_i, end_i, None, price, cost, a, init, oracle=True)
        key = f"L{L}_h{int(hr * 100)}"
        sens[key] = {m: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if k != "per_product_fill"}
                     for m, r in cond.items()}
        if (L, hr) == (3, 0.25):
            results = cond
        print(key, {m: (round(r["fill_rate"], 4), round(r["total_cost"])) for m, r in cond.items()}, flush=True)
    paired = {}
    for m in ("lightgbm", "tcn"):
        d = np.array(results[m]["per_product_fill"]) - np.array(results["seasonal_naive"]["per_product_fill"])
        rng = np.random.default_rng(0)
        boots = rng.choice(d, size=(2000, len(d))).mean(1)
        paired[f"{m}_minus_seasonal_naive_fill"] = {"mean": float(d.mean()), "ci95": [float(np.quantile(boots, .025)), float(np.quantile(boots, .975))]}
    out = REPO / "artifacts" / "experiments" / f"S1-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    out.mkdir(parents=True)
    (out / "metrics.json").write_text(json.dumps({
        "experiment_id": out.name, "study": "S1", "forecast_study": f1.name, "products": len(cohort),
        "window": [str(panel.dates[start_i].date()), str(panel.dates[end_i].date())], "assumptions": ASSUME,
        "value_kind": "simulated", "base_case": "L3_h25", "results": sens, "paired_fill_difference": paired,
        "caveats": ["Recorded sales are a demand proxy; real lost sales are unobserved.",
                    "Costs are assumptions; simulated cost differences are not realised savings.",
                    "The perfect-foresight reference orders exactly the next review window's sales; with long lead times it is not an upper bound.",
                    "Diagnostic: summed q50 of LightGBM/TCN covers about 50%/42% of test-window volume vs 87% for seasonal naive (heavy-tailed daily sales), so accuracy-optimal medians under-stock."]}, indent=2))
    print("wrote", out.relative_to(REPO), json.dumps(paired))


if __name__ == "__main__":
    main()
