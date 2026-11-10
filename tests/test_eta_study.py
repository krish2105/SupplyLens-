"""ET1 ETA study (week-7 study, SIMULATED history): the generator, the split, the metrics and a small end-to-end run."""
import importlib.util
from datetime import date

import numpy as np
import pandas as pd

from supplylens.config import REPO_ROOT

spec = importlib.util.spec_from_file_location("eta_study", REPO_ROOT / "evaluations" / "eta_study.py")
et = importlib.util.module_from_spec(spec)
spec.loader.exec_module(et)

SMALL = {"couriers": 10, "new_couriers": 2, "start": date(2026, 1, 5), "end": date(2026, 3, 15)}
SMALL_SPLIT = date(2026, 2, 23)


def test_generator_is_deterministic_and_follows_its_stated_process():
    a = et.generate(np.random.default_rng(1), join=SMALL_SPLIT, **SMALL)
    b = et.generate(np.random.default_rng(1), join=SMALL_SPLIT, **SMALL)
    pd.testing.assert_frame_equal(a, b)
    assert len(a) > 5000 and (a["minutes"] >= et.MIN_MINUTES).all() and (a["dist_km"] >= 0).all()
    assert a.loc[a["new_courier"], "day"].min() >= pd.Timestamp(SMALL_SPLIT)          # cold-start couriers have no history
    assert a["day"].dt.weekday.nunique() == 7 and set(a["hour"]) <= set(et.HOURS.tolist())
    assert np.corrcoef(a["stops_ahead"], a["minutes"])[0, 1] > 0.6                     # queueing dominates, as stated
    assert abs(a["minutes"].mean() - a["expected_minutes"].mean()) < 2.0              # expected time is the generator's mean
    peak, midday = a[a["hour"] == 17], a[a["hour"] == 11]                              # traffic: same queue, slower at 17:00
    assert (peak["minutes"] / (1 + peak["stops_ahead"])).mean() > (midday["minutes"] / (1 + midday["stops_ahead"])).mean()


def test_haversine_is_the_great_circle_distance():
    assert abs(et.haversine_km(0.0, 0.0, 1.0, 0.0) - 111.195) < 0.01
    assert et.haversine_km(10.0, 20.0, 10.0, 20.0) == 0.0
    assert abs(et.haversine_km(0.0, 0.0, 0.3, 0.4) - et.haversine_km(0.3, 0.4, 0.0, 0.0)) < 1e-12


def test_split_is_chronological_and_features_hold_no_target_or_hidden_quantity():
    df = et.generate(np.random.default_rng(2), join=SMALL_SPLIT, **SMALL)
    train, test = et.split(df, SMALL_SPLIT)
    assert train["day"].max() < pd.Timestamp(SMALL_SPLIT) <= test["day"].min()
    assert len(train) + len(test) == len(df)
    assert not set(et.FEATURES) & {"minutes", "expected_minutes", "new_courier", "day"}


def test_point_and_interval_metrics_on_hand_values():
    m = et.point_metrics([10, 20, 30, 100], [10, 50, 30, 40])        # errors 0, +30, 0, -60
    assert m == {"mae_min": 22.5, "rmse_min": 33.54, "acc_at_30": 0.75, "mean_error_min": -7.5}
    iv = et.interval_metrics([10, 20, 30, 100], [5, 25, 40, 90], [15, 15, 50, 110])   # second pair crossed
    assert iv == {"coverage": 0.75, "mean_width_min": 12.5, "below_lower": 0.25, "above_upper": 0.0, "crossed_share": 0.25}


def test_baseline_uses_region_hour_means_and_falls_back_when_a_cell_is_empty():
    train = pd.DataFrame({"region": [0, 0, 0, 1], "hour": [8, 8, 9, 8], "minutes": [10.0, 20.0, 60.0, 100.0]})
    test = pd.DataFrame({"region": [0, 0, 1, 2], "hour": [8, 10, 8, 8]})
    b = et.region_hour_baseline(train, test)
    assert b["mean"].round(4).tolist() == [15.0, 30.0, 100.0, 47.5]   # cell; region 0; cell; all of train


def test_lightgbm_beats_the_region_hour_mean_and_its_interval_covers_on_a_small_history():
    r = et.run_seed(3, split_at=SMALL_SPLIT, **SMALL)
    base = r["models"]["baseline_region_hour_mean"]["existing_couriers"]
    gbm = r["models"]["lightgbm"]["existing_couriers"]
    ref = r["models"]["reference_generator_expected_time"]["existing_couriers"]
    assert gbm["mae_min"] < 0.7 * base["mae_min"] and gbm["acc_at_30"] > base["acc_at_30"]
    assert ref["mae_min"] < gbm["mae_min"]           # no model beats the generator's own expectation unless it leaks
    cov = r["intervals_80pct"]["quantile_lightgbm"]["existing_couriers"]["coverage"]
    assert 0.65 <= cov <= 0.92
    assert r["lightgbm_gain_share"]["stops_ahead"] == max(r["lightgbm_gain_share"].values())
