"""S2: decision-level backtest of the product's replenishment logic (ml/configs/decision_study_s2.json).

The question is not "which forecaster has the lowest MAE" (F1 answers that) but "which forecaster, fed through the logic
the product actually ships, leads to better simulated stock outcomes", against a simple rule that uses no forecast at all.
Every policy runs the same code path for the order quantity: optimisation/supplylens_opt/replenishment.assess (lead-time
demand at a 90% service level, one requirement per supplier lead time) and the coverage-first CP-SAT planner with MOQ,
pack multiples, lead times, budget and the open orders the simulation itself placed.

Exploratory and simulated: terms and costs are assumptions (uci-sim-ops recipe, study-only seed), demand is recorded
sales, and the window is the last F1 test window, already seen by earlier studies.

uv run python evaluations/decision_study.py
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from sqlalchemy import text

from supplylens.config import REPO_ROOT
from supplylens.db import tenant_session
from supplylens.seed import tenant_id
from supplylens_ml import models as M
from supplylens_ml.evaluate import paired_bootstrap
from supplylens_ml.panel import load_panel, rearrange
from supplylens_opt.leadtime_demand import estimate_dependence
from supplylens_opt.planner import Need, Offer, PlanRequest, plan
from supplylens_opt.replenishment import Position, assess

CONFIG = REPO_ROOT / "ml" / "configs" / "decision_study_s2.json"
Z90 = 1.2816


def log(m):
    print(f"[{datetime.now(UTC):%H:%M:%S}] {m}", flush=True)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def forecast_study() -> Path:
    reg = json.loads((REPO_ROOT / "evaluations" / "study_registry.json").read_text())["experiments"]
    runs = sorted(p for p in (REPO_ROOT / "artifacts" / "experiments").glob("F1-2*") if (p / "metrics.json").exists())
    live = [p for p in runs if reg.get(p.name, {}).get("status", "current") not in ("superseded",)]
    return live[-1]


def make_terms(cohort, price_minor, conf, rng):
    t = conf["terms"]
    offers, cost, lead = {}, {}, {}
    for j, sku in enumerate(cohort):
        pack = int(rng.choice(t["pack_sizes"]))
        base = max(1, round(price_minor.get(sku, 100) * rng.uniform(*t["unit_cost_ratio_of_median_selling_price"])))
        rows = []
        for role in ("primary", "alternate"):
            c = base if role == "primary" else round(base * (1 + rng.uniform(*t["alternate_supplier_cost_uplift"])))
            lo, hi = t["primary_lead_time_days"] if role == "primary" else t["alternate_lead_time_days"]
            lt = int(rng.integers(lo, hi + 1))
            moq = pack * int(rng.integers(t["moq_packs"][0], t["moq_packs"][1] + 1))
            rows.append(Offer(term_id=f"S2-{role[0].upper()}-{sku}", supplier_id=f"S2-{role.upper()}-{j % 4}", sku_id=sku,
                              unit_cost_minor=int(c), currency="GBP", moq=moq, order_multiple=pack, lead_time_days=lt,
                              value_kind="simulated"))
        offers[sku], cost[sku], lead[sku] = rows, base, sorted({o.lead_time_days for o in rows})
    return offers, cost, lead


def tcn_forecast(panel_path: Path, i: int, model: Path, expected: str, out: Path) -> np.ndarray:
    r = subprocess.run([sys.executable, "-m", "supplylens_ml.tcn", "predict", "--panel", str(panel_path), "--index", str(i),
                        "--model", str(model), "--model-sha256", expected, "--pred-out", str(out)],
                       capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise RuntimeError(r.stderr[-1200:])
    return np.load(out)


def acf_at(panel, j: int, i: int):
    days = np.arange(max(0, i - 119), i + 1)
    col = panel.y[days, j]
    keep = ~np.isnan(col) & (col > 0)          # recorded selling days only, as the product does
    values = col[keep].tolist()
    ordinals = [int(panel.dates[d].toordinal()) for d in days[keep]]
    weekdays = [int(panel.dates[d].dayofweek) for d in days[keep]]
    est = estimate_dependence(values, weekdays, ordinals=ordinals)
    return (list(est[0]), "history") if est else (None, "assumed default")


def main():
    conf = json.loads(CONFIG.read_text())
    f1 = forecast_study()
    f1m = json.loads((f1 / "metrics.json").read_text())
    panel_path = f1 / "_work" / "panel.npz"
    panel = load_panel(panel_path)
    cohort = json.loads((f1 / "cohort.json").read_text())
    assert panel.skus == cohort
    S = len(cohort)
    w = conf["window"]
    first = datetime.fromisoformat(w["first_review"]).date()
    reviews = [first + timedelta(days=w["review_days"] * k) for k in range(w["reviews"])]
    rev_i = [panel.idx(r) for r in reviews]
    end_i = panel.idx(w["last_day"])
    C = conf["product_policy"]["coverage_days"]
    with tenant_session(tenant_id("uci-research")) as s:
        ds = s.execute(text("SELECT id FROM datasets WHERE name='UCI Online Retail II'")).scalar()
        price_minor = {r.sku_id: int(r.p) for r in s.execute(text("""
            SELECT sku_id, percentile_disc(0.5) WITHIN GROUP (ORDER BY unit_price_minor) AS p FROM sales_lines
            WHERE dataset_id = :d AND sku_id = ANY(:k) AND invoiced_at < :b GROUP BY sku_id"""),
            {"d": ds, "k": cohort, "b": first.isoformat()})}
    rng = np.random.default_rng(conf["terms"]["seed"])
    offers, unit_cost, leads = make_terms(cohort, price_minor, conf, rng)
    price = np.array([price_minor.get(k, 100) / 100 for k in cohort])
    cost = np.array([unit_cost[k] / 100 for k in cohort])
    margin = np.maximum(price - cost, 0.0)
    hold_day = cost * conf["costs"]["holding_rate_annual"] / 365
    i0 = panel.idx(first)
    init = np.ceil(14 * np.nan_to_num(panel.y[i0 - 27: i0 + 1]).mean(axis=0))

    # ---------------- forecasts at every review (models trained up to F1's last test origin = the first review)
    arts = {a["file"]: a["sha256"] for fam in ("lightgbm", "tcn") for a in f1m["artifacts"][fam]}
    import lightgbm as lgb
    boosters = []
    for q in (10, 50, 90):
        f = f1 / f"lightgbm_q{q}.txt"
        raw = f.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == arts[f.name], f"{f.name} hash mismatch"
        boosters.append(lgb.Booster(model_str=raw.decode()))
    tcn_model = f1 / "tcn_seed0.pt"
    fc = {"seasonal_naive": {}, "lightgbm": {}, "tcn": {}}
    with tempfile.TemporaryDirectory() as td:
        for i in rev_i:
            fc["seasonal_naive"][i] = rearrange(M.seasonal_naive_panel(panel, i, 28))
            fc["lightgbm"][i] = rearrange(M.predict_lgbm(boosters, panel, i, 28))
            fc["tcn"][i] = rearrange(tcn_forecast(panel_path, i, tcn_model, arts[tcn_model.name], Path(td) / f"{i}.npy"))
    context_mae = {}
    for fam, by in fc.items():
        errs = []
        for i, q in by.items():
            n = min(28, end_i - i)
            errs.append(np.nanmean(np.abs(panel.y[i + 1: i + 1 + n].T - q[:, :n, 1])))
        context_mae[fam] = float(np.mean(errs))
    log(f"forecast study {f1.name}; reviews {reviews}; context MAE {context_mae}")
    acf = {i: [acf_at(panel, j, i) for j in range(S)] for i in rev_i}

    def requirements(policy: str, i: int, stock: np.ndarray, pending: np.ndarray) -> dict[str, dict[int, int]]:
        out = {}
        hist = np.nan_to_num(panel.y[i - 55: i + 1])
        m, sd = hist.mean(axis=0), hist.std(axis=0)
        d0 = panel.dates[i].date()
        for j, sku in enumerate(cohort):
            req = {}
            for L in leads[sku]:
                if policy.startswith("product_"):
                    q = fc[policy.removeprefix("product_")][i][j]
                    path = [{"day": d0 + timedelta(days=h + 1), "q10": float(q[h, 0]), "q50": float(q[h, 1]),
                             "q90": float(q[h, 2])} for h in range(q.shape[0])]
                    a = assess(Position(sku_id=sku, on_hand=int(stock[j]), allocated=0, on_order=int(pending[j])), path,
                               d0, C, 5, "leadtime_demand", lead_time_days=L,
                               service_level=conf["product_policy"]["service_level"], acf=acf[i][j][0],
                               dependence_basis=acf[i][j][1])
                    req[L] = int(a.required_units)
                elif policy == "simple_base_stock":
                    target = m[j] * (L + C) + Z90 * sd[j] * math.sqrt(L + C)
                    req[L] = max(0, math.ceil(target - stock[j] - pending[j]))
                else:  # perfect foresight reference (truncated at the end of the data)
                    actual = float(np.nansum(panel.y[i + 1: min(i + 1 + L + C, end_i + 1), j]))
                    req[L] = max(0, math.ceil(actual - stock[j] - pending[j]))
            if max(req.values()) > 0:
                out[sku] = req
        return out

    def simulate(policy: str, budget_minor: int) -> dict:
        stock, pipeline = init.copy(), {}
        lost_v, hold_v, sold_v, dem_v = np.zeros(S), np.zeros(S), np.zeros(S), np.zeros(S)
        stockout_days = spend = units = orders = shortfall = 0
        statuses = []
        for d in range(i0 + 1, end_i + 1):
            r = d - 1
            if r in rev_i:
                pending = sum(v for k, v in pipeline.items() if k > r) if pipeline else np.zeros(S)
                reqs = requirements(policy, r, stock, pending)
                needs = [Need(sku_id=k, required_units=min(v.values()), required_units_by_lead_time=v) for k, v in reqs.items()]
                res = plan(PlanRequest(decision_date=panel.dates[r].date(), need_by=panel.dates[r].date() + timedelta(days=C),
                                       currency="GBP", budget_minor=budget_minor, needs=needs,
                                       offers=[o for k in reqs for o in offers[k]], allow_shortfall=True))
                statuses.append(res.status)
                for line in res.lines:
                    j = cohort.index(line.sku_id)
                    arrive = r + next(o.lead_time_days for o in offers[line.sku_id] if o.term_id == line.term_id)
                    pipeline.setdefault(arrive, np.zeros(S))[j] += line.quantity
                    spend += line.line_minor
                    units += line.quantity
                    orders += 1
                shortfall += sum(res.shortfall.values())
            stock = stock + pipeline.pop(d, 0)
            dem = np.nan_to_num(panel.y[d])
            sold = np.minimum(dem, stock)
            stock = stock - sold
            sold_v += sold
            dem_v += dem
            lost_v += (dem - sold) * margin
            hold_v += stock * hold_day
            stockout_days += int(((dem - sold) > 0).sum())
        return {"fill_rate": float(sold_v.sum() / dem_v.sum()), "stockout_product_days": stockout_days,
                "lost_margin": float(lost_v.sum()), "holding_cost": float(hold_v.sum()),
                "total_cost": float(lost_v.sum() + hold_v.sum()), "purchase_spend": spend / 100, "units_ordered": units,
                "order_lines": orders, "shortfall_units": int(shortfall), "planner_statuses": statuses,
                "per_product_total_cost": (lost_v + hold_v).tolist()}

    budgets = {"workspace_scaled": int(2_000_000 * S / 48), "unconstrained": 10 ** 12}
    policies = list(conf["policies"])
    results = {}
    for bname, b in budgets.items():
        results[bname] = {}
        for p in policies:
            results[bname][p] = simulate(p, b)
            r = results[bname][p]
            log(f"{bname} {p}: fill {r['fill_rate']:.3f} cost {r['total_cost']:.0f} spend {r['purchase_spend']:.0f} "
                f"stockout-days {r['stockout_product_days']} shortfall {r['shortfall_units']}")
    comparisons = {}
    for bname in budgets:
        R = results[bname]
        pc = {p: np.array(R[p]["per_product_total_cost"]) for p in policies}
        best = min(("product_seasonal_naive", "product_lightgbm", "product_tcn"), key=lambda p: R[p]["total_cost"])
        comparisons[bname] = {
            "product_tcn_vs_product_seasonal_naive": paired_bootstrap(pc["product_tcn"], pc["product_seasonal_naive"]),
            "product_lightgbm_vs_product_seasonal_naive": paired_bootstrap(pc["product_lightgbm"], pc["product_seasonal_naive"]),
            f"{best}_vs_simple_base_stock": paired_bootstrap(pc[best], pc["simple_base_stock"]),
            "best_product_policy": best}
    exp_id = f"S2-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    out = REPO_ROOT / "artifacts" / "experiments" / exp_id
    out.mkdir(parents=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip()
    strip = {b: {p: {k: v for k, v in r.items() if k != "per_product_total_cost"} for p, r in R.items()} for b, R in results.items()}
    (out / "config.json").write_text(json.dumps({**conf, "config_sha256": sha(CONFIG), "commit": commit}, indent=2))
    (out / "metrics.json").write_text(json.dumps({
        "experiment_id": exp_id, "study": "S2", "status": "exploratory", "value_kind": "simulated",
        "forecast_study": f1.name, "products": S, "reviews": [str(r) for r in reviews], "window_end": w["last_day"],
        "budgets_minor": budgets, "context_forecast_mae": context_mae, "results": strip, "comparisons": comparisons,
        "term_summary": {"median_unit_cost_gbp": float(np.median(cost)), "median_margin_gbp": float(np.median(margin)),
                         "lead_times": sorted({L for v in leads.values() for L in v})},
        "honesty_note": conf["honesty_note"]}, indent=2))
    log(f"wrote {out.relative_to(REPO_ROOT)}")
    log(json.dumps(comparisons, indent=1))


if __name__ == "__main__":
    main()
