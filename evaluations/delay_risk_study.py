"""D1: supplier delay risk scoring (F8). SIMULATED order history: read this as a method check.

No real delivery history exists for the UCI suppliers (their terms are simulated too), so an order history is generated
from a stated process, and the question is whether a model trained on the past would flag late deliveries ahead of time:
- every week from 2010-01 to 2011-12, each of the 104 UCI supplier terms places one order of a size drawn around the
  product's recorded weekly sales;
- actual lead time = quoted lead time + delay; delay = supplier reliability (assumed profile below) + lane variability
  (sea lanes, lead time >= 8 days, vary more) + a December peak + a small order-size effect + noise;
- late = more than 2 days after the quoted lead time.
Models (trained on 2010-01..2011-06, tested on 2011-07..2011-12): the supplier's past late rate (baseline), logistic
regression, LightGBM. Reported: AUC, Brier score, calibration by decile, and the share of late orders in the top 10 %
of risk scores. Because the process is known, recovering it shows the pipeline works; it says nothing about real
suppliers, whose delivery records would replace the generator.

uv run python evaluations/delay_risk_study.py
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import lightgbm as lgb
import numpy as np
from scipy.optimize import minimize
from sqlalchemy import text

from supplylens.config import REPO_ROOT
from supplylens.db import tenant_session
from supplylens.seed import tenant_id

SEED = 11
RELIABILITY = {"SIM-SUP-ALPHA": 0.4, "SIM-SUP-BRAVO": 1.6, "SIM-SUP-CHARLIE": 0.9, "SIM-SUP-DELTA": 0.2}   # mean extra days (assumed)
LATE_DAYS = 2
SPLIT = date(2011, 7, 1)


def generate(rng):
    tid = tenant_id("uci-research")
    with tenant_session(tid) as s:
        terms = s.execute(text("SELECT term_id, supplier_id, sku_id, lead_time_days FROM supplier_terms ORDER BY term_id")).all()
        weekly = dict(s.execute(text("SELECT sku_id, sum(units)::float / 104 FROM sales_daily WHERE sku_id = ANY(:k) GROUP BY 1"),
                                {"k": [t.sku_id for t in terms]}).all())
    rows = []
    day = date(2010, 1, 4)
    while day <= date(2011, 12, 5):
        for t in terms:
            size = max(1, int(rng.poisson(max(weekly.get(t.sku_id, 20.0) * 7, 5))))
            sea = t.lead_time_days >= 8
            mean = (RELIABILITY.get(t.supplier_id, 0.8) + (1.2 if sea else 0.0) + (1.5 if day.month == 12 else 0.0)
                    + 0.25 * np.log1p(size / 500))
            delay = rng.gamma(shape=1.5, scale=max(mean, 0.05) / 1.5) + (rng.normal(0, 2.0 if sea else 0.7))
            rows.append({"day": day, "supplier": t.supplier_id, "lead": t.lead_time_days, "sea": int(sea), "size": size,
                         "month": day.month, "late": int(delay > LATE_DAYS)})
        day += timedelta(days=7)
    return rows


def matrix(rows, suppliers):
    X = np.array([[1.0 if r["supplier"] == s else 0.0 for s in suppliers] + [r["lead"], r["sea"], np.log1p(r["size"]),
                  1.0 if r["month"] == 12 else 0.0, 1.0 if r["month"] == 11 else 0.0] for r in rows])
    return X, np.array([r["late"] for r in rows], dtype=float)


def auc(y, p):
    order = np.argsort(p)
    ranks = np.empty(len(p))
    ranks[order] = np.arange(1, len(p) + 1)
    pos = y == 1
    return float((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * (~pos).sum()))


def logistic(Xtr, ytr, Xte):
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
    A, B = np.c_[np.ones(len(Xtr)), (Xtr - mu) / sd], np.c_[np.ones(len(Xte)), (Xte - mu) / sd]
    def nll(w):
        z = A @ w
        return float(np.sum(np.logaddexp(0, z) - ytr * z) + 0.5 * np.sum(w[1:] ** 2))
    def grad(w):
        p = 1 / (1 + np.exp(-(A @ w)))
        g = A.T @ (p - ytr)
        g[1:] += w[1:]
        return g
    w = minimize(nll, np.zeros(A.shape[1]), jac=grad, method="L-BFGS-B").x
    return 1 / (1 + np.exp(-(B @ w))), w


def report(y, p):
    cut = np.quantile(p, 0.9)
    top = p >= cut
    bins = np.quantile(p, np.linspace(0, 1, 11))
    idx = np.clip(np.searchsorted(bins, p, side="right") - 1, 0, 9)
    cal = [{"decile": int(d + 1), "predicted": round(float(p[idx == d].mean()), 3), "observed": round(float(y[idx == d].mean()), 3)}
           for d in range(10) if (idx == d).any()]
    return {"auc": round(auc(y, p), 4), "brier": round(float(np.mean((p - y) ** 2)), 4),
            "late_share_in_top_decile": round(float(y[top].mean()), 4), "late_rate": round(float(y.mean()), 4),
            "lift_top_decile": round(float(y[top].mean() / y.mean()), 2), "calibration": cal}


def main() -> None:
    rng = np.random.default_rng(SEED)
    rows = generate(rng)
    suppliers = sorted({r["supplier"] for r in rows})
    tr, te = [r for r in rows if r["day"] < SPLIT], [r for r in rows if r["day"] >= SPLIT]
    Xtr, ytr = matrix(tr, suppliers)
    Xte, yte = matrix(te, suppliers)
    rate = {s: np.mean([r["late"] for r in tr if r["supplier"] == s]) for s in suppliers}
    base = np.array([rate[r["supplier"]] for r in te])
    p_lr, w = logistic(Xtr, ytr, Xte)
    booster = lgb.train({"objective": "binary", "learning_rate": 0.05, "num_leaves": 15, "seed": SEED, "verbose": -1,
                         "deterministic": True, "num_threads": 1}, lgb.Dataset(Xtr, ytr), num_boost_round=300)
    p_gb = booster.predict(Xte)
    names = [f"supplier={s}" for s in suppliers] + ["quoted_lead_days", "sea_lane", "log_order_size", "december", "november"]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = REPO_ROOT / "artifacts" / "experiments" / f"D1-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    metrics = {
        "experiment_id": out.name, "study": "D1", "kind": "simulated",
        "question": "Can a model trained on past orders flag late deliveries ahead of time? (method check on a simulated history)",
        "data": {"orders_train": len(tr), "orders_test": len(te), "split": SPLIT.isoformat(), "late_definition": f"more than {LATE_DAYS} days after the quoted lead time",
                 "generator": {"reliability_days": RELIABILITY, "sea_extra_days": 1.2, "december_extra_days": 1.5, "seed": SEED}},
        "models": {"supplier_late_rate": report(yte, base), "logistic_regression": report(yte, p_lr), "lightgbm": report(yte, p_gb)},
        "logistic_coefficients_standardised": {n: round(float(c), 3) for n, c in zip(names, w[1:], strict=True)},
        "lightgbm_gain_importance": {n: round(float(v), 1) for n, v in zip(names, booster.feature_importance("gain"), strict=True)},
        "limits": ["the order history is generated: the models can only recover effects that were put in",
                   "no real supplier delivery data; replace generate() with recorded receipts (ERP receipt feed, Phase 6)"],
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str))
    (out / "config.json").write_text(json.dumps({"seed": SEED, "split": SPLIT.isoformat(), "late_days": LATE_DAYS}, indent=1))
    print(json.dumps({"experiment_id": out.name, **{k: {f: v[f] for f in ("auc", "brier", "lift_top_decile", "late_rate")} for k, v in metrics["models"].items()},
                      "coef": metrics["logistic_coefficients_standardised"]}, indent=1))


if __name__ == "__main__":
    main()
