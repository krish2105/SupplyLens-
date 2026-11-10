"""ET1: delivery-time (ETA) prediction on a SIMULATED last-mile history. Read this as a method check.

The course (Week 7) asks for "ETA prediction with machine learning". The real candidates (LaDe-D, Amazon Last Mile) need
the owner's approval, which has not been given, so a delivery history is generated from a stated process (the brief's
fallback). Nothing below is a measured delivery.

Generator (all parameters ASSUMED, listed in config.json):
- 8 regions in four density classes (dense / urban / suburban / rural), each with its own driving speed, doorstep service
  minutes, spacing between consecutive stops and area radius; synthetic coordinates around an arbitrary reference point;
- 40 couriers working from 2026-01-05 (simulated calendar), each in one home region, with a personal driving-speed and
  service-time factor, one fixed day off a week; 4 more couriers join on 2026-05-01 (the test period) with no history
  and slower factors, so the test also measures the cold start;
- parcels per courier-day: Poisson around 26, more on Mondays and Fridays, fewer at weekends, +4 % a month;
- each parcel: an acceptance hour (08-19), stops still ahead of it in the courier's queue (binomial in the day's load),
  and the haversine (straight-line) distance from the courier's position to the customer;
- delivery minutes = travel (road km = 1.3 x haversine km, at the region speed x hour-of-day traffic x weekday x courier
  factor x an unobserved region-day disturbance) + doorstep service + queueing (stops ahead x per-stop minutes) and noise
  (x lognormal 10 %, +/- 3 min, and 4 % of parcels wait 20-60 min more, e.g. nobody home).
Models see only courier, region, hour, weekday, haversine km and stops ahead. Chronological split: train 2026-01-05 to
2026-04-30 (the last 14 days of it pick the boosting rounds, then the model is refit on all of train), test 2026-05-01 to
2026-06-28. Models: historical mean by region x hour (baseline, with its historical 10th/90th percentiles as an interval),
LightGBM (point), quantile LightGBM at 0.1 and 0.9 (80 % interval). Metrics on test: MAE, RMSE, ACC@30 (share within
30 minutes), interval coverage and mean width; three seeds. The generator's own expected time (which uses hidden
quantities) is reported as a reference for the error no model can remove.

uv run python evaluations/eta_study.py
"""
from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta

import lightgbm as lgb
import numpy as np
import pandas as pd

from supplylens.config import REPO_ROOT

SEEDS = (7, 8, 9)
START, SPLIT, END = date(2026, 1, 5), date(2026, 5, 1), date(2026, 6, 28)   # simulated calendar
VALID_DAYS = 14
EARTH_RADIUS_KM = 6371.0088
REF_LATLON = (0.0, 0.0)          # arbitrary reference point for the synthetic coordinates; not a real service area
KM_PER_DEG = np.pi * EARTH_RADIUS_KM / 180
DETOUR = 1.3                     # ASSUMED road km per straight-line km; hidden from the models

DENSITY = {  # ASSUMED per density class: speed km/h, doorstep minutes, km between consecutive stops, area radius km,
    #          centre distance from the reference point (km), weight for courier placement
    "dense": {"speed": 14.0, "service": 6.0, "hop": 0.3, "radius": 1.5, "ring": 2.0, "couriers": 3.0},
    "urban": {"speed": 20.0, "service": 4.5, "hop": 0.6, "radius": 3.0, "ring": 7.0, "couriers": 2.0},
    "suburban": {"speed": 28.0, "service": 3.0, "hop": 1.0, "radius": 5.0, "ring": 14.0, "couriers": 1.5},
    "rural": {"speed": 40.0, "service": 2.5, "hop": 2.5, "radius": 10.0, "ring": 28.0, "couriers": 1.0},
}
REGIONS = ["dense", "dense", "urban", "urban", "urban", "suburban", "suburban", "rural"]
COURIERS, NEW_COURIERS = 40, 4
NEW_SPEED, NEW_SERVICE = 0.85, 1.2          # ASSUMED: new couriers drive slower and take longer at the door
PARCELS_PER_DAY = 26
QUEUE_SHARE = 0.4                           # stops ahead ~ Binomial(parcels that day - 1, 0.4)
HOURS = np.arange(8, 20)
HOUR_WEIGHT = np.array([6, 9, 10, 10, 9, 9, 9, 8, 7, 6, 5, 3], dtype=float)
HOUR_SPEED = np.array([0.75, 0.80, 0.95, 1.0, 0.95, 1.0, 1.0, 0.9, 0.75, 0.7, 0.8, 0.95])   # traffic, ASSUMED
WEEKDAY_SPEED = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.1, 1.2])                               # Mon..Sun
WEEKDAY_VOLUME = np.array([1.2, 1.0, 1.0, 1.05, 1.1, 0.85, 0.6])
MONTHLY_GROWTH = 0.04
DAY_SHOCK_SIGMA = 0.08                      # unobserved region-day disturbance on speed (weather, roadworks)
NOISE_SIGMA, NOISE_SD = 0.10, 3.0
TAIL_P, TAIL_LO, TAIL_HI = 0.04, 20.0, 60.0
MIN_MINUTES = 2.0
ACC_MINUTES = 30
FEATURES = ["courier", "region", "hour", "weekday", "dist_km", "stops_ahead"]
CATEGORICAL = ["courier", "region"]
LGB_PARAMS = {"learning_rate": 0.05, "num_leaves": 31, "min_data_in_leaf": 50, "feature_fraction": 1.0,
              "deterministic": True, "force_row_wise": True, "num_threads": 1, "verbose": -1}
MAX_ROUNDS, EARLY_STOP = 2000, 50


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle (straight-line) distance in km; inputs in degrees, scalars or arrays."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def to_latlon(xy_km):
    """Planar km offsets (east, north) from REF_LATLON to degrees."""
    lat = REF_LATLON[0] + xy_km[..., 1] / KM_PER_DEG
    lon = REF_LATLON[1] + xy_km[..., 0] / (KM_PER_DEG * np.cos(np.radians(REF_LATLON[0])))
    return lat, lon


def generate(rng, couriers: int = COURIERS, new_couriers: int = NEW_COURIERS, start: date = START, end: date = END,
             join: date = SPLIT, per_day: float = PARCELS_PER_DAY) -> pd.DataFrame:
    """One SIMULATED parcel history from the process in the module docstring (one row per delivered parcel)."""
    n_c = couriers + new_couriers
    weight = np.array([DENSITY[d]["couriers"] for d in REGIONS])
    home = rng.choice(len(REGIONS), size=n_c, p=weight / weight.sum())
    speed_f = np.exp(rng.normal(0, 0.15, n_c))
    service_f = np.exp(rng.normal(0, 0.20, n_c))
    new = np.arange(n_c) >= couriers
    speed_f[new] *= NEW_SPEED
    service_f[new] *= NEW_SERVICE
    day_off = rng.integers(0, 7, n_c)
    angle = rng.uniform(0, 2 * np.pi, len(REGIONS))
    ring = np.array([DENSITY[d]["ring"] for d in REGIONS])
    centre = np.c_[ring * np.cos(angle), ring * np.sin(angle)]
    n_days = (end - start).days + 1
    shock = np.exp(rng.normal(0, DAY_SHOCK_SIGMA, (n_days, len(REGIONS))))
    hour_p = HOUR_WEIGHT / HOUR_WEIGHT.sum()
    cols: dict[str, list] = {k: [] for k in ("day", "courier", "region", "hour", "weekday", "dist_km", "stops_ahead",
                                              "minutes", "expected_minutes", "new_courier")}
    for di in range(n_days):
        day = start + timedelta(days=di)
        wd = day.weekday()
        months = (day.year - start.year) * 12 + day.month - start.month
        for c in range(n_c):
            if wd == day_off[c] or (new[c] and day < join):
                continue
            n = int(rng.poisson(per_day * WEEKDAY_VOLUME[wd] * (1 + MONTHLY_GROWTH) ** months))
            if n == 0:
                continue
            r = int(home[c])
            cls = DENSITY[REGIONS[r]]
            h = rng.choice(len(HOURS), size=n, p=hour_p)
            stops = rng.binomial(n - 1, QUEUE_SHARE, n)
            here = to_latlon(centre[r] + rng.normal(0, cls["radius"] / 2, (n, 2)))
            there = to_latlon(centre[r] + rng.normal(0, cls["radius"] / 2, (n, 2)))
            dist = haversine_km(here[0], here[1], there[0], there[1])
            speed = cls["speed"] * HOUR_SPEED[h] * WEEKDAY_SPEED[wd] * speed_f[c] * shock[di, r]
            travel = DETOUR * dist / speed * 60
            service = cls["service"] * service_f[c]
            per_stop = DETOUR * cls["hop"] / speed * 60 + service
            base = travel + service + stops * per_stop
            tail = (rng.random(n) < TAIL_P) * rng.uniform(TAIL_LO, TAIL_HI, n)
            minutes = base * np.exp(rng.normal(0, NOISE_SIGMA, n)) + rng.normal(0, NOISE_SD, n) + tail
            cols["day"] += [day] * n
            cols["courier"] += [c] * n
            cols["region"] += [r] * n
            cols["hour"] += list(HOURS[h])
            cols["weekday"] += [wd] * n
            cols["dist_km"] += list(dist)
            cols["stops_ahead"] += list(stops)
            cols["minutes"] += list(np.maximum(minutes, MIN_MINUTES))
            cols["expected_minutes"] += list(base * np.exp(NOISE_SIGMA ** 2 / 2) + TAIL_P * (TAIL_LO + TAIL_HI) / 2)
            cols["new_courier"] += [bool(new[c])] * n
    df = pd.DataFrame(cols)
    df["day"] = pd.to_datetime(df["day"])
    return df


def split(df: pd.DataFrame, at: date = SPLIT):
    cut = pd.Timestamp(at)
    return df[df["day"] < cut].reset_index(drop=True), df[df["day"] >= cut].reset_index(drop=True)


def point_metrics(y, p) -> dict:
    y, p = np.asarray(y, float), np.asarray(p, float)
    err = p - y
    return {"mae_min": round(float(np.mean(np.abs(err))), 2), "rmse_min": round(float(np.sqrt(np.mean(err ** 2))), 2),
            f"acc_at_{ACC_MINUTES}": round(float(np.mean(np.abs(err) <= ACC_MINUTES)), 4),
            "mean_error_min": round(float(np.mean(err)), 2)}


def interval_metrics(y, lo, hi) -> dict:
    """Coverage and width of [lo, hi]; crossed quantiles (lo > hi) are counted, then the pair is put in order."""
    y, lo, hi = (np.asarray(v, float) for v in (y, lo, hi))
    a, b = np.minimum(lo, hi), np.maximum(lo, hi)
    return {"coverage": round(float(np.mean((y >= a) & (y <= b))), 4), "mean_width_min": round(float(np.mean(b - a)), 2),
            "below_lower": round(float(np.mean(y < a)), 4), "above_upper": round(float(np.mean(y > b)), 4),
            "crossed_share": round(float(np.mean(lo > hi)), 4)}


def region_hour_baseline(train: pd.DataFrame, test: pd.DataFrame) -> pd.DataFrame:
    """Historical mean and 10th/90th percentiles of training minutes by region x hour (fallback: region, then all)."""
    stats = {}
    for keys in (["region", "hour"], ["region"]):
        g = train.groupby(keys)["minutes"]
        stats[tuple(keys)] = pd.DataFrame({"mean": g.mean(), "q10": g.quantile(0.1), "q90": g.quantile(0.9)})
    out = test[["region", "hour"]].merge(stats[("region", "hour")], left_on=["region", "hour"], right_index=True, how="left")
    fb = test[["region"]].merge(stats[("region",)], left_on="region", right_index=True, how="left")
    glob = {"mean": train["minutes"].mean(), "q10": train["minutes"].quantile(0.1), "q90": train["minutes"].quantile(0.9)}
    for c in ("mean", "q10", "q90"):
        out[c] = out[c].fillna(fb[c]).fillna(glob[c])
    return out[["mean", "q10", "q90"]].reset_index(drop=True)


def _dataset(df: pd.DataFrame) -> lgb.Dataset:
    return lgb.Dataset(df[FEATURES], df["minutes"], categorical_feature=CATEGORICAL, free_raw_data=False)


def fit_lightgbm(train: pd.DataFrame, seed: int, objective: str = "regression", alpha: float | None = None,
                 valid_days: int = VALID_DAYS):
    """Pick boosting rounds by early stopping on the last `valid_days` of train, then refit on all of train."""
    params = {**LGB_PARAMS, "objective": objective, "seed": seed}
    if alpha is not None:
        params["alpha"] = alpha
    cut = train["day"].max() - pd.Timedelta(days=valid_days - 1)
    fit, valid = train[train["day"] < cut], train[train["day"] >= cut]
    probe = lgb.train(params, _dataset(fit), num_boost_round=MAX_ROUNDS, valid_sets=[_dataset(valid)],
                      callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False)])
    rounds = max(1, int(probe.best_iteration))
    return lgb.train(params, _dataset(train), num_boost_round=rounds), rounds


def by_cohort(test: pd.DataFrame, fn, *cols) -> dict:
    out = {"all": fn(test["minutes"], *(c for c in cols))}
    for name, mask in (("existing_couriers", ~test["new_courier"]), ("new_couriers", test["new_courier"])):
        if mask.any():
            out[name] = fn(test["minutes"][mask], *(np.asarray(c)[mask.to_numpy()] for c in cols))
    return out


def run_seed(seed: int, **gen) -> dict:
    """Generate one history, fit every model on its train period and score the test period."""
    rng = np.random.default_rng(seed)
    split_at = gen.pop("split_at", SPLIT)
    df = generate(rng, join=split_at, **gen)
    train, test = split(df, split_at)
    base = region_hour_baseline(train, test)
    point, r_point = fit_lightgbm(train, seed)
    q10, r10 = fit_lightgbm(train, seed, "quantile", 0.1)
    q90, r90 = fit_lightgbm(train, seed, "quantile", 0.9)
    p, lo, hi = point.predict(test[FEATURES]), q10.predict(test[FEATURES]), q90.predict(test[FEATURES])
    gain = point.feature_importance("gain")
    return {
        "seed": seed,
        "rows": {"train": len(train), "test": len(test), "test_new_courier_rows": int(test["new_courier"].sum())},
        "test_mean_minutes": round(float(test["minutes"].mean()), 2),
        "models": {
            "baseline_region_hour_mean": by_cohort(test, point_metrics, base["mean"]),
            "lightgbm": by_cohort(test, point_metrics, p),
            "reference_generator_expected_time": by_cohort(test, point_metrics, test["expected_minutes"]),
        },
        "intervals_80pct": {
            "baseline_region_hour_percentiles": by_cohort(test, interval_metrics, base["q10"], base["q90"]),
            "quantile_lightgbm": by_cohort(test, interval_metrics, lo, hi),
        },
        "boosting_rounds": {"lightgbm": r_point, "quantile_0.1": r10, "quantile_0.9": r90},
        "lightgbm_gain_share": {f: round(float(g / gain.sum()), 4) for f, g in zip(FEATURES, gain, strict=True)},
    }


def summarise(per_seed: list[dict]) -> dict:
    """Mean and range over seeds of the headline (all-test-rows) metrics."""
    def agg(vals):
        return {"mean": round(float(np.mean(vals)), 4), "min": round(float(np.min(vals)), 4), "max": round(float(np.max(vals)), 4)}
    out: dict = {}
    for group in ("models", "intervals_80pct"):
        for name in per_seed[0][group]:
            for cohort in per_seed[0][group][name]:
                for metric in per_seed[0][group][name][cohort]:
                    vals = [r[group][name][cohort][metric] for r in per_seed]
                    out.setdefault(name, {}).setdefault(cohort, {})[metric] = agg(vals)
    return out


def main() -> None:
    t0 = time.time()
    per_seed = []
    for s in SEEDS:
        r = run_seed(s)
        per_seed.append(r)
        print(s, r["rows"], {k: v["all"] for k, v in r["models"].items()},
              {k: v["all"]["coverage"] for k, v in r["intervals_80pct"].items()}, flush=True)
    summary = summarise(per_seed)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = REPO_ROOT / "artifacts" / "experiments" / f"ET1-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    config = {
        "seeds": list(SEEDS), "calendar": {"start": START.isoformat(), "split": SPLIT.isoformat(), "end": END.isoformat(),
                                           "validation_days_inside_train": VALID_DAYS},
        "regions": REGIONS, "density_classes": DENSITY, "couriers": COURIERS, "new_couriers": NEW_COURIERS,
        "new_courier_factors": {"speed": NEW_SPEED, "service": NEW_SERVICE}, "parcels_per_day": PARCELS_PER_DAY,
        "queue_share": QUEUE_SHARE, "hours": HOURS.tolist(), "hour_weight": HOUR_WEIGHT.tolist(),
        "hour_speed": HOUR_SPEED.tolist(), "weekday_speed": WEEKDAY_SPEED.tolist(), "weekday_volume": WEEKDAY_VOLUME.tolist(),
        "monthly_growth": MONTHLY_GROWTH, "detour_factor": DETOUR, "day_shock_sigma": DAY_SHOCK_SIGMA,
        "noise": {"lognormal_sigma": NOISE_SIGMA, "additive_sd_min": NOISE_SD, "tail_p": TAIL_P, "tail_min": [TAIL_LO, TAIL_HI]},
        "reference_latlon": REF_LATLON, "features": FEATURES, "categorical": CATEGORICAL,
        "lightgbm": {**LGB_PARAMS, "max_rounds": MAX_ROUNDS, "early_stopping_rounds": EARLY_STOP},
    }
    metrics = {
        "experiment_id": out.name, "study": "ET1", "kind": "simulated delivery history (synthetic generator; no real deliveries)",
        "question": "How much closer to the actual delivery time does a LightGBM ETA get than a region x hour historical mean, "
                    "and are its quantile intervals honest? (method check on a SIMULATED last-mile history)",
        "data": {"label": "SIMULATED", "generator": "evaluations/eta_study.py generate(); parameters in config.json",
                 "rows_per_seed": [r["rows"] for r in per_seed],
                 "split": {"train": f"{START.isoformat()}..{(SPLIT - timedelta(days=1)).isoformat()}",
                           "test": f"{SPLIT.isoformat()}..{END.isoformat()}", "kind": "chronological",
                           "boosting_rounds_chosen_on": f"last {VALID_DAYS} days of train, then refit on all of train"},
                 "features": FEATURES, "target": "minutes from acceptance to delivery",
                 "distance": "haversine (straight-line) km between synthetic coordinates",
                 "cold_start": f"{NEW_COURIERS} couriers start on {SPLIT.isoformat()} with no training rows"},
        "results": {"summary_over_seeds": summary, "per_seed": per_seed,
                    "metric_notes": {f"acc_at_{ACC_MINUTES}": f"share of test parcels predicted within {ACC_MINUTES} minutes",
                                     "coverage": "share of test parcels inside the 80 % interval (target 0.80)",
                                     "reference_generator_expected_time": "not a model: the generator's expected minutes "
                                     "given hidden quantities (true courier factors, region-day disturbance); shows the "
                                     "noise no model can remove"}},
        "assumptions": [
            "every generator parameter (speeds, service minutes, traffic by hour, weekday effects, growth, noise, detour "
            "factor 1.3, new-courier factors) is assumed, not estimated from data",
            "the queue is summarised by one number (stops ahead) and the traffic of the acceptance hour applies to the whole wait",
            "couriers work one home region; coordinates are synthetic around an arbitrary reference point",
        ],
        "limits": [
            "synthetic data: the models can only recover effects that were put into the generator, so the accuracy says the "
            "pipeline works, not how well it would predict real deliveries",
            "distances are haversine (straight-line); real road distances and routing are not modelled",
            "no real courier sequences, addresses or traffic feeds",
            "the real datasets (LaDe, Amazon Last Mile) need the owner's approval before they can replace the generator; "
            "the LaDe paper's leaderboard is not comparable with these numbers and is not reported",
        ],
        "seeds": {"generator_and_lightgbm": list(SEEDS)},
        "seconds": round(time.time() - t0, 1),
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str))
    (out / "config.json").write_text(json.dumps(config, indent=1, default=str))
    print(json.dumps({"experiment_id": out.name, "seconds": metrics["seconds"],
                      "summary": {k: v["all"] for k, v in summary.items()}}, indent=1))


if __name__ == "__main__":
    main()
