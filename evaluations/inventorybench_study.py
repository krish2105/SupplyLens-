"""InventoryBench (pinned commit 62b1f11) — deterministic policies scored by the OFFICIAL evaluator.

Policies (no LLM; the agent study compares tool-only decision logic):
  last_value       order up to last observed demand x (L+1)                         (weak reference)
  base_stock       normal base-stock, critical ratio p/(p+h), promised lead time    (OR baseline replica)
  supplylens       exponentially smoothed level + empirical residual quantile at the critical
                   ratio, lead time learned from observed arrivals (FIFO matching), loss-aware

The simulator below mirrors eval/run_baseline_policy.py: the policy only sees on-hand, in-transit,
previous demand/order/arrivals, prices and the promised lead time. Actual lead times are used only
to move goods, exactly as in the official runner. Scores come from eval/evaluate_results.py.

uv run python evaluations/inventorybench_study.py
"""
from __future__ import annotations

import json
import math
import statistics
import subprocess
import sys
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
IB = REPO / "data/raw/core/inventory_bench/repository"
PINNED = "62b1f1162f19a41d428d47c6cd4ca431f098f6f3"


def z_of(p: float) -> float:
    return statistics.NormalDist().inv_cdf(min(max(p, 1e-4), 1 - 1e-4))


class LastValue:
    def __init__(self, hist, L, p, h):
        self.L, self.last = L, (hist[-1] if hist else 0.0)

    def order(self, s):
        if s["period"] > 1:
            self.last = s["previous_demand"]
        return max(0.0, self.last * (self.L + 1) - s["on_hand"] - s["in_transit"])


class BaseStock:
    def __init__(self, hist, L, p, h):
        self.L, self.hist = L, list(hist)

    def order(self, s):
        if s["period"] > 1:
            self.hist.append(s["previous_demand"])
        mu = float(np.mean(self.hist)) if self.hist else 0.0
        sd = float(np.std(self.hist)) if len(self.hist) > 1 else mu * 0.5
        rho = s["p"] / (s["p"] + s["h"])
        S = mu * (self.L + 1) + z_of(rho) * sd * math.sqrt(self.L + 1)
        return max(0.0, S - s["on_hand"] - s["in_transit"])


class SupplyLens:
    """Forecast + service target + verified lead-time learning: the deterministic core SupplyLens uses."""

    def __init__(self, hist, L, p, h, alpha: float = 0.3):
        self.promised, self.alpha = L, alpha
        self.level = float(np.mean(hist)) if hist else 0.0
        self.resid: list[float] = [d - self.level for d in hist]
        self.outstanding: deque = deque()  # [order_period, remaining_qty]
        self.lead_samples: list[int] = []
        self.prev_transit = 0.0

    def _learn_arrivals(self, period, arrivals, in_transit, last_order):
        # Arrivals observed last period fill the oldest open orders first (FIFO).
        left = arrivals
        while left > 1e-9 and self.outstanding:
            o = self.outstanding[0]
            take = min(o[1], left)
            o[1] -= take
            left -= take
            if o[1] <= 1e-9:
                self.lead_samples.append(period - 1 - o[0])
                self.outstanding.popleft()
        # Orders that vanished from in-transit without arriving were lost: drop them from the ledger.
        expected = sum(o[1] for o in self.outstanding)
        if expected - in_transit > 1e-6:
            lost = expected - in_transit
            while lost > 1e-9 and self.outstanding:
                o = self.outstanding[-1]
                take = min(o[1], lost)
                o[1] -= take
                lost -= take
                if o[1] <= 1e-9:
                    self.outstanding.pop()

    def order(self, s):
        if s["period"] > 1:
            d = s["previous_demand"]
            self.resid.append(d - self.level)
            self.level = self.alpha * d + (1 - self.alpha) * self.level
            self._learn_arrivals(s["period"], s["previous_arrivals"], s["in_transit"], s["previous_order"])
        L = self.promised
        if self.lead_samples:
            L = max(L if not self.lead_samples else 0, int(np.ceil(np.quantile(self.lead_samples, 0.8))))
        L = max(L, max((s["period"] - 1 - o[0] for o in self.outstanding), default=0) if L == 0 else L)
        rho = s["p"] / (s["p"] + s["h"])
        r = np.array(self.resid[-20:]) if self.resid else np.array([0.0])
        n = L + 1
        if len(r) >= 8:
            q = float(np.quantile(r, rho)) * math.sqrt(n)
        else:
            q = z_of(rho) * (float(np.std(r)) if len(r) > 1 else self.level * 0.5) * math.sqrt(n)
        S = max(0.0, self.level * n + q)
        qty = max(0.0, S - s["on_hand"] - s["in_transit"])
        return qty

    def record(self, period, qty):
        if qty > 0:
            self.outstanding.append([period, float(qty)])


POLICIES = {"last_value": LastValue, "base_stock": BaseStock, "supplylens": SupplyLens}


def promised(path: Path) -> int:
    s = str(path)
    return 0 if "lead_time_0" in s else 4 if "lead_time_4" in s else 2


def simulate(policy_cls, inst: Path) -> pd.DataFrame:
    item = inst.name
    train = pd.read_csv(inst / "train.csv")
    test = pd.read_csv(inst / "test.csv")
    hist = [float(x) for x in train[f"demand_{item}"]]
    p0, h0 = float(test[f"profit_{item}"].iloc[0]), float(test[f"holding_cost_{item}"].iloc[0])
    pol = policy_cls(hist, promised(inst), p0, h0)
    on_hand, transit = 0.0, {}
    prev_d = prev_o = prev_a = 0.0
    out = []
    for idx in range(len(test)):
        period = idx + 1
        row = test.iloc[idx]
        lt = row[f"lead_time_{item}"]
        lt = float("inf") if (isinstance(lt, str) and lt.lower() == "inf") or np.isinf(float(lt)) else int(lt)
        state = {"period": period, "on_hand": on_hand, "in_transit": float(sum(transit.values())),
                 "previous_demand": prev_d, "previous_order": prev_o, "previous_arrivals": prev_a,
                 "p": float(row[f"profit_{item}"]), "h": float(row[f"holding_cost_{item}"])}
        q = max(0, int(pol.order(state)))
        if hasattr(pol, "record"):
            pol.record(period, q)
        out.append({"period": period, "order_quantity": q})
        if not np.isinf(lt):
            transit[period + lt] = transit.get(period + lt, 0) + q
        arr = transit.pop(period, 0)
        on_hand += arr
        d = float(row[f"demand_{item}"])
        on_hand -= min(d, on_hand)
        prev_d, prev_o, prev_a = d, q, arr
    return pd.DataFrame(out)


def main():
    commit = subprocess.run(["git", "-C", str(IB), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if commit != PINNED:
        sys.exit(f"InventoryBench commit {commit} differs from pinned {PINNED}")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = REPO / "artifacts" / "experiments" / f"IB-{stamp}"
    instances = sorted(p for p in (IB / "benchmark").glob("*/*/*") if (p / "test.csv").exists())
    summary = {}
    for name, cls in POLICIES.items():
        sub = root / name
        for inst in instances:
            rel = inst.relative_to(IB / "benchmark")
            d = sub / "results" / rel
            d.mkdir(parents=True, exist_ok=True)
            simulate(cls, inst).to_csv(d / "results.csv", index=False)
        # Official scorer from the pinned repository; isolated interpreter, paths passed as arguments.
        r = subprocess.run([sys.executable, "-I", str(IB / "eval/evaluate_results.py"), "--benchmark-dir", str(IB / "benchmark"),
                            "--submission-dir", str(sub), "--output-json", str(sub / "scores.json")],
                           capture_output=True, text=True, cwd=str(sub))
        if r.returncode:
            sys.exit(r.stderr[-2000:])
        scores = json.loads((sub / "scores.json").read_text())
        summary[name] = {"overall_score": scores.get("overall_score", scores.get("score")),
                         "batches": {k: v.get("score") for k, v in (scores.get("batch_scores") or scores.get("batches") or {}).items()}
                         if isinstance(scores.get("batch_scores") or scores.get("batches"), dict) else None}
        print(name, json.dumps(summary[name])[:400], flush=True)
    (root / "metrics.json").write_text(json.dumps({
        "experiment_id": root.name, "study": "IB", "benchmark": "InventoryBench", "benchmark_commit": commit,
        "instances": len(instances), "scorer": "eval/evaluate_results.py (official, unmodified)",
        "metric": "mean normalized reward = max(0, reward / (profit x total demand))", "policies": summary,
        "notes": ["No LLM is used; this compares deterministic decision logic only.",
                  "Real trajectories derive from H&M sales; check upstream data terms before redistribution."]}, indent=2))
    print("wrote", root.relative_to(REPO))


if __name__ == "__main__":
    main()
