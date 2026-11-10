"""W2: a small LSTM forecaster on the W1 protocol, against seasonal naive and W1's Prophet and XGBoost (WP4, Week 3).

Question: on UCI Online Retail II total daily units, does an LSTM beat seasonal naive, Prophet and XGBoost on WAPE,
MAPE (non-zero actuals) and RMSE under W1's rolling-origin protocol?

Data: the raw UCI zip (sha256 recorded), cleaned with the product's own rules (supplylens_ml.uci: accepted sales
lines, cross-sheet overlap removed, units per calendar day), summed over all products, zero on non-trading days.
Weather is NOT used: the Open-Meteo file W1 used is not available locally, so the LSTM is compared above all with
W1's no-weather Prophet and XGBoost.
Protocol (W1's): 13 Monday origins 2011-09-05 .. 2011-11-28, horizon 1-7 days, refit at every origin on data up to
the origin only. Seasonal naive is recomputed here on the same origins as a reproduction check against W1's numbers.
Model: one-layer LSTM over the last 56 days (units scaled by their 28-day mean, plus weekday one-hot), whose final state
is joined with the 7 target days' calendar (weekday, day of year, days to Christmas) and mapped to 7 outputs (direct
multi-horizon). Hyperparameters are fixed in CFG; only the loss (MSE or Huber on scaled units) is chosen, on 9 validation
origins before the test window, by mean WAPE over the seeds. PyTorch runs on CPU, one thread,
deterministic algorithms, in child processes (evaluations/lstm_child.py; never in this process: D-023).

uv run python evaluations/lstm_study.py [--bronze-root DIR] [--work DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
ZIP = REPO_ROOT / "data" / "raw" / "core" / "online_retail_ii" / "online_retail_ii.zip"
ZIP_SHA256 = "572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb"
W1_RUN = REPO_ROOT / "artifacts" / "experiments" / "W1-20261027T055557Z" / "metrics.json"
CHILD = Path(__file__).resolve().parent / "lstm_child.py"

ORIGINS = [date(2011, 9, 5) + timedelta(weeks=i) for i in range(13)]           # W1's test origins
VAL_ORIGINS = [date(2011, 7, 4) + timedelta(weeks=i) for i in range(9)]         # before the test window; reported only
H, WINDOW, SCALE_DAYS = 7, 56, 28
SEEDS = [0, 1, 2, 3, 4]
BOOT, BOOT_SEED = 2000, 7
CFG = {"hidden": 32, "head": 64, "layers": 1, "dropout": 0.0, "epochs": 150, "batch": 64, "lr": 2e-3,
       "weight_decay": 1e-4, "grad_clip": 1.0, "threads": 1, "device": "cpu"}
# The one choice made on data: the training loss, picked by mean validation WAPE before any test origin is scored.
LOSS_CANDIDATES = [{"loss": "mse"}, {"loss": "huber", "huber_delta": 1.0}]
N_STEP = 1 + 7          # per input day: scaled units, weekday one-hot
N_CAL = 10              # per target day: weekday one-hot, sin/cos day of year, days to Christmas / 365


# ----------------------------------------------------------------------------------------------------------- data
def dense(series: pd.Series, start, end) -> pd.Series:
    return series.reindex(pd.date_range(start, end, freq="D"), fill_value=0.0)


def bronze_dir(cache_root: Path) -> Path:
    """Reuse the product's bronze cache if it exists, otherwise build one outside the repository."""
    product = REPO_ROOT / "data" / "bronze" / "online_retail_ii"
    return product if (product / ZIP_SHA256[:16]).exists() else cache_root


def load_total(zip_path: Path, cache_root: Path) -> tuple[pd.Series, str, dict]:
    """Total accepted units per calendar day, exactly as the ingest writes sales_daily (supplylens_ml.uci)."""
    from supplylens_ml import uci
    digest = uci.sha256_file(zip_path)
    bronze = uci.read_bronze(zip_path, bronze_dir(cache_root))
    classified = uci.resolve_sheet_overlap({s: uci.classify(s, df) for s, df in bronze.items()})
    acc = pd.concat([c.accepted for c in classified.values()], ignore_index=True)
    daily = uci.daily_units(acc)
    daily["day"] = pd.to_datetime(daily["day"])
    total = daily.groupby("day")["units"].sum().astype(float)
    info = {"accepted_lines": int(len(acc)), "accepted_units": int(acc["qty"].sum()), "first_day": str(total.index.min().date()),
            "last_day": str(total.index.max().date())}
    return total, digest, info


# ------------------------------------------------------------------------------------------------------ baselines
def snaive(y: pd.Series, origin: pd.Timestamp) -> np.ndarray:
    """Same weekday last week (W1's definition; H = 7 so every horizon looks back exactly one week)."""
    return np.array([y[origin + timedelta(days=h - 7)] if h <= 7 else y[origin] for h in range(1, H + 1)])


# ------------------------------------------------------------------------------------------------------ windowing
def calendar(days: pd.DatetimeIndex) -> np.ndarray:
    """(n, 10): weekday one-hot, sin/cos of day of year, days to 25 December of the same year / 365."""
    days = pd.DatetimeIndex(days)
    dow = np.eye(7)[days.dayofweek.to_numpy()]
    ang = 2 * np.pi * days.dayofyear.to_numpy() / 365.25
    xmas = np.array([(pd.Timestamp(d.year, 12, 25) - d).days for d in days], dtype=float) / 365.0
    return np.column_stack([dow, np.sin(ang), np.cos(ang), xmas]).astype(np.float32)


def scale_at(values: np.ndarray, i: int) -> float:
    """Mean of the last SCALE_DAYS values up to and including index i; 1.0 if that is zero (all closed days)."""
    s = float(np.mean(values[max(0, i - SCALE_DAYS + 1): i + 1]))
    return s if s > 0 else 1.0


def window_at(values: np.ndarray, dates: pd.DatetimeIndex, i: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Inputs for a forecast made at the end of day i: history i-WINDOW+1..i and the calendar of days i+1..i+H.

    Only values[.. i] are read. The target-day calendar is known in advance, so it is not a leak."""
    if i - WINDOW + 1 < 0:
        raise ValueError("not enough history for a window")
    sc = scale_at(values, i)
    hist = values[i - WINDOW + 1: i + 1] / sc
    x = np.column_stack([hist, calendar(dates[i - WINDOW + 1: i + 1])[:, :7]]).astype(np.float32)
    future = pd.date_range(dates[i] + timedelta(days=1), periods=H, freq="D")
    return x, calendar(future), sc


def training_set(values: np.ndarray, dates: pd.DatetimeIndex, origin_i: int):
    """Every day i whose 7 labels i+1..i+H are known at the origin (i + H <= origin_i), stride 1."""
    X, C, Y, S = [], [], [], []
    for i in range(WINDOW - 1, origin_i - H + 1):
        x, c, sc = window_at(values, dates, i)
        X.append(x)
        C.append(c)
        Y.append(values[i + 1: i + 1 + H] / sc)
        S.append(sc)
    return (np.stack(X).astype(np.float32), np.stack(C).astype(np.float32), np.stack(Y).astype(np.float32),
            np.array(S))


def build_inputs(total: pd.Series, origins: list[date]) -> dict[str, np.ndarray]:
    """Arrays for the child process, one training set and one forecast window per origin."""
    values, dates = total.to_numpy(dtype=float), pd.DatetimeIndex(total.index)
    out: dict[str, np.ndarray] = {"n_origins": np.array(len(origins))}
    for k, o in enumerate(origins):
        oi = dates.get_loc(pd.Timestamp(o))
        X, C, Y, _ = training_set(values, dates, oi)
        xp, cp, sp = window_at(values, dates, oi)
        out.update({f"X{k}": X, f"C{k}": C, f"Y{k}": Y, f"Xp{k}": xp[None], f"Cp{k}": cp[None], f"Sp{k}": np.array([sp])})
    return out


# -------------------------------------------------------------------------------------------------------- metrics
def scores(y: np.ndarray, f: np.ndarray) -> dict:
    from supplylens_ml.metrics import mae, mape, rmse, wape
    w, m = wape(y, f), mape(y, f)
    return {"mae": round(mae(y, f), 3), "rmse": round(rmse(y, f), 3), "wape": None if w is None else round(w, 4),
            "mape_nonzero_days": None if m is None else round(m, 4)}


def seed_summary(runs: list[dict]) -> dict:
    """Mean and sample standard deviation (ddof=1) across seeds, plus every seed's value."""
    out = {}
    for k in ("wape", "mape_nonzero_days", "rmse", "mae"):
        v = np.array([r[k] for r in runs], dtype=float)
        nd = 4 if k in ("wape", "mape_nonzero_days") else 3
        out[k] = {"mean": round(float(v.mean()), nd), "sd": round(float(v.std(ddof=1)), nd) if len(v) > 1 else None,
                  "min": round(float(v.min()), nd), "max": round(float(v.max()), nd), "runs": [round(float(x), nd) for x in v]}
    return out


def reproduction_check(ours: dict, recorded: dict) -> dict:
    """Match means equal at the precision W1 recorded (WAPE/MAPE 4 dp, RMSE/MAE 3 dp)."""
    tol = {"wape": 5e-5, "mape_nonzero_days": 5e-5, "rmse": 5e-4, "mae": 5e-4}
    diff = {k: round(ours[k] - recorded[k], 6) for k in tol}
    return {"w1_recorded": {k: recorded[k] for k in tol}, "difference": diff,
            "match": all(abs(diff[k]) <= tol[k] for k in tol)}


def paired_bootstrap(err_a: np.ndarray, err_b: np.ndarray, groups: np.ndarray, boot: int = BOOT, seed: int = BOOT_SEED) -> dict:
    """Mean of (|e_a| - |e_b|) with a 95 % interval resampling whole origins (W1's method)."""
    rng = np.random.default_rng(seed)
    d = np.abs(err_a) - np.abs(err_b)
    ids = np.unique(groups)
    by = {g: d[groups == g] for g in ids}
    boots = [np.mean(np.concatenate([by[g] for g in rng.choice(ids, size=len(ids), replace=True)])) for _ in range(boot)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"mean_abs_error_change": round(float(d.mean()), 3), "ci95": [round(float(lo), 3), round(float(hi), 3)],
            "relative_to_b": round(float(d.mean() / np.mean(np.abs(err_b))), 4), "clear": bool(hi < 0 or lo > 0)}


def w1_reference(path: Path = W1_RUN) -> dict:
    m = json.loads(path.read_text())
    models = m["results"]["total"]["models"]
    labels = {"xgboost": "from W1, without weather", "prophet": "from W1, without weather",
              "seasonal_naive": "from W1 (no weather input)", "xgboost_weather": "from W1, with observed weather",
              "prophet_weather": "from W1, with observed weather"}
    return {"run": m["experiment_id"], "origins": m["protocol"]["origins"], "points": m["results"]["total"]["points"],
            "models": {k: {**models[k], "label": labels[k]} for k in labels}}


def select_loss(val_blocks: list[dict]) -> dict:
    """Candidate with the lowest mean validation WAPE across seeds; the first listed wins a tie."""
    best = min(range(len(val_blocks)), key=lambda n: (val_blocks[n]["lstm"]["wape"]["mean"], n))
    return val_blocks[best]["candidate"]


# ---------------------------------------------------------------------------------------------------------- child
def run_children(inputs_path: Path, work: Path, tag: str, seeds: list[int], cfg: dict, check_repeat: bool) -> dict[int, dict]:
    """One CPU child per seed, in parallel; each is single-threaded and deterministic."""
    env = {**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONHASHSEED": "0"}
    procs = {}
    for s in seeds:
        out = work / f"{tag}_seed{s}.npz"
        cmd = [sys.executable, str(CHILD), "--inputs", str(inputs_path), "--seed", str(s), "--cfg", json.dumps(cfg),
               "--out", str(out), "--info", str(work / f"{tag}_seed{s}.json")]
        if check_repeat and s == seeds[0]:
            cmd.append("--repeat-first")
        log = (work / f"{tag}_seed{s}.log").open("w")
        procs[s] = (subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env), log, out)
    res = {}
    for s, (p, log, out) in procs.items():
        rc = p.wait()
        log.close()
        if rc:
            raise RuntimeError(f"LSTM child seed {s} failed:\n" + (work / f"{tag}_seed{s}.log").read_text()[-2000:])
        res[s] = {"pred": np.load(out)["pred"], "info": json.loads((work / f"{tag}_seed{s}.json").read_text())}
    return res


def evaluate_lstm(total: pd.Series, origins: list[date], work: Path, tag: str, seeds: list[int], cfg: dict,
                  check_repeat: bool = False) -> dict:
    inputs = build_inputs(total, origins)
    path = work / f"{tag}_inputs.npz"
    np.savez(path, **inputs)
    res = run_children(path, work, tag, seeds, cfg, check_repeat)
    scales = np.array([inputs[f"Sp{k}"][0] for k in range(len(origins))])
    actual = np.concatenate([total[[pd.Timestamp(o) + timedelta(days=h) for h in range(1, H + 1)]].to_numpy() for o in origins])
    groups = np.repeat(np.arange(len(origins)), H)
    fc = {s: np.clip(r["pred"] * scales[:, None], 0, None).reshape(-1) for s, r in res.items()}
    sn = np.concatenate([snaive(total, pd.Timestamp(o)) for o in origins])
    return {"actual": actual, "groups": groups, "lstm": fc, "seasonal_naive": sn, "info": {s: r["info"] for s, r in res.items()},
            "train_samples": [int(inputs[f"Y{k}"].shape[0]) for k in range(len(origins))]}


# ----------------------------------------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bronze-root", default=str(Path(tempfile.gettempdir()) / "supplylens-bronze"),
                    help="cache for the parsed UCI sheets (outside the repo unless data/bronze already exists)")
    ap.add_argument("--work", default=None, help="scratch directory for child-process inputs and outputs")
    ns = ap.parse_args()
    t0 = time.time()
    ref = w1_reference()
    if ref["origins"] != [o.isoformat() for o in ORIGINS]:
        raise SystemExit("W1's recorded origins differ from W2's; the comparison would not be like for like")
    total_raw, digest, data_info = load_total(ZIP, Path(ns.bronze_root))
    if digest != ZIP_SHA256:
        raise SystemExit(f"raw file hash {digest} is not the F1/W1 file {ZIP_SHA256}")
    total = dense(total_raw, total_raw.index.min(), pd.Timestamp(ORIGINS[-1] + timedelta(days=H)))
    print(f"data loaded: {len(total)} days, {data_info} ({time.time() - t0:.0f}s)", flush=True)
    work = Path(ns.work or tempfile.mkdtemp(prefix="w2-lstm-"))
    work.mkdir(parents=True, exist_ok=True)

    def block(ev: dict) -> dict:
        y = ev["actual"]
        runs = [scores(y, ev["lstm"][s]) for s in SEEDS]
        ens = np.mean(np.stack([ev["lstm"][s] for s in SEEDS]), axis=0)
        lstm_abs = np.mean(np.stack([np.abs(y - ev["lstm"][s]) for s in SEEDS]), axis=0)   # |error| averaged over seeds
        return {"lstm": seed_summary(runs), "lstm_seed_average_forecast": scores(y, ens),
                "seasonal_naive": scores(y, ev["seasonal_naive"]), "points": len(y),
                "lstm_vs_seasonal_naive": paired_bootstrap(lstm_abs, y - ev["seasonal_naive"], ev["groups"])}

    # validation: choose the loss before the test window is touched
    val_blocks = []
    for n, cand in enumerate(LOSS_CANDIDATES):
        vb = block(evaluate_lstm(total, VAL_ORIGINS, work, f"val{n}", SEEDS, {**CFG, **cand}))
        val_blocks.append({"candidate": cand, **vb})
        print(f"validation {cand}: lstm wape {vb['lstm']['wape']} | seasonal naive {vb['seasonal_naive']} "
              f"({time.time() - t0:.0f}s)", flush=True)
    chosen = select_loss(val_blocks)
    cfg = {**CFG, **chosen}
    print(f"chosen on validation: {chosen}", flush=True)
    test = evaluate_lstm(total, ORIGINS, work, "test", SEEDS, cfg, check_repeat=True)
    print(f"test done ({time.time() - t0:.0f}s)", flush=True)
    tb = block(test)
    sn_check = reproduction_check(tb["seasonal_naive"], ref["models"]["seasonal_naive"])
    if tb["points"] != ref["points"]:
        sn_check["match"] = False
    w1 = ref["models"]
    mean_wape = tb["lstm"]["wape"]["mean"]
    seed_wapes = tb["lstm"]["wape"]["runs"]
    standing = {name: {"metric": "wape", "lstm_seed_mean": mean_wape, "other": w1[name]["wape"],
                       "lstm_better_on_mean": mean_wape < w1[name]["wape"],
                       "seeds_better": sum(w < w1[name]["wape"] for w in seed_wapes), "seeds": len(seed_wapes)}
                for name in ("xgboost", "prophet", "seasonal_naive")}
    for name in ("xgboost", "prophet", "seasonal_naive"):
        standing[name]["rmse"] = {"lstm_seed_mean": tb["lstm"]["rmse"]["mean"], "other": w1[name]["rmse"],
                                  "lstm_better_on_mean": tb["lstm"]["rmse"]["mean"] < w1[name]["rmse"]}
    rep = test["info"][SEEDS[0]].get("repeat_first_max_abs_diff")
    trading = total[(total.index <= pd.Timestamp(ORIGINS[0])) & (total > 0)]
    hist_max, hist_median = float(trading.max()), float(trading.median())
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = REPO_ROOT / "artifacts" / "experiments" / f"W2-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    info0 = test["info"][SEEDS[0]]
    metrics = {
        "experiment_id": out.name, "study": "W2", "kind": "measured (backtest)",
        "question": ("Does a small LSTM beat seasonal naive, Prophet and XGBoost on WAPE, MAPE (non-zero actuals) and RMSE "
                     "for UCI total daily units, under W1's rolling-origin protocol?"),
        "data": {"sales": "UCI Online Retail II daily units: accepted sales lines (supplylens_ml.uci, uci-v1), summed over "
                          "all products per calendar day, zero on non-trading days; read from the raw zip, not the database",
                 "sha256": digest, "weather": "not used (file not available locally)", **data_info,
                 "series_used": [str(total.index[0].date()), str(total.index[-1].date())]},
        "protocol": {"origins": [o.isoformat() for o in ORIGINS], "horizon_days": H, "refit_each_origin": True,
                     "seeds": SEEDS, "device": f"cpu, {CFG['threads']} thread per seed, torch.use_deterministic_algorithms(True)",
                     "target": "total daily units (W1 target (a))", "window_days": WINDOW,
                     "inputs": ("last 56 days of units divided by their 28-day mean (covers XGBoost's lag7, lag14, mean7, "
                                "mean28 and same-weekday mean of 4 weeks) + weekday one-hot per input day; for each of the 7 "
                                "target days weekday one-hot, sin/cos day of year and days to Christmas (W1 XGBoost: dow, "
                                "doy, month, to_xmas). No weather, no holiday calendar (W1 Prophet had UK holidays)."),
                     "model": f"LSTM({N_STEP}->{CFG['hidden']}, {CFG['layers']} layer) final state + {H}x{N_CAL} target "
                              f"calendar -> MLP({CFG['head']}) -> {H} outputs (direct multi-horizon)",
                     "training_samples_per_origin": test["train_samples"], "config": cfg,
                     "hyperparameters": ("fixed in advance except the loss, which was chosen between "
                                         f"{[c['loss'] for c in LOSS_CANDIDATES]} by mean validation WAPE over the seeds "
                                         "before the test origins were scored; test origins scored once, not tuned on"),
                     "loss_chosen_on_validation": chosen,
                     "validation_origins": [o.isoformat() for o in VAL_ORIGINS],
                     "parameters": info0.get("params"), "torch": info0.get("torch"),
                     "determinism_check": {"what": "seed 0, first test origin fitted twice in the same process",
                                           "max_abs_diff_scaled": rep, "deterministic": rep == 0.0},
                     "seed_sd": "sample standard deviation across seeds (ddof=1)"},
        "results": {
            "lstm": tb["lstm"],
            "lstm_seed_average_forecast": tb["lstm_seed_average_forecast"],
            "seasonal_naive_reproduced": {**tb["seasonal_naive"], "check": sn_check, "points": tb["points"]},
            "from_w1": {"run": ref["run"], "points": ref["points"],
                        "xgboost": w1["xgboost"], "prophet": w1["prophet"], "seasonal_naive": w1["seasonal_naive"],
                        "xgboost_weather": w1["xgboost_weather"], "prophet_weather": w1["prophet_weather"]},
            "lstm_vs_seasonal_naive": {**tb["lstm_vs_seasonal_naive"], "basis": "absolute error averaged over seeds, "
                                       "paired by day; 95 % bootstrap over the 13 origins"},
            "lstm_standing": standing,
            "validation": {"note": "9 Monday origins 2011-07-04..2011-08-29 (targets end 2011-09-05, before the test "
                                   "targets); same model and seeds; used only to choose the loss",
                           "points": val_blocks[0]["points"], "seasonal_naive": val_blocks[0]["seasonal_naive"],
                           "candidates": [{"candidate": v["candidate"], "lstm": v["lstm"],
                                           "lstm_vs_seasonal_naive": v["lstm_vs_seasonal_naive"]} for v in val_blocks],
                           "chosen": chosen},
        },
        "limits": [
            "one retailer, one autumn test period: 13 origins x 7 days = 91 points",
            "no weather: W1's weather file is not available locally, so W2 is compared with W1's no-weather Prophet and "
            "XGBoost; W1's with-weather rows are shown for reference only",
            "Prophet and XGBoost numbers are read from W1's metrics.json, not re-run; per-day forecasts were not stored "
            "by W1, so no paired test against them is possible, only the point comparison",
            "the TCN of F1 is not comparable: it forecasts quantiles per product on a different cohort and window",
            "MAPE leaves out zero-sales days (Saturdays); WAPE is the comparable figure",
            "a single small architecture; only the loss was chosen on validation; a tuned or larger network might do "
            "differently",
            f"{min(test['train_samples'])}-{max(test['train_samples'])} training windows per origin (under two years of "
            "daily history, one previous autumn), which favours simpler models",
            f"a few bulk-order days (maximum {hist_max:,.0f} units against a median trading day of {hist_median:,.0f} "
            f"before {ORIGINS[0]}) sit in the training history; returns are not netted (W1 had the same series)",
        ],
        "seconds": round(time.time() - t0),
        "environment": {"python": sys.version.split()[0], "platform": platform.platform(), "torch": info0.get("torch")},
    }
    config = {"study": "W2", "origins": metrics["protocol"]["origins"], "validation_origins": metrics["protocol"]["validation_origins"],
              "horizon": H, "window": WINDOW, "scale_days": SCALE_DAYS, "seeds": SEEDS, "cfg_fixed": CFG,
              "loss_candidates": LOSS_CANDIDATES, "loss_chosen_on_validation": chosen, "cfg_used_on_test": cfg,
              "n_step_features": N_STEP, "n_calendar_features": N_CAL, "bootstrap": {"resamples": BOOT, "seed": BOOT_SEED},
              "data_zip": str(ZIP.relative_to(REPO_ROOT)), "data_sha256": digest, "w1_reference": str(W1_RUN.relative_to(REPO_ROOT)),
              "command": "uv run python evaluations/lstm_study.py"}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str))
    (out / "config.json").write_text(json.dumps(config, indent=1))
    print(json.dumps({"experiment_id": out.name, "lstm": tb["lstm"], "seasonal_naive": tb["seasonal_naive"],
                      "reproduction": sn_check, "standing": standing}, indent=1))


if __name__ == "__main__":
    main()
