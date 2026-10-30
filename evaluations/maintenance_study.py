"""PM1: predictive maintenance for the equipment that moves stock. Two parts.

(a) Failure prediction on the UCI AI4I 2020 Predictive Maintenance dataset (Matzka, 2020; CC BY 4.0; 10,000 machine
    cycles, 339 failures; a published synthetic dataset modelled on a real milling process). Logistic regression and
    LightGBM predict "machine failure" from type, temperatures, speed, torque and tool wear. The alert threshold is chosen on
    a validation split by expected cost: a missed failure costs an unplanned stop, an alert costs an inspection (both
    ASSUMED below). Compared policies: run to failure, and inspect-on-alert.
(b) Remaining useful life from sensor time series, with deep learning. A SIMULATED fleet of conveyor motors degrades
    towards failure (a hidden health index drives vibration, bearing temperature and motor current, plus noise and
    unit-to-unit variation). Models see the last 30 cycles of the three sensors: a baseline (ridge regression on window
    statistics) and a 1D convolutional network (PyTorch). Reported: RMSE and the asymmetric PHM08 score on held-out
    motors, then a maintenance simulation: fixed-interval replacement against replacing when predicted life drops below a
    margin.

Each part runs in its own process: LightGBM and PyTorch bring separate OpenMP runtimes that cannot share one (D-023).
Needs data/raw/optional/ai4i_2020/ai4i_2020.zip (scripts/download_datasets.py --dataset ai4i_2020).
uv run python evaluations/maintenance_study.py
"""
from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import zipfile
from datetime import UTC, datetime

import numpy as np

from supplylens.config import REPO_ROOT

SEED = 6
COST_MISSED = 2000.0        # ASSUMED: unplanned stop of a sorter or conveyor, one shift of delayed picking (GBP)
COST_ALERT = 150.0          # ASSUMED: technician inspection after an alert (GBP)
COST_PLANNED = 400.0        # ASSUMED (part b): planned replacement of a motor
COST_FAILURE = 2400.0       # ASSUMED (part b): replacement after a failure, including the stop
WINDOW = 30


# ------------------------------------------------------------------------------------------------ (a) AI4I 2020
def load_ai4i():
    path = REPO_ROOT / "data" / "raw" / "optional" / "ai4i_2020" / "ai4i_2020.zip"
    rows = list(csv.DictReader(io.StringIO(zipfile.ZipFile(path).read("ai4i2020.csv").decode("utf-8-sig"))))
    X = np.array([[1.0 if r["Type"] == "L" else 0.0, 1.0 if r["Type"] == "M" else 0.0,
                   float(r["Air temperature [K]"]), float(r["Process temperature [K]"]),
                   float(r["Process temperature [K]"]) - float(r["Air temperature [K]"]),
                   float(r["Rotational speed [rpm]"]), float(r["Torque [Nm]"]),
                   float(r["Torque [Nm]"]) * float(r["Rotational speed [rpm]"]) * 2 * np.pi / 60,      # power, W
                   float(r["Tool wear [min]"]), float(r["Tool wear [min]"]) * float(r["Torque [Nm]"])] for r in rows])
    y = np.array([int(r["Machine failure"]) for r in rows], dtype=float)
    modes = {m: np.array([int(r[m]) for r in rows]) for m in ("TWF", "HDF", "PWF", "OSF", "RNF")}
    names = ["type L", "type M", "air temp", "process temp", "temp difference", "speed", "torque", "power", "tool wear",
             "wear x torque"]
    return X, y, modes, names


def auc(y, p):
    order = np.argsort(p)
    ranks = np.empty(len(p))
    ranks[order] = np.arange(1, len(p) + 1)
    pos = y == 1
    return float((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * (~pos).sum()))


def pr_auc(y, p):
    order = np.argsort(-p)
    ys = y[order]
    tp = np.cumsum(ys)
    prec = tp / np.arange(1, len(ys) + 1)
    return float(np.sum(prec * ys) / max(1, ys.sum()))          # average precision


def logistic_fit(Xtr, ytr):
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
    A = np.c_[np.ones(len(Xtr)), (Xtr - mu) / sd]
    w = np.zeros(A.shape[1])
    for _ in range(3000):                                   # gradient descent with L2, balanced classes
        p = 1 / (1 + np.exp(-(A @ w)))
        wt = np.where(ytr == 1, (len(ytr) / (2 * ytr.sum())), len(ytr) / (2 * (len(ytr) - ytr.sum())))
        g = A.T @ (wt * (p - ytr)) / len(ytr) + 1e-3 * np.r_[0, w[1:]]
        w -= 0.5 * g
    return lambda X: 1 / (1 + np.exp(-(np.c_[np.ones(len(X)), (X - mu) / sd] @ w)))


def cost_threshold(y, p):
    best = None
    for t in np.unique(np.round(p, 4)):
        alert = p >= t
        cost = COST_MISSED * np.sum((~alert) & (y == 1)) + COST_ALERT * np.sum(alert)
        if best is None or cost < best[1]:
            best = (float(t), float(cost))
    return best[0]


def policy(y, p, t):
    alert = p >= t
    caught, missed = int(np.sum(alert & (y == 1))), int(np.sum((~alert) & (y == 1)))
    return {"threshold": round(t, 4), "alerts": int(alert.sum()), "failures_caught": caught, "failures_missed": missed,
            "precision": round(caught / max(1, alert.sum()), 3), "recall": round(caught / max(1, y.sum()), 3),
            "cost_gbp": float(COST_MISSED * missed + COST_ALERT * alert.sum())}


def part_a(rng):
    import lightgbm as lgb
    X, y, modes, names = load_ai4i()
    idx = rng.permutation(len(y))
    tr, va, te = idx[:6000], idx[6000:8000], idx[8000:]
    out = {"rows": int(len(y)), "failures": int(y.sum()), "split": {"train": 6000, "validation": 2000, "test": 2000},
           "test_failures": int(y[te].sum()), "models": {}}
    lr = logistic_fit(X[tr], y[tr])
    gbm = lgb.train({"objective": "binary", "learning_rate": 0.05, "num_leaves": 15, "min_data_in_leaf": 20, "seed": SEED,
                     "verbose": -1, "scale_pos_weight": 5.0}, lgb.Dataset(X[tr], y[tr], feature_name=[n.replace(" ", "_") for n in names]),
                    num_boost_round=400)
    for name, f in (("logistic_regression", lr), ("lightgbm", lambda Z: gbm.predict(Z))):
        pva, pte = f(X[va]), f(X[te])
        t = cost_threshold(y[va], pva)
        out["models"][name] = {"auc": round(auc(y[te], pte), 4), "average_precision": round(pr_auc(y[te], pte), 4),
                               "policy_on_test": policy(y[te], pte, t)}
    out["run_to_failure_cost_gbp"] = float(COST_MISSED * y[te].sum())
    imp = gbm.feature_importance("gain")
    out["lightgbm_gain_share"] = {n: round(float(v / imp.sum()), 4) for n, v in sorted(zip(names, imp, strict=True), key=lambda z: -z[1])}
    pte = gbm.predict(X[te])
    t = out["models"]["lightgbm"]["policy_on_test"]["threshold"]
    out["recall_by_failure_mode"] = {m: {"failures": int(v[te].sum()), "caught": int(np.sum((pte >= t) & (v[te] == 1)))} for m, v in modes.items()}
    out["costs_assumed"] = {"missed_failure_gbp": COST_MISSED, "alert_inspection_gbp": COST_ALERT}
    return out


# ------------------------------------------------------------------------------------------- (b) simulated fleet
def simulate_fleet(rng, n_units: int):
    units = []
    for _ in range(n_units):
        life = int(rng.integers(120, 360))                    # cycles until failure
        onset = int(life * rng.uniform(0.35, 0.65))           # wear starts to show
        k = rng.uniform(1.6, 3.0)                             # how sharply it accelerates
        base = rng.normal(0, 1, 3) * [0.15, 1.5, 0.4]         # unit-to-unit offsets
        t = np.arange(life)
        health = np.clip((t - onset) / (life - onset), 0, None) ** k     # 0 healthy .. 1 at failure
        vib = 2.0 + base[0] + 3.0 * health + rng.normal(0, 0.25, life)
        temp = 45 + base[1] + 18 * health + rng.normal(0, 1.2, life)
        cur = 8.0 + base[2] + 2.5 * health ** 1.5 + rng.normal(0, 0.3, life)
        units.append({"life": life, "x": np.stack([vib, temp, cur], 1)})
    return units


def windows(units, cap=125):
    X, y = [], []
    for u in units:
        for end in range(WINDOW, u["life"] + 1):
            X.append(u["x"][end - WINDOW:end])
            y.append(min(cap, u["life"] - end))               # piecewise-linear RUL target, capped (common practice)
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)


def phm_score(err):
    """PHM08 asymmetric score: late predictions (err > 0, predicted life too long) are penalised more."""
    return float(np.sum(np.where(err < 0, np.exp(-err / 13) - 1, np.exp(err / 10) - 1)))


def make_cnn():
    from torch import nn

    class CNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(nn.Conv1d(3, 32, 5, padding=2), nn.ReLU(), nn.Conv1d(32, 32, 5, padding=2), nn.ReLU(),
                                     nn.Conv1d(32, 32, 3, padding=1), nn.ReLU(), nn.AdaptiveAvgPool1d(1), nn.Flatten(),
                                     nn.Linear(32, 32), nn.ReLU(), nn.Linear(32, 1))

        def forward(self, x):                                 # x: (batch, window, 3)
            return self.net(x.transpose(1, 2)).squeeze(-1)
    return CNN()


def part_b(rng):
    import torch
    from torch import nn
    torch.manual_seed(SEED)
    train_u, test_u = simulate_fleet(rng, 80), simulate_fleet(rng, 30)
    Xtr, ytr = windows(train_u)
    mu, sd = Xtr.reshape(-1, 3).mean(0), Xtr.reshape(-1, 3).std(0)
    norm = lambda X: (X - mu) / sd  # noqa: E731
    # baseline: ridge regression on window summaries (last value, mean, trend, spread of each sensor)
    feats = lambda X: np.c_[np.ones(len(X)), X[:, -1, :], X.mean(1), X[:, -5:, :].mean(1) - X[:, :5, :].mean(1), X.std(1)]  # noqa: E731
    F = feats(Xtr)
    coef = np.linalg.solve(F.T @ F + 1.0 * np.eye(F.shape[1]), F.T @ ytr)
    model = make_cnn()
    opt = torch.optim.Adam(model.parameters(), lr=2e-3)
    Xt, yt = torch.tensor(norm(Xtr), dtype=torch.float32), torch.tensor(ytr)
    g = torch.Generator().manual_seed(SEED)
    for _epoch in range(25):
        perm = torch.randperm(len(Xt), generator=g)
        for i in range(0, len(Xt), 256):
            b = perm[i:i + 256]
            opt.zero_grad()
            loss = nn.functional.mse_loss(model(Xt[b]), yt[b])
            loss.backward()
            opt.step()
    model.eval()

    def predict(kind, X):
        if kind == "cnn":
            with torch.no_grad():
                return model(torch.tensor(norm(X), dtype=torch.float32)).numpy()
        return feats(X) @ coef

    # accuracy on each test motor's windows, scored where it matters most (true RUL <= 125)
    Xte, yte = windows(test_u)
    res = {}
    for kind in ("ridge_window_stats", "cnn"):
        p = predict("cnn" if kind == "cnn" else "ridge", Xte)
        err = p - yte
        last = []                                             # error at the final observed window of truncated test motors
        res[kind] = {"rmse_all_windows": round(float(np.sqrt(np.mean(err ** 2))), 2),
                     "rmse_last_50_cycles": round(float(np.sqrt(np.mean(err[yte <= 50] ** 2))), 2),
                     "phm_score_per_motor": round(phm_score(err[yte <= 125]) / len(test_u), 1)}
        del last

    # maintenance simulation on the test motors: each starts new; decide every cycle
    def run(rule):
        cost, failures, wasted = 0.0, 0, []
        for u in test_u:
            stop = None
            for end in range(WINDOW, u["life"] + 1):
                if rule[0] == "fixed" and end >= rule[1]:
                    stop = end
                    break
                if rule[0] in ("cnn", "ridge") and end % 5 == 0:
                    if predict(rule[0], u["x"][end - WINDOW:end][None])[0] <= rule[1]:
                        stop = end
                        break
            if stop is None or stop >= u["life"]:
                cost += COST_FAILURE
                failures += 1
                wasted.append(0)
            else:
                cost += COST_PLANNED
                wasted.append(u["life"] - stop)
        return {"cost_gbp": cost, "failures": failures, "planned": len(test_u) - failures,
                "mean_unused_life_cycles": round(float(np.mean(wasted)), 1)}

    lives = np.array([u["life"] for u in train_u])
    policies = {"run_to_failure": run(("fixed", 10**9))}
    for q in (0.05, 0.2):
        policies[f"fixed_interval_p{int(q * 100)}"] = run(("fixed", int(np.quantile(lives, q))))
    for margin in (10, 20, 30):
        policies[f"cnn_rul_below_{margin}"] = run(("cnn", margin))
        policies[f"ridge_rul_below_{margin}"] = run(("ridge", margin))
    curve = []                                                # one test motor: true vs predicted RUL for the figure
    u = test_u[0]
    for end in range(WINDOW, u["life"] + 1, 3):
        w = u["x"][end - WINDOW:end][None]
        curve.append({"cycle": end, "true": min(125, u["life"] - end), "cnn": round(float(predict("cnn", w)[0]), 1),
                      "ridge": round(float(predict("ridge", w)[0]), 1)})
    return {"fleet": {"train_motors": 80, "test_motors": 30, "train_windows": int(len(Xtr)), "test_windows": int(len(Xte)),
                      "window_cycles": WINDOW, "rul_cap": 125},
            "accuracy": res, "policies": policies, "example_motor": curve,
            "costs_assumed": {"planned_replacement_gbp": COST_PLANNED, "failure_gbp": COST_FAILURE}}


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in ("a", "b"):          # child process: one part, JSON on stdout
        rng = np.random.default_rng(SEED if sys.argv[1] == "a" else SEED + 1)
        print(json.dumps(part_a(rng) if sys.argv[1] == "a" else part_b(rng), default=float))
        return
    run = lambda part: json.loads(subprocess.run([sys.executable, __file__, part], capture_output=True, text=True,  # noqa: E731
                                                 check=True).stdout.strip().splitlines()[-1])
    a, b = run("a"), run("b")
    print(json.dumps({k: a[k] for k in ("models", "run_to_failure_cost_gbp", "recall_by_failure_mode")}, indent=1))
    print(json.dumps({"accuracy": b["accuracy"], "policies": b["policies"]}, indent=1))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = REPO_ROOT / "artifacts" / "experiments" / f"PM1-{stamp}"
    out.mkdir(parents=True)
    metrics = {"experiment_id": out.name, "study": "PM1", "kind": "measured (a: published synthetic dataset) and simulated (b)",
               "question": "Can failures and remaining life be predicted early enough to replace run-to-failure and fixed-interval maintenance?",
               "ai4i_2020": a, "fleet_rul": b, "seed": SEED,
               "sources": ["Matzka, S. (2020). AI4I 2020 Predictive Maintenance Dataset. UCI Machine Learning Repository. https://doi.org/10.24432/C5HS5C"],
               "limits": ["AI4I 2020 is itself synthetic (modelled on a real process), not observed failures",
                          "part (b) fleet, its degradation process and all costs are assumed",
                          "one random split for (a); one simulated fleet for (b)"]}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str))
    print(out.name)


if __name__ == "__main__":
    main()
