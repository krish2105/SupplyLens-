"""W2 LSTM study: windowing never reads past the origin, metrics and the W1 reproduction check behave, and the PyTorch
child is deterministic. PyTorch is never imported in this process (D-023); the one torch test uses a child process."""
import importlib.util
import json
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from supplylens.config import REPO_ROOT

spec = importlib.util.spec_from_file_location("lstm_study", REPO_ROOT / "evaluations" / "lstm_study.py")
w2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w2)


def _series(n=120, start="2011-01-03"):
    dates = pd.date_range(start, periods=n, freq="D")
    return np.arange(1, n + 1, dtype=float), dates


def test_study_module_keeps_torch_out_of_the_test_process():
    assert "torch" not in sys.modules


def test_training_windows_never_read_values_after_the_origin():
    values, dates = _series()
    origin_i = 100
    values[origin_i + 1:] = np.nan                       # anything read after the origin would poison the arrays
    X, C, Y, S = w2.training_set(values, dates, origin_i)
    assert np.isfinite(X).all() and np.isfinite(Y).all() and np.isfinite(S).all()
    assert len(X) == origin_i - w2.H - (w2.WINDOW - 1) + 1          # every day whose 7 labels are known, stride 1
    assert Y[-1, -1] * S[-1] == pytest.approx(values[origin_i])      # the last label is the origin day itself
    x, c, sc = w2.window_at(values, dates, origin_i)
    assert np.isfinite(x).all() and x[-1, 0] * sc == pytest.approx(values[origin_i])


def test_windows_line_up_with_the_series_and_the_calendar():
    values, dates = _series()
    X, C, Y, S = w2.training_set(values, dates, 100)
    k, i = 5, w2.WINDOW - 1 + 5
    assert np.allclose(X[k, :, 0] * S[k], values[i - w2.WINDOW + 1: i + 1])
    assert np.allclose(Y[k] * S[k], values[i + 1: i + 1 + w2.H])
    assert X[k, -1, 1:8].argmax() == dates[i].dayofweek               # weekday of the last input day
    assert C[k, 0, :7].argmax() == dates[i + 1].dayofweek             # weekday of the first target day
    assert [C[k, h, :7].argmax() for h in range(w2.H)] == [d.dayofweek for d in dates[i + 1: i + 1 + w2.H]]
    assert S[k] == pytest.approx(np.mean(values[i - w2.SCALE_DAYS + 1: i + 1]))


def test_scale_falls_back_to_one_on_an_all_closed_window():
    assert w2.scale_at(np.zeros(60), 59) == 1.0
    assert w2.scale_at(np.full(60, 4.0), 59) == 4.0


def test_calendar_features_on_known_days():
    cal = w2.calendar(pd.DatetimeIndex(["2011-12-24", "2011-12-25", "2011-09-05"]))
    assert cal.shape == (3, w2.N_CAL)
    assert [row[:7].argmax() for row in cal] == [5, 6, 0]            # Saturday, Sunday, Monday
    assert cal[1, 9] == 0 and cal[0, 9] == pytest.approx(1 / 365)


def test_seasonal_naive_is_the_same_weekday_one_week_earlier():
    values, dates = _series(40)
    y = pd.Series(values, index=dates)
    origin = dates[20]
    assert list(w2.snaive(y, origin)) == [values[20 + h - 7] for h in range(1, 8)]


def test_scores_on_known_values():
    s = w2.scores(np.array([0.0, 10.0, 20.0]), np.array([1.0, 8.0, 25.0]))
    assert s["wape"] == round(8 / 30, 4)
    assert s["mape_nonzero_days"] == round((0.2 + 0.25) / 2, 4)      # the zero-sales day is left out
    assert s["rmse"] == round(float(np.sqrt(10)), 3) and s["mae"] == round(8 / 3, 3)


def test_seed_summary_reports_mean_and_sample_sd():
    runs = [{"wape": w, "mape_nonzero_days": w, "rmse": 10 * w, "mae": w} for w in (0.1, 0.2, 0.3)]
    s = w2.seed_summary(runs)
    assert s["wape"]["mean"] == 0.2 and s["wape"]["sd"] == 0.1 and s["wape"]["runs"] == [0.1, 0.2, 0.3]
    assert s["rmse"]["mean"] == 2.0 and s["rmse"]["min"] == 1.0 and s["rmse"]["max"] == 3.0


def test_reproduction_check_matches_at_recorded_precision_and_flags_a_drift():
    rec = {"mae": 6428.418, "rmse": 8909.444, "wape": 0.2974, "mape_nonzero_days": 0.3306}
    assert w2.reproduction_check(dict(rec), rec)["match"]
    drift = w2.reproduction_check({**rec, "wape": 0.2984}, rec)
    assert not drift["match"] and drift["difference"]["wape"] == pytest.approx(0.001)


def test_loss_selection_takes_the_lowest_validation_wape_and_the_first_on_a_tie():
    blocks = [{"candidate": {"loss": "mse"}, "lstm": {"wape": {"mean": 0.30}}},
              {"candidate": {"loss": "huber"}, "lstm": {"wape": {"mean": 0.28}}}]
    assert w2.select_loss(blocks) == {"loss": "huber"}
    blocks[1]["lstm"]["wape"]["mean"] = 0.30
    assert w2.select_loss(blocks) == {"loss": "mse"}


def test_paired_bootstrap_separates_a_clear_gain_from_no_difference():
    groups = np.repeat(np.arange(10), 7)
    base = np.random.default_rng(0).normal(0, 100, 70)
    same = w2.paired_bootstrap(base, base, groups)
    assert same["mean_abs_error_change"] == 0 and not same["clear"]
    better = w2.paired_bootstrap(base * 0.5, base, groups)
    assert better["mean_abs_error_change"] < 0 and better["clear"] and better["ci95"][1] < 0


def test_origins_and_reference_models_are_read_from_w1():
    ref = w2.w1_reference()
    assert ref["origins"] == [o.isoformat() for o in w2.ORIGINS] and len(w2.ORIGINS) == 13
    assert ref["points"] == 13 * w2.H
    assert ref["models"]["xgboost"]["label"] == "from W1, without weather"
    assert ref["models"]["xgboost_weather"]["label"] == "from W1, with observed weather"
    assert set(ref["models"]) >= {"xgboost", "prophet", "seasonal_naive"}


def test_lstm_child_is_deterministic_across_processes(tmp_path):
    if importlib.util.find_spec("torch") is None:      # checked without importing it here (D-023)
        pytest.skip("PyTorch not installed")
    n = 120
    dates = pd.date_range("2011-01-03", periods=n, freq="D")
    y = pd.Series(100.0 + 50 * (dates.dayofweek < 5) + np.arange(n) * 0.1, index=dates)
    origins = [date(2011, 1, 3) + timedelta(days=100)]
    inputs = w2.build_inputs(y, origins)
    np.savez(tmp_path / "in.npz", **inputs)
    cfg = {**w2.CFG, "hidden": 8, "head": 8, "epochs": 5, "loss": "huber", "huber_delta": 1.0}
    a = w2.run_children(tmp_path / "in.npz", tmp_path, "a", [3], cfg, check_repeat=True)
    b = w2.run_children(tmp_path / "in.npz", tmp_path, "b", [3], cfg, check_repeat=False)
    assert a[3]["pred"].shape == (1, w2.H) and np.isfinite(a[3]["pred"]).all()
    assert a[3]["info"]["repeat_first_max_abs_diff"] == 0.0           # same seed, same process
    assert np.array_equal(a[3]["pred"], b[3]["pred"])                 # same seed, another process
    assert json.loads((tmp_path / "a_seed3.json").read_text())["threads"] == 1
    assert "torch" not in sys.modules
