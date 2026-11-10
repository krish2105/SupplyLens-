"""B1: class imbalance and group parity on AI4I 2020 (course Week 10: re-sampling, re-weighting, adversarial debiasing).

Data and costs are PM1 part (a)'s, reused from evaluations/maintenance_study.py: the UCI AI4I 2020 dataset (Matzka, 2020;
CC BY 4.0; synthetic data modelled on a milling process; 3.4 % of cycles fail), the same features, the same 60/20/20
split (seed 6) and the same ASSUMED costs (missed failure GBP 2,000, inspection GBP 150).

Imbalance methods, each with logistic regression and with LightGBM (PM1's settings):
1. none: no correction, alert at p >= 0.5;
2. class weights: each class carries half the training weight (re-weighting);
3. group-and-class weights: Kamiran & Calders reweighing (weight P(g)P(y)/P(g,y)) times the class weights, so in every
   Type the failures and the non-failures each carry half of that Type's weight;
4. SMOTE on the training fold only (SMOTENC: Type is categorical); synthetic machines are interpolated in the raw sensor
   space and the derived features (temperature difference, power, wear x torque) are recomputed; validation and test
   rows never reach the sampler;
5. threshold moving: the unweighted model, alert threshold chosen on validation by assumed cost (PM1's rule). Each of
   2-4 is also reported with the cost threshold ("+threshold").
Adversarial debiasing (Zhang, Lemoine & Mitchell, 2018) runs in PyTorch in a child process (evaluations/
adversarial_child.py; LightGBM and PyTorch cannot share a process, D-023): a logistic predictor with class weights and an
adversary that tries to recover Type from the predictor's output and the label; 5 seeds, alpha chosen on validation.

Group attribute: machine Type (L/M/H), a product-quality variant, NOT a protected human attribute. It stands in for a
group to demonstrate the parity screen. Reported on test: recall, precision, PR-AUC (average precision), cost; per Type
recall (with a Wilson 95 % interval) and false-positive rate, n, failures, and the largest gap between Types.

uv run --with scikit-learn==1.7.2 --with imbalanced-learn==0.14.0 python evaluations/imbalance_study.py
"""
from __future__ import annotations

import importlib.util
import json
import platform
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from supplylens.config import REPO_ROOT

_spec = importlib.util.spec_from_file_location("maintenance_study", Path(__file__).with_name("maintenance_study.py"))
PM1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PM1)

SEED = PM1.SEED                     # PM1(a)'s split seed
COST_MISSED, COST_ALERT = PM1.COST_MISSED, PM1.COST_ALERT
GROUPS = ("L", "M", "H")
MIN_GROUP_FAILURES = 10             # a Type with fewer test failures is reported but left out of the "large groups" gap
SMOTE_SEEDS = (6, 7, 8, 9, 10)
ADV_SEEDS = (0, 1, 2, 3, 4)
ADV_ALPHAS = (0.01, 0.03, 0.1, 0.3, 1.0)
ADV_CFG = {"steps": 3000, "lr": 0.05, "lr_final": 0.0005, "C": 1.0}     # full-batch Adam, decaying lr
ADV_COST_SLACK = 0.10               # alpha rule: validation cost at most 10 % above the adversary-off model
PM1_RUN = "PM1-20261030T192104Z"
LGBM_PARAMS = {"objective": "binary", "learning_rate": 0.05, "num_leaves": 15, "min_data_in_leaf": 20, "seed": SEED,
               "verbose": -1}       # PM1's, without its scale_pos_weight (weights are the method under test here)
LGBM_ROUNDS = 400
COMMAND = ("uv run --with scikit-learn==1.7.2 --with imbalanced-learn==0.14.0 python evaluations/imbalance_study.py")


# ------------------------------------------------------------------------------------------------ data helpers
def split(n: int, seed: int = SEED):
    """PM1(a)'s split: the first draw of default_rng(seed) is a permutation; 60/20/20."""
    idx = np.random.default_rng(seed).permutation(n)
    a, b = int(n * 0.6), int(n * 0.8)
    return idx[:a], idx[a:b], idx[b:]


def groups_of(X):
    """Type from PM1's one-hot columns (0 = type L, 1 = type M; neither = H)."""
    return np.where(X[:, 0] == 1, "L", np.where(X[:, 1] == 1, "M", "H"))


def raw_from_features(X):
    """[type code (L=0, M=1, H=2), air K, process K, speed rpm, torque Nm, tool wear min] from PM1's feature matrix."""
    code = np.where(X[:, 0] == 1, 0.0, np.where(X[:, 1] == 1, 1.0, 2.0))
    return np.c_[code, X[:, 2], X[:, 3], X[:, 5], X[:, 6], X[:, 8]]


def derive(raw):
    """PM1's feature columns from raw values (same order and formulas as maintenance_study.load_ai4i)."""
    code, air, proc, speed, torque, wear = raw.T
    return np.c_[(code == 0).astype(float), (code == 1).astype(float), air, proc, proc - air, speed, torque,
                 torque * speed * 2 * np.pi / 60, wear, wear * torque]


def oversample_training_fold(raw, y, tr, sampler):
    """Fit the over-sampler on the training rows only; validation and test rows never reach it. Continuous columns are
    standardised with training statistics for the neighbour search and mapped back afterwards; column 0 (Type) is left
    as a category. Returns raw rows: the originals first, then the synthetic ones (imbalanced-learn's order)."""
    Xtr = raw[tr].astype(float).copy()
    mu, sd = Xtr[:, 1:].mean(0), Xtr[:, 1:].std(0) + 1e-12
    Xtr[:, 1:] = (Xtr[:, 1:] - mu) / sd
    Xr, yr = sampler.fit_resample(Xtr, y[tr])
    Xr = np.asarray(Xr, dtype=float).copy()
    Xr[:, 1:] = Xr[:, 1:] * sd + mu
    return Xr, np.asarray(yr, dtype=float)


def class_weights(y):
    """Balanced: each class carries half of the total weight (scikit-learn's class_weight='balanced')."""
    n, n_pos = len(y), y.sum()
    return np.where(y == 1, n / (2 * n_pos), n / (2 * (n - n_pos)))


def group_class_weights(y, g):
    """Kamiran & Calders reweighing P(g)P(y)/P(g,y) times balanced class weights = n_g / (2 n_gy): inside each Type,
    failures and non-failures each carry half of the Type's weight."""
    w = np.zeros(len(y))
    for k in np.unique(g):
        for c in (0, 1):
            m = (g == k) & (y == c)
            if m.any():
                w[m] = (g == k).sum() / (2 * m.sum())
    return w


# --------------------------------------------------------------------------------------------- metric helpers
def cost_gbp(y, alert) -> float:
    """PM1's cost: every missed failure costs COST_MISSED, every alert (caught or not) COST_ALERT."""
    alert = np.asarray(alert, dtype=bool)
    return float(COST_MISSED * np.sum((~alert) & (y == 1)) + COST_ALERT * np.sum(alert))


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return None
    p = k / n
    centre, half = (p + z * z / (2 * n)) / (1 + z * z / n), z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(float(centre - half), 4), round(float(centre + half), 4)]


def group_rates(y, alert, g, labels=GROUPS):
    alert = np.asarray(alert, dtype=bool)
    out = {}
    for k in labels:
        m = g == k
        pos, neg = m & (y == 1), m & (y == 0)
        tp, fp = int(np.sum(alert & pos)), int(np.sum(alert & neg))
        out[k] = {"n": int(m.sum()), "failures": int(pos.sum()), "alerts": int(np.sum(alert & m)),
                  "recall": round(tp / pos.sum(), 4) if pos.sum() else None, "recall_ci95": wilson(tp, int(pos.sum())),
                  "fpr": round(fp / neg.sum(), 4) if neg.sum() else None}
    return out


def gap(per_group, key, min_failures: int = 0):
    """Largest minus smallest rate over the groups where it is defined (and that have >= min_failures failures)."""
    vals = [v[key] for v in per_group.values() if v[key] is not None and v["failures"] >= min_failures]
    return round(max(vals) - min(vals), 4) if len(vals) >= 2 else None


def evaluate(y, p, t, g):
    alert = p >= t
    caught = int(np.sum(alert & (y == 1)))
    per = group_rates(y, alert, g)
    return {"threshold": round(float(t), 4), "alerts": int(alert.sum()), "failures_caught": caught,
            "failures_missed": int(y.sum()) - caught, "recall": round(caught / max(1, y.sum()), 4),
            "precision": round(caught / max(1, alert.sum()), 4), "pr_auc": round(PM1.pr_auc(y, p), 4),
            "cost_gbp": cost_gbp(y, alert), "per_group": per, "recall_gap": gap(per, "recall"), "fpr_gap": gap(per, "fpr"),
            "recall_gap_groups_with_10_failures": gap(per, "recall", MIN_GROUP_FAILURES)}


def paired_cost_delta_ci(y, alert_a, alert_b, reps: int = 2000, seed: int = SEED):
    """95 % paired bootstrap interval (over test rows) of cost(a) - cost(b)."""
    row = lambda a: COST_MISSED * ((~a) & (y == 1)) + COST_ALERT * a  # noqa: E731
    d = row(np.asarray(alert_a, bool)) - row(np.asarray(alert_b, bool))
    s = d[np.random.default_rng(seed).integers(0, len(y), (reps, len(y)))].sum(1)
    return [float(np.quantile(s, 0.025)), float(np.quantile(s, 0.975))]


# ------------------------------------------------------------------------------------------------- learners
def fit_lr(X, y, w=None):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    m = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=5000))
    m.fit(X, y, logisticregression__sample_weight=w)
    return lambda Z: m.predict_proba(Z)[:, 1]


def fit_lgbm(X, y, w=None):
    import lightgbm as lgb
    b = lgb.train(LGBM_PARAMS, lgb.Dataset(X, y, weight=w), num_boost_round=LGBM_ROUNDS)
    return lambda Z: b.predict(Z)


def smote_rows(raw, y, tr, seed):
    from imblearn.over_sampling import SMOTENC
    Xr, yr = oversample_training_fold(raw, y, tr, SMOTENC(categorical_features=[0], k_neighbors=5, random_state=seed))
    return derive(Xr), yr, Xr[:, 0]


def run_learner(fit, X, y, g, tr, va, te, smote):
    Xs, ys = smote
    variants = {"none": fit(X[tr], y[tr]), "class_weights": fit(X[tr], y[tr], class_weights(y[tr])),
                "group_class_weights": fit(X[tr], y[tr], group_class_weights(y[tr], g[tr])), "smote": fit(Xs, ys)}
    res, alerts = {}, {}
    for name, f in variants.items():
        pva, pte = f(X[va]), f(X[te])
        tag = "threshold_moving" if name == "none" else f"{name}+threshold"
        for key, t in ((name, 0.5), (tag, PM1.cost_threshold(y[va], pva))):
            res[key] = evaluate(y[te], pte, t, g[te])
            alerts[key] = pte >= t
    order = ["none", "class_weights", "group_class_weights", "smote", "threshold_moving", "class_weights+threshold",
             "group_class_weights+threshold", "smote+threshold"]
    for k in order:
        res[k]["cost_delta_vs_none_ci95"] = paired_cost_delta_ci(y[te], alerts[k], alerts["none"])
    return {k: res[k] for k in order}


# -------------------------------------------------------------------------------------------- adversarial
def run_adversarial(X, y, g, tr, va, te):
    code = np.array([GROUPS.index(k) for k in g])
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "in.npz", Path(d) / "out.npz"
        np.savez(src, X=X, y=y, g=code, tr=tr, va=va, te=te)
        cfg = {"seeds": list(ADV_SEEDS), "alphas": list(ADV_ALPHAS), **ADV_CFG}
        r = subprocess.run([sys.executable, str(Path(__file__).with_name("adversarial_child.py")), str(src), str(dst),
                            json.dumps(cfg)], capture_output=True, text=True, check=True, timeout=3600)
        info = json.loads(r.stdout.strip().splitlines()[-1])
        out = np.load(dst)
        p_va, p_te = out["p_va"], out["p_te"]
    runs = {}
    for ci, name in enumerate(info["configs"]):
        per_seed = {"0.5": [], "threshold": []}
        val = []
        for si in range(len(ADV_SEEDS)):
            per_seed["0.5"].append(evaluate(y[te], p_te[ci, si], 0.5, g[te]))
            per_seed["threshold"].append(evaluate(y[te], p_te[ci, si], PM1.cost_threshold(y[va], p_va[ci, si]), g[te]))
            val.append(evaluate(y[va], p_va[ci, si], 0.5, g[va]))
        runs[name] = {"alpha": info["alphas"][ci], "test_at_0.5": aggregate(per_seed["0.5"]),
                      "test_at_cost_threshold": aggregate(per_seed["threshold"]), "validation_at_0.5": aggregate(val),
                      "probe_type_from_output": aggregate_flat(info["probe"][name])}
    off = runs["off"]["validation_at_0.5"]["mean"]
    eligible = [n for n in runs if n != "off" and runs[n]["validation_at_0.5"]["mean"]["cost_gbp"] <= (1 + ADV_COST_SLACK) * off["cost_gbp"]]
    score = lambda n: runs[n]["validation_at_0.5"]["mean"]["recall_gap"] + runs[n]["validation_at_0.5"]["mean"]["fpr_gap"]  # noqa: E731
    chosen = min(eligible, key=score) if eligible else None
    return runs, chosen, info


def aggregate_flat(rows):
    keys = rows[0].keys()
    return {"mean": {k: round(float(np.mean([r[k] for r in rows])), 4) for k in keys},
            "sd": {k: round(float(np.std([r[k] for r in rows], ddof=1)), 4) for k in keys}}


def aggregate(rows):
    """Mean and sd (ddof=1) over seeds of the scalar metrics and of each group's recall and FPR."""
    scal = ["recall", "precision", "pr_auc", "cost_gbp", "alerts", "threshold", "recall_gap", "fpr_gap",
            "recall_gap_groups_with_10_failures"]
    m = lambda vals: round(float(np.mean(vals)), 4)  # noqa: E731
    s = lambda vals: round(float(np.std(vals, ddof=1)), 4)  # noqa: E731
    mean = {k: m([r[k] for r in rows]) for k in scal if all(r[k] is not None for r in rows)}
    sd = {k: s([r[k] for r in rows]) for k in scal if all(r[k] is not None for r in rows)}
    per = {}
    for k in GROUPS:
        g0 = rows[0]["per_group"][k]
        per[k] = {"n": g0["n"], "failures": g0["failures"]}
        for key in ("recall", "fpr"):
            vals = [r["per_group"][k][key] for r in rows]
            if all(v is not None for v in vals):
                per[k][key], per[k][key + "_sd"] = m(vals), s(vals)
    mean["per_group"] = per
    return {"mean": mean, "sd": sd, "seeds": len(rows)}


# ------------------------------------------------------------------------------------------------------ main
def main() -> None:
    t0 = time.perf_counter()
    import imblearn
    import lightgbm
    import sklearn
    X, y, _modes, _names = PM1.load_ai4i()
    g = groups_of(X)
    raw = raw_from_features(X)
    if not np.allclose(derive(raw), X):
        raise SystemExit("feature derivation does not reproduce PM1's features")
    tr, va, te = split(len(y))

    # check: PM1's own logistic model on this split reproduces PM1's recorded test policy
    pm1_lr = PM1.logistic_fit(X[tr], y[tr])
    pm1_policy = PM1.policy(y[te], pm1_lr(X[te]), PM1.cost_threshold(y[va], pm1_lr(X[va])))
    pm1_file = REPO_ROOT / "artifacts" / "experiments" / PM1_RUN / "metrics.json"
    recorded = (json.loads(pm1_file.read_text())["ai4i_2020"]["models"]["logistic_regression"]["policy_on_test"]
                if pm1_file.exists() else None)

    Xs, ys, scode = smote_rows(raw, y, tr, SEED)
    smote_info = {"train_rows_before": int(len(tr)), "train_failures_before": int(y[tr].sum()), "rows_after": int(len(ys)),
                  "failures_after": int(ys.sum()), "synthetic_rows": int(len(ys) - len(tr)),
                  "synthetic_by_type": {k: int(np.sum(scode[len(tr):] == i)) for i, k in enumerate(GROUPS)},
                  "train_failures_by_type": {k: int(np.sum((g[tr] == k) & (y[tr] == 1))) for k in GROUPS}}
    methods = {"logistic_regression": run_learner(fit_lr, X, y, g, tr, va, te, (Xs, ys)),
               "lightgbm": run_learner(fit_lgbm, X, y, g, tr, va, te, (Xs, ys))}

    spread = {}                                                  # SMOTE's own randomness: other sampler seeds
    for learner, fit in (("logistic_regression", fit_lr), ("lightgbm", fit_lgbm)):
        rows = {"smote": [], "smote+threshold": []}
        for s in SMOTE_SEEDS:
            Xs2, ys2, _ = smote_rows(raw, y, tr, s)
            f = fit(Xs2, ys2)
            pva, pte = f(X[va]), f(X[te])
            rows["smote"].append(evaluate(y[te], pte, 0.5, g[te]))
            rows["smote+threshold"].append(evaluate(y[te], pte, PM1.cost_threshold(y[va], pva), g[te]))
        spread[learner] = {k: aggregate(v) for k, v in rows.items()}

    runs, chosen, info = run_adversarial(X, y, g, tr, va, te)
    off, deb = runs["off"], runs[chosen] if chosen else None
    flat = lambda a: dict(a["mean"]) | {"sd": a["sd"], "seeds": a["seeds"]}  # noqa: E731
    methods["adversarial_logistic_torch"] = {
        "adversary_off": flat(off["test_at_0.5"]), "adversarial_debiasing": flat(deb["test_at_0.5"]) if deb else None,
        "adversary_off+threshold": flat(off["test_at_cost_threshold"]),
        "adversarial_debiasing+threshold": flat(deb["test_at_cost_threshold"]) if deb else None}

    gte = {k: {"n": int(np.sum(g[te] == k)), "failures": int(np.sum((g[te] == k) & (y[te] == 1)))} for k in GROUPS}
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = REPO_ROOT / "artifacts" / "experiments" / f"B1-{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    libraries = {"python": platform.python_version(), "numpy": np.__version__, "lightgbm": lightgbm.__version__,
                 "scikit-learn": sklearn.__version__, "imbalanced-learn": imblearn.__version__, "torch": info["torch"]}
    metrics = {
        "experiment_id": out.name, "study": "B1", "kind": "measured (published synthetic dataset AI4I 2020)",
        "question": ("Do re-sampling (SMOTE), re-weighting, threshold moving and adversarial debiasing improve failure "
                     "detection under 3.4 % failures, and do they narrow the gap in recall and false-positive rate "
                     "between machine Types L, M and H?"),
        "data": {"rows": int(len(y)), "failures": int(y.sum()), "split": {"train": int(len(tr)), "validation": int(len(va)),
                                                                          "test": int(len(te))},
                 "test_failures": int(y[te].sum()), "groups": gte,
                 "groups_all_rows": {k: {"n": int(np.sum(g == k)), "failures": int(np.sum((g == k) & (y == 1)))} for k in GROUPS},
                 "group_attribute": "machine Type (L/M/H), a product-quality variant; not a protected human attribute"},
        "split_check": {"pm1_logistic_policy_here": pm1_policy, "pm1_logistic_policy_recorded": recorded,
                        "reproduced": recorded is not None and all(pm1_policy[k] == recorded[k] for k in recorded)},
        "smote": smote_info, "methods": methods, "smote_seed_spread": spread,
        "adversarial": {"paper": "Zhang, Lemoine & Mitchell (2018), equality-of-odds adversary, projection update",
                        "seeds": list(ADV_SEEDS), "alphas": list(ADV_ALPHAS), "alpha_chosen": runs[chosen]["alpha"] if chosen else None,
                        "rule": (f"smallest mean validation (recall gap + FPR gap) at threshold 0.5 among alphas whose mean "
                                 f"validation cost is at most {ADV_COST_SLACK:.0%} above the adversary-off model's; chosen "
                                 "before test is read"),
                        "mean": deb["test_at_0.5"]["mean"] if deb else None, "sd": deb["test_at_0.5"]["sd"] if deb else None,
                        "off_mean": off["test_at_0.5"]["mean"], "off_sd": off["test_at_0.5"]["sd"],
                        "sweep": runs, "child_seconds": info["seconds"]},
        "parity_screen_d1": {"done": False, "why": ("D1's delivery-history generator reads supplier terms and weekly sales "
                                                    "from the PostgreSQL workspace (tenant_session); this study was kept "
                                                    "database-free, so the supplier screen was not run")},
        "libraries": libraries, "costs_assumed": {"missed_failure_gbp": COST_MISSED, "alert_inspection_gbp": COST_ALERT},
        "sources": ["Matzka, S. (2020). AI4I 2020 Predictive Maintenance Dataset. UCI Machine Learning Repository. https://doi.org/10.24432/C5HS5C",
                    "Chawla, N. V., Bowyer, K. W., Hall, L. O., Kegelmeyer, W. P. (2002). SMOTE: Synthetic Minority Over-sampling Technique. JAIR 16, 321-357",
                    "Kamiran, F., Calders, T. (2012). Data preprocessing techniques for classification without discrimination. Knowledge and Information Systems 33, 1-33",
                    "Zhang, B. H., Lemoine, B., Mitchell, M. (2018). Mitigating Unwanted Biases with Adversarial Learning. AIES 2018"],
        "limits": [
            "AI4I 2020 is itself synthetic (modelled on a real milling process), not observed failures",
            "Type is a product-quality variant, not a protected human attribute: it demonstrates the method only. In the "
            "generator, failure mechanics differ by Type (the overstrain limit and tool-wear increment depend on it), so "
            "equal error rates across Types are not a requirement here",
            f"one fixed split (PM1's, seed {SEED}); {int(y[te].sum())} test failures; type H has {gte['H']['failures']} test "
            f"failures, so its recall moves {round(100 / max(1, gte['H']['failures']))} points per failure and dominates the "
            "three-group recall gap (Wilson 95 % intervals per group are given)",
            f"recall_gap_groups_with_10_failures leaves out Types with fewer than {MIN_GROUP_FAILURES} test failures",
            "costs are PM1's ASSUMED values; cost_gbp is the realised cost on the test split under them",
            "methods 1-4 alert at p >= 0.5; '+threshold' and threshold_moving use PM1's cost threshold chosen on validation",
            "SMOTE rows are interpolated machines and may be physically implausible; derived features are recomputed",
            "adversarial: a linear predictor trained full-batch with class weights in PyTorch; its sd over 5 seeds reflects "
            "only the initial weights of predictor and adversary, not resampling of data (with the adversary off the "
            "predictor converges to the scikit-learn class-weighted model, so its sd is near zero)",
            "the Type probe is linear in the predictor's logit and the label; a richer probe might find more",
            "the D1 supplier parity screen was not run (needs the database)"],
        "seconds": round(time.perf_counter() - t0, 1),
    }
    config = {"seed": SEED, "split": "default_rng(6).permutation(10000): 6000 / 2000 / 2000 (PM1 part a)",
              "features": "PM1's 10 columns (type L, type M, air, process, difference, speed, torque, power, tool wear, wear x torque)",
              "logistic_regression": "scikit-learn StandardScaler + LogisticRegression(C=1.0, lbfgs, max_iter=5000)",
              "lightgbm": {"params": LGBM_PARAMS, "rounds": LGBM_ROUNDS},
              "smote": {"sampler": "imblearn SMOTENC(categorical_features=[Type], k_neighbors=5, sampling_strategy='auto')",
                        "space": "raw columns, continuous ones standardised with training statistics", "random_state": SEED,
                        "spread_seeds": list(SMOTE_SEEDS)},
              "class_weights": "n / (2 n_class)", "group_class_weights": "n_type / (2 n_type_class)",
              "threshold_rule": "PM1 cost_threshold on validation: minimise 2000 x missed + 150 x alerts",
              "adversarial": {"seeds": list(ADV_SEEDS), "alphas": list(ADV_ALPHAS), **ADV_CFG,
                              "cost_slack": ADV_COST_SLACK,
                              "predictor": "nn.Linear(10, 1) on standardised features, balanced class weights, L2 as scikit-learn C=1",
                              "adversary": "nn.Linear(3, 3) on [s, s*y, s*(1-y)], s = sigmoid((1+|c|) logit)",
                              "probe": "multinomial logistic on [z, z*y, y], fitted on validation, scored on test"},
              "min_group_failures": MIN_GROUP_FAILURES, "bootstrap": {"reps": 2000, "seed": SEED, "kind": "paired over test rows"},
              "libraries": libraries, "command": COMMAND, "pm1_run_checked": PM1_RUN}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=float))
    (out / "config.json").write_text(json.dumps(config, indent=1, default=float))
    brief = {learner: {k: (v["recall"], v["cost_gbp"], v["recall_gap"], v["fpr_gap"]) for k, v in ms.items() if v}
             for learner, ms in methods.items()}
    print(json.dumps({"experiment_id": out.name, "split_check": metrics["split_check"]["reproduced"], "groups": gte,
                      "methods (recall, cost, recall gap, fpr gap)": brief, "alpha_chosen": metrics["adversarial"]["alpha_chosen"],
                      "seconds": metrics["seconds"]}, indent=1))


if __name__ == "__main__":
    main()
