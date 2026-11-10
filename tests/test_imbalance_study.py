"""B1 imbalance and group parity study (week 10): the helpers the study relies on. No torch, scikit-learn or
imbalanced-learn in this process (D-023; the last two are not in the lock file): the real sampler is replaced by a
recording stand-in, and the PyTorch child is exercised in its own process."""
import importlib.util
import io
import json
import subprocess
import sys
import zipfile

import numpy as np
import pytest

from supplylens.config import REPO_ROOT

spec = importlib.util.spec_from_file_location("imbalance_study", REPO_ROOT / "evaluations" / "imbalance_study.py")
b1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b1)
pm1 = b1.PM1


class RecordingSampler:
    """Stands in for SMOTENC: records what it was given and appends copies of the minority rows (shifted slightly)."""

    def __init__(self):
        self.seen = None

    def fit_resample(self, X, y):
        self.seen = X.copy()
        extra = X[y == 1] + 0.01
        return np.r_[X, extra], np.r_[y, np.ones(len(extra))]


def test_split_is_pm1s_and_disjoint():
    tr, va, te = b1.split(10000, 6)
    idx = np.random.default_rng(6).permutation(10000)            # PM1(a): rng = default_rng(SEED); rng.permutation(n)
    assert (len(tr), len(va), len(te)) == (6000, 2000, 2000)
    assert np.array_equal(tr, idx[:6000]) and np.array_equal(va, idx[6000:8000]) and np.array_equal(te, idx[8000:])
    assert not (set(tr) & set(va) or set(tr) & set(te) or set(va) & set(te))
    assert b1.SEED == pm1.SEED == 6


def test_oversampling_sees_and_returns_only_training_rows():
    rng = np.random.default_rng(0)
    raw = np.c_[rng.integers(0, 3, 100).astype(float), rng.normal(300, 2, (100, 5))]
    y = (np.arange(100) % 10 == 0).astype(float)
    tr, va, te = b1.split(100, 1)
    raw[va, 1:] = -999.0                                         # sentinels: any use of validation or test rows shows up
    raw[te, 1:] = 999999.0
    sampler = RecordingSampler()
    Xr, yr = b1.oversample_training_fold(raw, y, tr, sampler)
    assert len(sampler.seen) == len(tr)                          # the sampler got the training rows and nothing else
    assert np.allclose(Xr[:len(tr)], raw[tr]) and np.array_equal(yr[:len(tr)], y[tr])
    assert len(Xr) == len(tr) + int(y[tr].sum())
    assert not np.isin([-999.0, 999999.0], Xr).any()
    assert Xr[:, 1:].min() > 250 and Xr[:, 1:].max() < 350      # scaling used training statistics only
    assert np.array_equal(sampler.seen[:, 0], raw[tr, 0])        # Type passed through as a category, not standardised


def test_features_rebuilt_from_raw_match_pm1s_loader(tmp_path, monkeypatch):
    head = ("UDI,Product ID,Type,Air temperature [K],Process temperature [K],Rotational speed [rpm],Torque [Nm],"
            "Tool wear [min],Machine failure,TWF,HDF,PWF,OSF,RNF\n")
    rows = ["1,L1,L,298.1,308.6,1551,42.8,0,0,0,0,0,0,0", "2,M2,M,298.2,308.7,1408,46.3,3,1,0,0,0,1,0",
            "3,H3,H,299.0,310.1,1282,60.7,215,1,0,1,0,0,0"]
    target = tmp_path / "data" / "raw" / "optional" / "ai4i_2020"
    target.mkdir(parents=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ai4i2020.csv", head + "\n".join(rows) + "\n")
    (target / "ai4i_2020.zip").write_bytes(buf.getvalue())
    monkeypatch.setattr(pm1, "REPO_ROOT", tmp_path)
    X, y, _, _ = pm1.load_ai4i()
    assert list(b1.groups_of(X)) == ["L", "M", "H"]
    raw = b1.raw_from_features(X)
    assert np.allclose(raw[2], [2, 299.0, 310.1, 1282, 60.7, 215])
    assert np.allclose(b1.derive(raw), X)                        # SMOTE rows get exactly PM1's derived features
    assert np.allclose(b1.derive(raw)[0, 7], 42.8 * 1551 * 2 * np.pi / 60)


def test_per_group_recall_fpr_and_gaps_on_a_toy_example():
    g = np.array(["L"] * 5 + ["M"] * 3 + ["H"] * 2)
    y = np.array([1, 1, 0, 0, 0, 1, 0, 0, 0, 0], dtype=float)
    alert = np.array([1, 0, 1, 0, 0, 1, 0, 0, 0, 1], dtype=bool)
    r = b1.group_rates(y, alert, g)
    assert r["L"] == {"n": 5, "failures": 2, "alerts": 2, "recall": 0.5, "recall_ci95": b1.wilson(1, 2), "fpr": round(1 / 3, 4)}
    assert (r["M"]["recall"], r["M"]["fpr"], r["M"]["n"]) == (1.0, 0.0, 3)
    assert (r["H"]["recall"], r["H"]["fpr"], r["H"]["failures"]) == (None, 0.5, 0)   # no failures: recall undefined
    assert b1.gap(r, "recall") == 0.5                            # H has no recall, so the gap is M - L
    assert b1.gap(r, "fpr") == 0.5                               # H 0.5 - M 0.0
    assert b1.gap(r, "recall", min_failures=2) is None           # only L has two failures: no pair to compare
    e = b1.evaluate(y, alert.astype(float), 0.5, g)
    assert (e["recall"], e["precision"], e["alerts"], e["failures_missed"]) == (round(2 / 3, 4), 0.5, 4, 1)


def test_wilson_interval():
    assert b1.wilson(0, 0) is None
    lo, hi = b1.wilson(5, 10)
    assert abs(lo - 0.2366) < 1e-3 and abs(hi - 0.7634) < 1e-3
    lo, hi = b1.wilson(0, 4)
    assert lo == 0.0 and 0.48 < hi < 0.50


def test_cost_matches_pm1s_definition():
    y = np.array([1, 1, 0, 0, 0, 1], dtype=float)
    alert = np.array([1, 0, 1, 1, 0, 0], dtype=bool)             # 2 missed, 3 alerts
    assert b1.cost_gbp(y, alert) == 2 * 2000 + 3 * 150 == 4450
    rng = np.random.default_rng(3)
    y, p = (rng.random(500) < 0.05).astype(float), rng.random(500)
    for t in (0.1, 0.5, 0.9):
        assert b1.cost_gbp(y, p >= t) == pm1.policy(y, p, t)["cost_gbp"]
    assert (b1.COST_MISSED, b1.COST_ALERT) == (pm1.COST_MISSED, pm1.COST_ALERT) == (2000.0, 150.0)
    lo, hi = b1.paired_cost_delta_ci(y, p >= 0.5, p >= 0.5)
    assert lo == hi == 0.0


def test_weights_balance_classes_and_groups():
    y = np.array([1, 0, 0, 0, 1, 1, 0, 0, 0, 0], dtype=float)
    g = np.array(["L", "L", "L", "L", "M", "M", "M", "H", "H", "H"])
    w = b1.class_weights(y)
    assert np.isclose(w[y == 1].sum(), w[y == 0].sum()) and np.isclose(w.sum(), len(y))
    gw = b1.group_class_weights(y, g)
    for k in ("L", "M"):                                         # inside each Type: failures and non-failures half each
        m = g == k
        assert np.isclose(gw[m & (y == 1)].sum(), m.sum() / 2) and np.isclose(gw[m & (y == 0)].sum(), m.sum() / 2)
    assert np.allclose(gw[g == "H"], 0.5)                        # H has no failures: its rows keep half weight


@pytest.mark.skipif(importlib.util.find_spec("torch") is None, reason="torch not installed")   # no import here (D-023)
def test_adversarial_child_runs_in_its_own_process(tmp_path):
    rng = np.random.default_rng(0)
    n = 300
    X = rng.normal(size=(n, 4))
    g = rng.integers(0, 3, n)
    y = ((X[:, 0] + 0.5 * g + rng.normal(size=n)) > 1.5).astype(float)
    idx = rng.permutation(n)
    src, dst = tmp_path / "in.npz", tmp_path / "out.npz"
    np.savez(src, X=X, y=y, g=g, tr=idx[:180], va=idx[180:240], te=idx[240:])
    cfg = {"seeds": [0, 1], "alphas": [0.1], "steps": 50, "lr": 0.05, "lr_final": 0.005, "C": 1.0}
    r = subprocess.run([sys.executable, str(REPO_ROOT / "evaluations" / "adversarial_child.py"), str(src), str(dst),
                        json.dumps(cfg)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    info = json.loads(r.stdout.strip().splitlines()[-1])
    assert info["configs"] == ["off", "alpha_0.1"] and len(info["probe"]["off"]) == 2
    out = np.load(dst)
    assert out["p_va"].shape == (2, 2, 60) and out["p_te"].shape == (2, 2, 60)
    assert ((out["p_te"] >= 0) & (out["p_te"] <= 1)).all()
