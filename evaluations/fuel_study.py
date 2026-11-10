"""FE1: flagging fuel-inefficient trips from trip telemetry. SIMULATED trips: read this as a method check.

Course outline, week 2 lab: "build ML models to predict delays, equipment breakdowns, or fuel inefficiency". Delays are
D1 and breakdowns PM1; this is the third. No telematics or fuel-card records exist in the repository, so a year of trips
is generated from the stated process below, and the question is whether a model on trip telemetry flags fuel-inefficient
trips (and predicts litres per 100 km) better than a fleet-average rule.

Generator (every number is ASSUMED: a plausible order of magnitude for diesel vans and trucks, not taken from a source):
- a fleet of vans, rigid trucks and articulated trucks (FLEET); each vehicle has an age (uniform 0-12 years at the start
  of the year); each driver drives one class (1.2 drivers per vehicle) and WEAK_SHARE of the drivers are systematically
  less efficient: a hidden +WEAK_HIDDEN on fuel that no telemetry field records, plus more idling and harsh acceleration;
- each vehicle runs one trip per working day (Monday-Saturday) with probability TRIP_PROB through a nominal 12-month
  year, with a driver of its class drawn at random. Per trip: distance (log-normal by class), payload share (beta),
  stops per 10 km (gamma by class), average speed (class cruise speed minus 9 km/h per stop per 10 km, plus noise),
  idle share (rises with stops and with the driver's habit), harsh accelerations per 100 km (Poisson around the
  driver's rate), ambient temperature (a temperate seasonal cycle, 4 C in January to 18 C in July, plus weather noise);
- reference L/100 km = empty rate + (full rate - empty rate) x payload share: the class/payload base term only;
- actual litres = reference L/100 km x km / 100 x (1 + effects + noise), where
    effects = driver hidden effect + 0.5 (idle share - 0.10) + 0.010 (harsh per 100 km - 4)
              + 0.0001 (speed - 65)^2 + 0.03 (stops per 10 km - class typical) + 0.006 max(0, 10 - temperature)
              + 0.004 max(0, temperature - 25) + 0.008 (age - 6),   noise ~ Normal(0, NOISE_SD);
- label "inefficient" = actual L/100 km > 1.15 x reference L/100 km.
Split by month: train 1-8, validation 9-10, test 11-12 (the test months are colder than most of the training year).

Models. Telemetry models (ridge / logistic regression, LightGBM) see class, age, distance, payload, stops, speed, idle,
harsh accelerations, temperature and driver id, but NOT the trip's fuel reading (think fuel known only per fill-up):
with the fuel reading and the payload the label could be computed almost directly, which would be circular.
Baselines: class mean L/100 km (regression); the fleet-average rule "measured L/100 km above 1.15 x the class median"
(classification; it does use the trip's measured fuel, but ignores payload), also with its line moved to maximise F1
on validation for threshold parity; and the class's past inefficient share (classification, class information only).
Classifier thresholds maximise F1 on the validation months. Regularisation
strengths are chosen on validation; LightGBM stops early on validation. Final models are fitted on the training months.
Reported on the test months: MAE and RMSE (L/100 km); AUC, precision, recall and F1 at the chosen threshold; the share of
excess fuel (litres above the reference) on flagged trips; CO2 of that fuel at an ASSUMED 2.5 kg CO2 per litre of diesel;
LightGBM gain-share importance. Because the process is known, recovering it shows the pipeline works; it says nothing
about a real fleet, whose telematics and fuel records would replace generate().

uv run python evaluations/fuel_study.py
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import lightgbm as lgb
import numpy as np
from scipy.optimize import minimize
from scipy.stats import rankdata

SEED = 17
CLASSES = ("van", "rigid", "articulated")
FLEET = {"van": 24, "rigid": 22, "articulated": 14}                    # vehicles per class (simulated fleet)
CLASS_PARAMS = {                                                        # ASSUMED, per class
    # empty / full: L/100 km at 0 % and 100 % payload on the class's typical duty; km: median trip and log-sd;
    # stops: mean stops per 10 km (the class typical); cruise: speed with no stops (km/h)
    "van": {"empty": 8.5, "full": 11.5, "km": 90.0, "km_sd": 0.40, "stops": 1.6, "cruise": 58.0},
    "rigid": {"empty": 20.0, "full": 28.0, "km": 160.0, "km_sd": 0.45, "stops": 0.6, "cruise": 64.0},
    "articulated": {"empty": 24.0, "full": 36.0, "km": 380.0, "km_sd": 0.35, "stops": 0.12, "cruise": 74.0},
}
EFFECTS = {"idle_per_share": 0.5, "idle_typical": 0.10, "harsh_per_event": 0.010, "harsh_typical": 4.0,
           "speed_quadratic": 0.0001, "speed_best_kmh": 65.0, "stops_per_stop": 0.03, "cold_per_c": 0.006,
           "cold_below_c": 10.0, "heat_per_c": 0.004, "heat_above_c": 25.0, "age_per_year": 0.008, "age_typical": 6.0}
DRIVERS_PER_VEHICLE = 1.2
WEAK_SHARE = 0.20                   # share of drivers who are systematically less efficient (ASSUMED)
WEAK_HIDDEN = 0.09                  # their hidden extra fuel share, not visible in any telemetry field (ASSUMED)
DRIVER_SD = 0.02                    # spread of the hidden effect among the other drivers
NOISE_SD = 0.05                     # trip-level noise on the fuel multiplier (wind, load placement, metering)
TRIP_PROB = 0.85
INEFFICIENT_RATIO = 1.15
CO2_KG_PER_LITRE = 2.5              # ASSUMED, rounded diesel factor; check the current official factor before external use
TRAIN_MONTHS, VAL_MONTHS, TEST_MONTHS = range(1, 9), range(9, 11), range(11, 13)
PENALTIES = (0.01, 0.1, 1.0, 10.0, 100.0, 1000.0)
LGB_PARAMS = {"learning_rate": 0.05, "num_leaves": 31, "min_data_in_leaf": 40, "verbose": -1, "deterministic": True,
              "num_threads": 1, "force_row_wise": True}
LGB_ROUNDS, LGB_EARLY_STOP = 2000, 100
FEATURES = ["vehicle_class", "vehicle_age_years", "distance_km", "payload_share", "stops_per_10km", "avg_speed_kmh",
            "idle_share", "harsh_accel_per_100km", "ambient_temp_c", "driver_id"]
CONTINUOUS = FEATURES[1:-1]


def generate(rng, fleet: dict[str, int] = FLEET, trip_prob: float = TRIP_PROB) -> dict[str, np.ndarray]:
    """One simulated year of trips, in date order, from the process in the module docstring."""
    vcls = np.repeat(np.arange(len(CLASSES)), [fleet.get(c, 0) for c in CLASSES])
    vage = rng.uniform(0, 12, len(vcls))
    dcls = np.repeat(np.arange(len(CLASSES)), [max(1, round(fleet.get(c, 0) * DRIVERS_PER_VEHICLE)) if fleet.get(c, 0) else 0
                                               for c in CLASSES])
    weak = rng.random(len(dcls)) < WEAK_SHARE
    hidden = rng.normal(0, DRIVER_SD, len(dcls)) + np.where(weak, WEAK_HIDDEN, 0.0)
    harsh_rate = rng.gamma(3.0, 1.2, len(dcls)) * np.where(weak, 1.8, 1.0)
    idle_habit = rng.uniform(0.0, 0.05, len(dcls)) + np.where(weak, 0.04, 0.0)

    dates = np.datetime64("2025-01-01") + np.arange(365)
    work = dates[(dates.astype("int64") + 3) % 7 < 6]                    # Monday = 0; Sunday off
    V, Dd = np.meshgrid(np.arange(len(vcls)), np.arange(len(work)), indexing="ij")
    run = rng.random(V.shape) < trip_prob
    v, day = V[run], work[Dd[run]]
    order = np.argsort(day, kind="stable")
    v, day = v[order], day[order]
    n = len(v)
    cls = vcls[v]
    driver = np.empty(n, dtype=int)
    for k in range(len(CLASSES)):
        m = cls == k
        if m.any():
            driver[m] = rng.choice(np.flatnonzero(dcls == k), m.sum())

    p = {key: np.array([CLASS_PARAMS[c][key] for c in CLASSES])[cls] for key in CLASS_PARAMS["van"]}
    doy = (day - np.datetime64("2025-01-01")).astype(int)
    month = day.astype("datetime64[M]").astype(int) % 12 + 1
    km = np.clip(np.exp(np.log(p["km"]) + p["km_sd"] * rng.standard_normal(n)), 5, 900)
    payload = rng.beta(2.2, 1.8, n)
    stops = rng.gamma(2.0, p["stops"] / 2.0)
    speed = np.clip(p["cruise"] - 9.0 * stops + rng.normal(0, 6.0, n), 12, 90)
    idle = np.clip(0.03 + 0.025 * stops + idle_habit[driver] + rng.normal(0, 0.025, n), 0.0, 0.6)
    harsh = rng.poisson(harsh_rate[driver] * km / 100) / (km / 100)
    temp = 11 + 7 * np.sin(2 * np.pi * (doy - 105) / 365) + rng.normal(0, 3.5, n)
    age = vage[v] + doy / 365

    e = EFFECTS
    effects = (hidden[driver] + e["idle_per_share"] * (idle - e["idle_typical"]) + e["harsh_per_event"] * (harsh - e["harsh_typical"])
               + e["speed_quadratic"] * (speed - e["speed_best_kmh"]) ** 2 + e["stops_per_stop"] * (stops - p["stops"])
               + e["cold_per_c"] * np.maximum(0, e["cold_below_c"] - temp) + e["heat_per_c"] * np.maximum(0, temp - e["heat_above_c"])
               + e["age_per_year"] * (age - e["age_typical"]))
    ratio = np.maximum(0.5, 1 + effects + rng.normal(0, NOISE_SD, n))
    ref_l100 = p["empty"] + (p["full"] - p["empty"]) * payload
    l100 = ref_l100 * ratio
    litres = l100 * km / 100
    return {"day": day, "month": month, "vehicle_id": v, "vehicle_class": cls, "vehicle_age_years": age, "distance_km": km,
            "payload_share": payload, "stops_per_10km": stops, "avg_speed_kmh": speed, "idle_share": idle,
            "harsh_accel_per_100km": harsh, "ambient_temp_c": temp, "driver_id": driver, "weak_driver": weak[driver],
            "ref_l100": ref_l100, "l100": l100, "litres": litres, "ref_litres": ref_l100 * km / 100,
            "excess_litres": np.maximum(0.0, litres - ref_l100 * km / 100),
            "inefficient": (l100 > INEFFICIENT_RATIO * ref_l100).astype(int),
            "_n_drivers": np.array(len(dcls)), "_weak_drivers": np.array(int(weak.sum()))}


def subset(d, mask):
    return {k: (v[mask] if not k.startswith("_") else v) for k, v in d.items()}


# --------------------------------------------------------------------------------------------------------- metrics
def auc(y, p) -> float:
    """Rank AUC with average ranks for ties (equals the probability a positive outranks a negative)."""
    y = np.asarray(y)
    r = rankdata(p)
    pos = y == 1
    n1, n0 = pos.sum(), (~pos).sum()
    return float((r[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def best_f1_threshold(y, p) -> float:
    """The score threshold (flag when score >= t) that maximises F1 on (y, p); ties go to the higher threshold."""
    y, p = np.asarray(y), np.asarray(p, dtype=float)
    ts = np.unique(p)[::-1]
    best_t, best_f1 = float(ts[0]), -1.0
    for t in ts:
        flag = p >= t
        tp = float(np.sum(flag & (y == 1)))
        f1 = 2 * tp / (flag.sum() + y.sum()) if (flag.sum() + y.sum()) else 0.0
        if f1 > best_f1 + 1e-12:
            best_t, best_f1 = float(t), f1
    return best_t


def flag_report(y, flag, excess, score=None) -> dict:
    y, flag, excess = np.asarray(y), np.asarray(flag, dtype=bool), np.asarray(excess, dtype=float)
    tp = int(np.sum(flag & (y == 1)))
    prec = tp / flag.sum() if flag.sum() else 0.0
    rec = tp / y.sum() if y.sum() else 0.0
    out = {"auc": round(auc(y, score), 4) if score is not None else None,
           "precision": round(float(prec), 4), "recall": round(float(rec), 4),
           "f1": round(float(2 * prec * rec / (prec + rec)) if prec + rec else 0.0, 4),
           "flagged_trips": int(flag.sum()), "flagged_share": round(float(flag.mean()), 4),
           "excess_litres_on_flagged": round(float(excess[flag].sum()), 1),
           "excess_fuel_captured_share": round(float(excess[flag].sum() / excess.sum()), 4) if excess.sum() else 0.0}
    out["excess_co2_kg_on_flagged_assumed_factor"] = round(out["excess_litres_on_flagged"] * CO2_KG_PER_LITRE, 1)
    return out


def regression_report(y, pred) -> dict:
    err = np.asarray(pred, dtype=float) - np.asarray(y, dtype=float)
    return {"mae_l_per_100km": round(float(np.mean(np.abs(err))), 4), "rmse_l_per_100km": round(float(np.sqrt(np.mean(err ** 2))), 4)}


# ---------------------------------------------------------------------------------------------------------- models
def linear_design(d, n_drivers: int, ref=None):
    """Class one-hots, class x payload, standardised continuous fields, driver one-hots. Raw fields, no hand-made
    nonlinear terms. `ref` carries the training means and sds."""
    cont = np.column_stack([d[f] for f in CONTINUOUS])
    if ref is None:
        ref = (cont.mean(0), cont.std(0) + 1e-9)
    z = (cont - ref[0]) / ref[1]
    cls = np.eye(len(CLASSES))[d["vehicle_class"]]
    drv = np.eye(n_drivers)[d["driver_id"]]
    X = np.column_stack([cls[:, 1:], cls * d["payload_share"][:, None], z, drv])
    return np.c_[np.ones(len(X)), X], ref


def ridge_fit(A, y, lam: float):
    P = lam * np.eye(A.shape[1])
    P[0, 0] = 0.0
    return np.linalg.solve(A.T @ A + P, A.T @ y)


def logistic_fit(A, y, lam: float):
    def nll(w):
        z = A @ w
        return float(np.sum(np.logaddexp(0, z) - y * z) + 0.5 * lam * np.sum(w[1:] ** 2))

    def grad(w):
        g = A.T @ (1 / (1 + np.exp(-(A @ w))) - y)
        g[1:] += lam * w[1:]
        return g
    return minimize(nll, np.zeros(A.shape[1]), jac=grad, method="L-BFGS-B", options={"maxiter": 2000}).x


def sigmoid(z):
    return 1 / (1 + np.exp(-z))


def lgb_matrix(d):
    return np.column_stack([d[f] for f in FEATURES]).astype(float)


def lgb_fit(objective: str, tr, ytr, va, yva, seed: int, rounds: int = LGB_ROUNDS):
    cat = [FEATURES.index("vehicle_class"), FEATURES.index("driver_id")]
    dtr = lgb.Dataset(lgb_matrix(tr), ytr, feature_name=FEATURES, categorical_feature=cat, free_raw_data=False)
    dva = lgb.Dataset(lgb_matrix(va), yva, reference=dtr, categorical_feature=cat)
    return lgb.train({**LGB_PARAMS, "objective": objective, "seed": seed}, dtr, num_boost_round=rounds, valid_sets=[dva],
                     callbacks=[lgb.early_stopping(LGB_EARLY_STOP, verbose=False)])


def gain_share(booster) -> dict:
    g = booster.feature_importance("gain")
    return {n: round(float(v / g.sum()), 4) for n, v in sorted(zip(FEATURES, g, strict=True), key=lambda z: -z[1])}


def run(d, seed: int = SEED, rounds: int = LGB_ROUNDS) -> dict:
    """Fit every model on the training months, tune on validation, report on the test months."""
    tr, va, te = (subset(d, np.isin(d["month"], list(ms))) for ms in (TRAIN_MONTHS, VAL_MONTHS, TEST_MONTHS))
    nd = int(d["_n_drivers"])
    yte, ex = te["inefficient"], te["excess_litres"]

    # baselines
    cmean = np.array([tr["l100"][tr["vehicle_class"] == k].mean() if (tr["vehicle_class"] == k).any() else tr["l100"].mean()
                      for k in range(len(CLASSES))])
    cmed = np.array([np.median(tr["l100"][tr["vehicle_class"] == k]) if (tr["vehicle_class"] == k).any() else np.median(tr["l100"])
                     for k in range(len(CLASSES))])
    cshare = np.array([tr["inefficient"][tr["vehicle_class"] == k].mean() if (tr["vehicle_class"] == k).any() else tr["inefficient"].mean()
                       for k in range(len(CLASSES))])
    rule_score = te["l100"] / cmed[te["vehicle_class"]]
    t_share = best_f1_threshold(va["inefficient"], cshare[va["vehicle_class"]])
    t_rule = best_f1_threshold(va["inefficient"], va["l100"] / cmed[va["vehicle_class"]])

    # ridge (regression) and logistic (classification), penalty chosen on validation
    Atr, ref = linear_design(tr, nd)
    Ava, _ = linear_design(va, nd, ref)
    Ate, _ = linear_design(te, nd, ref)
    lam_r = min(PENALTIES, key=lambda lam: np.mean(np.abs(Ava @ ridge_fit(Atr, tr["l100"], lam) - va["l100"])))
    w_r = ridge_fit(Atr, tr["l100"], lam_r)

    def val_logloss(lam):
        q = np.clip(sigmoid(Ava @ logistic_fit(Atr, tr["inefficient"], lam)), 1e-9, 1 - 1e-9)
        return -np.mean(va["inefficient"] * np.log(q) + (1 - va["inefficient"]) * np.log(1 - q))
    lam_c = min(PENALTIES, key=val_logloss)
    w_c = logistic_fit(Atr, tr["inefficient"], lam_c)
    t_lr = best_f1_threshold(va["inefficient"], sigmoid(Ava @ w_c))
    p_lr = sigmoid(Ate @ w_c)

    # LightGBM
    reg = lgb_fit("regression", tr, tr["l100"], va, va["l100"], seed, rounds)
    clf = lgb_fit("binary", tr, tr["inefficient"], va, va["inefficient"], seed, rounds)
    t_gb = best_f1_threshold(va["inefficient"], clf.predict(lgb_matrix(va), num_iteration=clf.best_iteration))
    p_gb = clf.predict(lgb_matrix(te), num_iteration=clf.best_iteration)

    regression = {
        "class_mean": {"inputs": "vehicle class only (training mean L/100 km per class)",
                       **regression_report(te["l100"], cmean[te["vehicle_class"]])},
        "ridge": {"inputs": "telemetry fields, no fuel reading", "penalty": lam_r,
                  **regression_report(te["l100"], Ate @ w_r)},
        "lightgbm": {"inputs": "telemetry fields, no fuel reading", "trees": int(reg.best_iteration),
                     **regression_report(te["l100"], reg.predict(lgb_matrix(te), num_iteration=reg.best_iteration))},
    }
    classification = {
        "fleet_average_rule": {"inputs": "the trip's MEASURED L/100 km against 1.15 x the training class median; ignores payload",
                               "threshold": f"l100 > {INEFFICIENT_RATIO} x class median",
                               **flag_report(yte, rule_score > INEFFICIENT_RATIO, ex, rule_score)},
        "fleet_average_rule_f1_tuned": {"inputs": "same score as fleet_average_rule; its line moved to maximise F1 on validation (threshold parity with the models)",
                                        "threshold": f"l100 >= {round(t_rule, 4)} x class median",
                                        **flag_report(yte, rule_score >= t_rule, ex, rule_score)},
        "class_share": {"inputs": "vehicle class only (training inefficient share per class)", "threshold": round(t_share, 4),
                        **flag_report(yte, cshare[te["vehicle_class"]] >= t_share, ex, cshare[te["vehicle_class"]])},
        "logistic_regression": {"inputs": "telemetry fields, no fuel reading", "penalty": lam_c, "threshold": round(t_lr, 4),
                                **flag_report(yte, p_lr >= t_lr, ex, p_lr)},
        "lightgbm": {"inputs": "telemetry fields, no fuel reading", "trees": int(clf.best_iteration), "threshold": round(t_gb, 4),
                     **flag_report(yte, p_gb >= t_gb, ex, p_gb)},
    }
    split = {name: {"months": [min(ms), max(ms)], "trips": len(s["l100"]), "inefficient_share": round(float(s["inefficient"].mean()), 4)}
             for name, ms, s in (("train", TRAIN_MONTHS, tr), ("validation", VAL_MONTHS, va), ("test", TEST_MONTHS, te))}
    return {"split": split, "regression": regression, "classification": classification,
            "feature_importance": {"lightgbm_regressor_gain_share": gain_share(reg), "lightgbm_classifier_gain_share": gain_share(clf)},
            "test_excess": {"trips": len(yte), "excess_litres": round(float(ex.sum()), 1),
                            "excess_share_of_fuel": round(float(ex.sum() / te["litres"].sum()), 4),
                            "excess_co2_kg_assumed_factor": round(float(ex.sum()) * CO2_KG_PER_LITRE, 1),
                            "excess_litres_on_inefficient_trips_share": round(float(ex[yte == 1].sum() / ex.sum()), 4)},
            "class_means_l_per_100km_train": {c: round(float(cmean[k]), 3) for k, c in enumerate(CLASSES)},
            "class_medians_l_per_100km_train": {c: round(float(cmed[k]), 3) for k, c in enumerate(CLASSES)}}


def main() -> None:
    from supplylens.config import REPO_ROOT

    t0 = time.time()
    d = generate(np.random.default_rng(SEED))
    res = run(d)
    reg, cls = res["regression"], res["classification"]
    verdict = {
        "lightgbm_regression_mae_below_class_mean": reg["lightgbm"]["mae_l_per_100km"] < reg["class_mean"]["mae_l_per_100km"],
        "ridge_regression_mae_below_class_mean": reg["ridge"]["mae_l_per_100km"] < reg["class_mean"]["mae_l_per_100km"],
        "lightgbm_auc_above_fleet_average_rule": cls["lightgbm"]["auc"] > cls["fleet_average_rule"]["auc"],
        "lightgbm_f1_above_fleet_average_rule": cls["lightgbm"]["f1"] > cls["fleet_average_rule"]["f1"],
        "lightgbm_f1_above_fleet_average_rule_f1_tuned": cls["lightgbm"]["f1"] > cls["fleet_average_rule_f1_tuned"]["f1"],
        "lightgbm_excess_captured_above_fleet_average_rule": (cls["lightgbm"]["excess_fuel_captured_share"]
                                                              > cls["fleet_average_rule"]["excess_fuel_captured_share"]),
        "logistic_auc_above_fleet_average_rule": cls["logistic_regression"]["auc"] > cls["fleet_average_rule"]["auc"],
        "lightgbm_auc_above_logistic": cls["lightgbm"]["auc"] > cls["logistic_regression"]["auc"],
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = REPO_ROOT / "artifacts" / "experiments" / f"FE1-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    by_class = {c: {"vehicles": FLEET[c], "trips": int(np.sum(d["vehicle_class"] == k)),
                    "inefficient_share": round(float(d["inefficient"][d["vehicle_class"] == k].mean()), 4),
                    "mean_l_per_100km": round(float(d["l100"][d["vehicle_class"] == k].mean()), 3)} for k, c in enumerate(CLASSES)}
    metrics = {
        "experiment_id": out.name, "study": "FE1",
        "kind": "simulated (generated trip telemetry and fuel; a method check, not a measured fleet)",
        "question": "Can trip telemetry flag fuel-inefficient trips, and predict litres per 100 km, better than a fleet-average rule?",
        "data": {"trips": len(d["l100"]), "vehicles": int(sum(FLEET.values())), "drivers": int(d["_n_drivers"]),
                 "less_efficient_drivers": int(d["_weak_drivers"]), "months": 12, "by_class": by_class,
                 "inefficient_share": round(float(d["inefficient"].mean()), 4),
                 "label": f"actual L/100 km > {INEFFICIENT_RATIO} x reference (class/payload base term only)",
                 "excess_fuel": "litres above the reference; includes condition effects (cold, stops, speed) as well as driving",
                 "split": res["split"], "features": FEATURES, "test_excess": res["test_excess"],
                 "class_means_l_per_100km_train": res["class_means_l_per_100km_train"],
                 "class_medians_l_per_100km_train": res["class_medians_l_per_100km_train"]},
        "models": {"regression_test": reg, "classification_test": cls,
                   "threshold_rule": "classifier thresholds maximise F1 on the validation months; the fleet-average rule uses its own fixed 1.15 x median line",
                   "tuning": f"ridge and logistic L2 penalty from {list(PENALTIES)} on validation (MAE / log-loss); LightGBM early stopping ({LGB_EARLY_STOP} rounds) on validation; all fitted on training months only"},
        "verdict": verdict,
        "feature_importance": res["feature_importance"],
        "assumptions": [
            "base rates (L/100 km empty and full) per class are ASSUMED round numbers: " + json.dumps({c: [CLASS_PARAMS[c]["empty"], CLASS_PARAMS[c]["full"]] for c in CLASSES}),
            "effect sizes on fuel (idle, harsh acceleration, speed, stops, temperature, age) are ASSUMED: " + json.dumps(EFFECTS),
            f"{int(WEAK_SHARE * 100)} % of drivers carry a hidden +{WEAK_HIDDEN:.2f} fuel share no telemetry field records (ASSUMED), plus more idling and harsh acceleration",
            f"trip noise on the fuel multiplier Normal(0, {NOISE_SD}) (ASSUMED)",
            f"CO2 factor {CO2_KG_PER_LITRE} kg CO2 per litre of diesel is ASSUMED (rounded); check the current official conversion factor before external use",
            "temperate seasonal temperature cycle (4 C January to 18 C July) plus Normal(0, 3.5) weather noise (ASSUMED)",
        ],
        "limits": [
            "the trips are generated: the models can only recover effects that were put in, and their accuracy reflects the chosen noise level",
            "no real telematics or fuel-card data; replace generate() with recorded trips and fuel readings",
            "the CO2 factor is assumed, so the CO2 figures are fuel litres times an assumed constant",
            "the telemetry models do not see the trip's fuel reading while the fleet-average rule does: different information, stated per model",
            "'inefficient' is measured against the class/payload base term, so cold weather and stop-heavy routes count as excess alongside driving behaviour",
            "one simulated fleet, one seed, one chronological split (test = months 11-12, colder than most of the training year)",
            "the label counts trips (ratio to reference) while the excess-captured share weights by litres, so long heavy trips dominate it and the two can rank models differently",
        ],
        "seeds": {"generator": SEED, "lightgbm": SEED},
        "seconds": round(time.time() - t0, 1),
    }
    config = {"seed": SEED, "fleet": FLEET, "class_params": CLASS_PARAMS, "effects": EFFECTS,
              "drivers_per_vehicle": DRIVERS_PER_VEHICLE, "weak_share": WEAK_SHARE, "weak_hidden": WEAK_HIDDEN,
              "driver_sd": DRIVER_SD, "noise_sd": NOISE_SD, "trip_prob": TRIP_PROB, "inefficient_ratio": INEFFICIENT_RATIO,
              "co2_kg_per_litre_assumed": CO2_KG_PER_LITRE, "months": {"train": list(TRAIN_MONTHS), "validation": list(VAL_MONTHS),
                                                                       "test": list(TEST_MONTHS)},
              "penalties": PENALTIES, "lightgbm": {**LGB_PARAMS, "max_rounds": LGB_ROUNDS, "early_stopping": LGB_EARLY_STOP}}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str))
    (out / "config.json").write_text(json.dumps(config, indent=1, default=str))
    print(json.dumps({"experiment_id": out.name, "seconds": metrics["seconds"], "trips": metrics["data"]["trips"],
                      "regression": {k: (v["mae_l_per_100km"], v["rmse_l_per_100km"]) for k, v in reg.items()},
                      "classification": {k: {f: v[f] for f in ("auc", "precision", "recall", "f1", "flagged_share", "excess_fuel_captured_share")}
                                         for k, v in cls.items()}, "verdict": verdict}, indent=1))


if __name__ == "__main__":
    main()
