"""FE1 fuel inefficiency (week-2 lab): the generator is reproducible, the label follows its definition, the metrics are
right on hand-checked examples, and on a small simulated fleet the telemetry models beat the class-only baselines."""
import importlib.util

import numpy as np
import pytest

from supplylens.config import REPO_ROOT

spec = importlib.util.spec_from_file_location("fuel_study", REPO_ROOT / "evaluations" / "fuel_study.py")
fs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fs)

SMALL = {"van": 4, "rigid": 4, "articulated": 3}


@pytest.fixture(scope="module")
def small():
    return fs.generate(np.random.default_rng(3), fleet=SMALL)


def test_generator_is_deterministic_for_a_seed(small):
    again = fs.generate(np.random.default_rng(3), fleet=SMALL)
    assert small.keys() == again.keys()
    for k in small:
        assert np.array_equal(small[k], again[k]), k
    other = fs.generate(np.random.default_rng(4), fleet=SMALL)
    assert not np.array_equal(small["litres"][:50], other["litres"][:50])


def test_trips_are_in_date_order_and_cover_twelve_months(small):
    assert np.all(np.diff(small["day"].astype("int64")) >= 0)
    assert set(np.unique(small["month"])) == set(range(1, 13))
    assert np.all(small["distance_km"] > 0) and np.all((small["payload_share"] >= 0) & (small["payload_share"] <= 1))


def test_reference_and_label_follow_their_definitions(small):
    for i in (0, 7, 123, len(small["l100"]) - 1):
        c = fs.CLASS_PARAMS[fs.CLASSES[small["vehicle_class"][i]]]
        ref = c["empty"] + (c["full"] - c["empty"]) * small["payload_share"][i]
        assert small["ref_l100"][i] == pytest.approx(ref)
        assert small["l100"][i] == pytest.approx(small["litres"][i] / small["distance_km"][i] * 100)
        assert small["inefficient"][i] == int(small["l100"][i] > 1.15 * ref)
        assert small["excess_litres"][i] == pytest.approx(max(0.0, small["litres"][i] - ref * small["distance_km"][i] / 100))
    assert np.array_equal(small["inefficient"], (small["l100"] > 1.15 * small["ref_l100"]).astype(int))
    assert 0.03 < small["inefficient"].mean() < 0.5            # the label is neither empty nor the majority


def test_auc_on_hand_checked_examples():
    assert fs.auc([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8]) == pytest.approx(0.75)
    assert fs.auc([0, 1, 0, 1], [0.2, 0.9, 0.3, 0.7]) == pytest.approx(1.0)
    assert fs.auc([0, 1], [0.5, 0.5]) == pytest.approx(0.5)       # ties count half


def test_flag_report_and_threshold_on_a_toy_example():
    y = np.array([1, 1, 0, 0, 1, 0])
    p = np.array([0.9, 0.8, 0.7, 0.2, 0.1, 0.05])
    # F1 by threshold: 0.9 -> 0.5, 0.8 -> 0.8, 0.7 -> 0.667, 0.2 -> 0.571, 0.1 -> 0.75, 0.05 -> 0.667
    assert fs.best_f1_threshold(y, p) == pytest.approx(0.8)
    excess = np.array([4.0, 2.0, 1.0, 0.0, 3.0, 0.0])
    r = fs.flag_report(y, p >= 0.8, excess, p)
    assert (r["precision"], r["recall"], r["flagged_trips"]) == (1.0, pytest.approx(0.6667, abs=1e-4), 2)
    assert r["excess_fuel_captured_share"] == pytest.approx(0.6)                 # (4 + 2) / 10 litres
    assert r["excess_co2_kg_on_flagged_assumed_factor"] == pytest.approx(6.0 * fs.CO2_KG_PER_LITRE)
    reg = fs.regression_report([10.0, 20.0], [11.0, 17.0])
    assert reg == {"mae_l_per_100km": 2.0, "rmse_l_per_100km": pytest.approx(np.sqrt(5.0), abs=1e-4)}


def test_telemetry_models_beat_class_only_baselines_on_a_small_fleet(small):
    res = fs.run(small, seed=fs.SEED, rounds=400)
    reg, cls = res["regression"], res["classification"]
    assert reg["lightgbm"]["mae_l_per_100km"] < reg["class_mean"]["mae_l_per_100km"]
    assert reg["ridge"]["mae_l_per_100km"] < reg["class_mean"]["mae_l_per_100km"]
    assert cls["lightgbm"]["auc"] > cls["class_share"]["auc"]
    assert cls["logistic_regression"]["auc"] > cls["class_share"]["auc"]
    assert res["split"]["train"]["months"] == [1, 8] and res["split"]["test"]["months"] == [11, 12]
    assert sum(s["trips"] for s in res["split"].values()) == len(small["l100"])
