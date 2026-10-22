"""L1: does the lead-time-demand model hit the service level it is asked for, and what does it cost in stock?

    uv run python evaluations/leadtime_demand_study.py

Simulated demand with KNOWN day-to-day dependence (supplylens_opt.demand_sim): negative-binomial daily demand around a weekday
pattern and a persistent latent level. For each persistence value, a marginal-quantile forecaster (calibrated per day,
blind to the latent level) gives daily q10/q50/q90, and each method turns them into an order-up-to level for a 28-day
protection interval (7 days lead time + 21 days coverage). We then count how often the realised 28-day demand stays at or
below that level ("coverage": the achieved service level) and how much stock the level implies.

Methods
  ltd_estimated   lead-time-demand model with the day-to-day autocorrelation curve (lags 1-14) measured from the series' own first 180 days
  ltd_default     same model with the declared fallback dependence (0.3), as used when no history exists
  q90_sum         the previous heuristic: sum of daily q90 over the window (only defined for a 90% target)
  q50_sum         sum of daily medians (what the earlier study showed under-stocks)

This is a SIMULATION. It shows the mechanics and the size of the gap between methods when the data-generating process is
known; it does not show how the model behaves on real retail history (the UCI/M5 histories need the licensed files).
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "optimisation"))

from supplylens_opt.demand_sim import marginal_quantiles, simulate
from supplylens_opt.leadtime_demand import DEFAULT_RHO, estimate_dependence, window_demand

L = 28
PHIS = (0.0, 0.5, 0.9)
LEVELS = (0.8, 0.9, 0.95)
N_SERIES = 150
TRAIN, TEST = 180, 240


def pinball(actual: float, q: float, tau: float) -> float:
    return tau * (actual - q) if actual >= q else (1 - tau) * (q - actual)


def one_phi(phi: float, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    acc = {(m, tau): {"hit": 0, "n": 0, "stock": 0.0, "pin": 0.0} for m in ("ltd_estimated", "ltd_default", "q90_sum", "q50_sum") for tau in LEVELS}
    lag1, rho_n = [], 0
    for _ in range(N_SERIES):
        base, s, r = float(rng.uniform(5, 30)), 0.35, 4.0
        q = marginal_quantiles(base, s, r, rng, n=8000)
        x = simulate(TRAIN + TEST, base, phi, s, r, rng)
        est = estimate_dependence(list(x[:TRAIN]), [i % 7 for i in range(TRAIN)])
        acf = est[0] if est else None
        if est:
            rho_n += 1
        for origin in range(0, TEST - L, 7):
            path = [{"q10": q[(TRAIN + origin + i) % 7][0], "q50": q[(TRAIN + origin + i) % 7][1], "q90": q[(TRAIN + origin + i) % 7][2]}
                    for i in range(L)]
            actual = float(x[TRAIN + origin:TRAIN + origin + L].sum())
            q50s, q90s = sum(p["q50"] for p in path), sum(p["q90"] for p in path)
            for tau in LEVELS:
                levels = {
                    "ltd_estimated": window_demand(path, L, tau, acf, "history").quantile,
                    "ltd_default": window_demand(path, L, tau, None).quantile,
                    "q90_sum": q90s, "q50_sum": q50s,
                }
                for m, lvl in levels.items():
                    a = acc[(m, tau)]
                    a["hit"] += actual <= lvl
                    a["n"] += 1
                    a["stock"] += lvl
                    a["pin"] += pinball(actual, lvl, tau)
        if est:
            lag1.append(est[0][0])
    out = {}
    for (m, tau), a in acc.items():
        out.setdefault(m, {})[str(tau)] = {"coverage": round(a["hit"] / a["n"], 3), "mean_order_up_to": round(a["stock"] / a["n"], 1),
                                           "mean_pinball": round(a["pin"] / a["n"], 2)}
    return {"phi": phi, "windows": a["n"], "series": N_SERIES, "estimated_lag1_median": round(float(np.median(lag1)), 3) if lag1 else None,
            "series_with_enough_history": rho_n, "results": out}


def main() -> None:
    res = [one_phi(phi, 100 + i) for i, phi in enumerate(PHIS)]
    doc = {"study": "L1", "generated_at": datetime.now(UTC).isoformat(), "protection_days": L, "default_rho": DEFAULT_RHO,
           "note": "simulation with known dependence; not validated on real retail data", "by_persistence": res}
    out = REPO / "artifacts" / "reports" / "leadtime_demand_study.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2))
    print(f"{'phi':>4} {'target':>6} | " + " | ".join(f"{m:>26}" for m in ("ltd_estimated", "ltd_default", "q90_sum", "q50_sum")))
    print(f"{'':>4} {'':>6} | " + " | ".join(f"{'coverage  stock':>26}" for _ in range(4)))
    for r in res:
        for tau in LEVELS:
            cells = []
            for m in ("ltd_estimated", "ltd_default", "q90_sum", "q50_sum"):
                c = r["results"][m][str(tau)]
                cells.append(f"{c['coverage']:>10.3f} {c['mean_order_up_to']:>10.1f}")
            print(f"{r['phi']:>4} {tau:>6} | " + " | ".join(f"{c:>26}" for c in cells))
    print("wrote", out.relative_to(REPO))


if __name__ == "__main__":
    main()
