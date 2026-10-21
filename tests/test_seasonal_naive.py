import numpy as np
import pandas as pd

from supplylens_ml.baselines import mase_scale, seasonal_naive
from supplylens_ml.metrics import coverage, crossing_rate, mase, pinball


def weekly(n_weeks=10, pattern=(5, 3, 0, 4, 6, 0, 2)):
    idx = pd.date_range("2011-01-03", periods=7 * n_weeks, freq="D")
    return pd.Series(np.tile(pattern, n_weeks).astype(float), index=idx)


def test_point_forecast_repeats_last_season():
    s = weekly()
    f = seasonal_naive(s, horizon=14)
    assert list(f["q50"][:7]) == [5, 3, 0, 4, 6, 0, 2]
    assert list(f["q50"][7:]) == [5, 3, 0, 4, 6, 0, 2]
    assert f["day"].iloc[0] == s.index[-1] + pd.Timedelta(days=1)


def test_forecast_ignores_data_after_origin():
    s = weekly()
    origin = s.index[-8]
    before = seasonal_naive(s[:origin], horizon=7)
    spiked = s.copy()
    spiked.iloc[-7:] = 1000
    after = seasonal_naive(spiked[:origin], horizon=7)
    pd.testing.assert_frame_equal(before, after)


def test_quantiles_ordered_and_nonnegative():
    rng = np.random.default_rng(0)
    s = pd.Series(rng.poisson(2, 200).astype(float), index=pd.date_range("2010-01-01", periods=200))
    f = seasonal_naive(s, horizon=28)
    assert crossing_rate(f["q10"].values, f["q50"].values, f["q90"].values) == 0.0
    assert (f[["q10", "q50", "q90"]] >= 0).all().all()
    assert (f["q90"] - f["q10"] > 0).any()


def test_mase_undefined_for_constant_training():
    flat = pd.Series([3.0] * 30, index=pd.date_range("2010-01-01", periods=30))
    assert mase_scale(flat) is None
    assert mase(np.array([1.0]), np.array([2.0]), None) is None


def test_pinball_and_coverage():
    y = np.array([0.0, 10.0])
    assert pinball(y, np.array([0.0, 0.0]), 0.9) == 4.5
    assert coverage(y, np.array([0, 0]), np.array([5, 5])) == 0.5
