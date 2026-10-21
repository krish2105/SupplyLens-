"""Temporal leakage guards for the trained-model features (ML-003)."""
import numpy as np
import pandas as pd

from supplylens_ml import models as M
from supplylens_ml.evaluate import paired_bootstrap, score
from supplylens_ml.panel import Panel, build_panel, mase_scale, rearrange, select_cohort


def toy_panel(seed=0, T=200, S=5):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2011-01-01", periods=T, freq="D")
    y = rng.poisson(5, size=(T, S)).astype(float)
    y[:30, 0] = np.nan  # series 0 launches late
    return Panel(dates, [f"S{j}" for j in range(S)], y)


def test_lgbm_features_ignore_future_rows():
    p = toy_panel()
    i = 150
    a, sa = M.lgbm_features(p, i)
    p2 = Panel(p.dates, p.skus, p.y.copy())
    p2.y[i + 1:] = 9999
    b, sb = M.lgbm_features(p2, i)
    pd.testing.assert_frame_equal(a, b)
    assert np.allclose(sa, sb)


def test_training_labels_never_cross_cutoff_and_prelaunch_rows_dropped():
    p = toy_panel()
    cutoff = 150
    origins = list(range(56, cutoff - 28 + 1, 7))
    assert max(origins) + 28 <= cutoff
    X, y = M.lgbm_training_set(p, origins)
    assert not np.isnan(y).any()
    # series 0 is not observable before day 30, so origins whose window starts earlier drop it
    assert len(y) < len(origins) * 28 * 5


def test_seasonal_naive_panel_ignores_future():
    p = toy_panel()
    a = M.seasonal_naive_panel(p, 150)
    p.y[151:] = 0
    assert np.allclose(a, M.seasonal_naive_panel(p, 150))


def test_cohort_uses_only_past_sales():
    daily = pd.DataFrame({"sku_id": ["A"] * 100 + ["B"] * 100,
                          "day": list(pd.date_range("2011-01-01", periods=100)) * 2,
                          "units": [1] * 100 + [0] * 60 + [5] * 40})
    p = build_panel(daily, "2011-01-01", "2011-04-10")
    assert select_cohort(p, "2011-03-01", lookback_days=59, min_selling_days=50) == ["A"]


def test_score_reports_undefined_mase_and_crossing():
    y = np.array([[1.0, 2.0], [0.0, 0.0]])
    raw = np.stack([np.stack([y - 1, y, y + 1], -1)[0], np.array([[1, 0, 2], [0, 0, 0]], float)])
    s = score(raw, y, np.array([1.0, np.nan]))
    assert s["mase_undefined_series"] == 1 and s["crossing_rate_raw"] == 0.25
    assert (rearrange(raw)[..., 0] <= rearrange(raw)[..., 1]).all()
    assert mase_scale(Panel(pd.date_range("2011-01-01", periods=20), ["Z"], np.zeros((20, 1))), 19)[0] != 0


def test_paired_bootstrap_sign():
    r = paired_bootstrap(np.array([1.0, 1, 1, 1]), np.array([2.0, 2, 2, 2]))
    assert r["mean_diff"] == -1 and r["share_a_better"] == 1.0
