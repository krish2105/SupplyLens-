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


def test_every_horizon_repeats_the_last_observed_week_not_older_weeks():
    """Audit F01: with changing weekly levels, weeks 2..4 must still repeat the LAST week (64..70), not 57..63 etc."""
    s = pd.Series(np.arange(1, 71, dtype=float), index=pd.date_range("2011-01-03", periods=70, freq="D"))
    f = seasonal_naive(s, horizon=28)
    expected = [64, 65, 66, 67, 68, 69, 70] * 4
    assert list(f["q50"]) == expected


def test_horizon_not_a_multiple_of_season_and_single_season_history():
    s = pd.Series([1.0, 2, 3, 4, 5, 6, 7], index=pd.date_range("2011-01-03", periods=7, freq="D"))
    f = seasonal_naive(s, horizon=10)
    assert list(f["q50"]) == [1, 2, 3, 4, 5, 6, 7, 1, 2, 3]


def test_panel_seasonal_naive_matches_the_series_baseline():
    from supplylens_ml.models import seasonal_naive_panel

    class P:
        pass
    y = np.stack([np.arange(1, 71, dtype=float), np.arange(70, 0, -1, dtype=float)], axis=1)
    panel = P()
    panel.y = y
    out = seasonal_naive_panel(panel, i=69, horizon=28)
    assert list(out[0, :, 1]) == [64, 65, 66, 67, 68, 69, 70] * 4
    assert list(out[1, :, 1]) == [7, 6, 5, 4, 3, 2, 1] * 4
    # an earlier origin uses only data up to it
    out_early = seasonal_naive_panel(panel, i=34, horizon=9)
    assert list(out_early[0, :, 1]) == [29, 30, 31, 32, 33, 34, 35, 29, 30]
