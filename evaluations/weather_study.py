"""W1: standard forecast accuracy metrics, Prophet and XGBoost, and does London weather improve UCI demand forecasts? (F6)

Data: UCI Online Retail II daily units (recorded sales) and Open-Meteo historical weather for London (daily mean and max
temperature, precipitation, sunshine; CC BY 4.0; fetched once into data/external/weather/, hash recorded).
Targets: (a) total daily units of the retailer; (b) the 50 best-selling products in the training window, pooled.
Protocol: rolling origin, one origin each Monday from 2011-09-05 to 2011-11-28 (13 origins), horizon 1-7 days, every
model refitted at each origin on data up to the origin only. Weather on the target day is the OBSERVED value, which a
real forecast would not have: the weather gain measured here is an upper bound (a perfect weather forecast).
Models: seasonal naive (same weekday last week), Prophet (weekly + yearly seasonality, UK holidays), XGBoost (lags,
rolling means, calendar, horizon), each of the last two with and without the weather regressors.
Metrics: MAE, RMSE, WAPE, and MAPE over days with non-zero actuals (the shop does not trade on Saturdays, where MAPE is
undefined). The weather effect is the paired difference in absolute error, with a 95 % bootstrap interval over origins.

uv run --with prophet==1.5.0 --with xgboost==3.0.2 python evaluations/weather_study.py
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.request
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text

from supplylens.config import REPO_ROOT
from supplylens.db import tenant_session
from supplylens.seed import tenant_id
from supplylens_ml.metrics import mae, mape, rmse, wape

WEATHER = REPO_ROOT / "data" / "external" / "weather" / "london_daily_2009-11-01_2011-12-09.json"
WEATHER_URL = ("https://archive-api.open-meteo.com/v1/archive?latitude=51.5072&longitude=-0.1276&start_date=2009-11-01"
               "&end_date=2011-12-09&daily=temperature_2m_mean,temperature_2m_max,precipitation_sum,sunshine_duration"
               "&timezone=Europe%2FLondon")
W_COLS = ["temp_mean", "temp_max", "precip", "sun_h"]
ORIGINS = [date(2011, 9, 5) + timedelta(weeks=i) for i in range(13)]
H, TOP_N, BOOT, SEED = 7, 50, 2000, 7


def weather() -> tuple[pd.DataFrame, str]:
    if not WEATHER.exists():
        WEATHER.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(WEATHER_URL, WEATHER)
    raw = WEATHER.read_bytes()
    d = json.loads(raw)["daily"]
    w = pd.DataFrame({"day": pd.to_datetime(d["time"]), "temp_mean": d["temperature_2m_mean"], "temp_max": d["temperature_2m_max"],
                      "precip": d["precipitation_sum"], "sun_h": np.array(d["sunshine_duration"], dtype=float) / 3600})
    return w.set_index("day"), hashlib.sha256(raw).hexdigest()


def load():
    tid = tenant_id("uci-research")
    with tenant_session(tid) as s:
        ds = s.execute(text("SELECT id FROM datasets WHERE name = 'UCI Online Retail II'")).scalar()
        rows = s.execute(text("SELECT sku_id, day, sum(units)::float AS u FROM sales_daily WHERE dataset_id = :d GROUP BY 1, 2"),
                         {"d": ds}).all()
    df = pd.DataFrame(rows, columns=["sku_id", "day", "u"])
    df["day"] = pd.to_datetime(df["day"])
    return df


def dense(series: pd.Series, start, end) -> pd.Series:
    return series.reindex(pd.date_range(start, end, freq="D"), fill_value=0.0)


def snaive(y: pd.Series, origin: pd.Timestamp) -> np.ndarray:
    return np.array([y[origin + timedelta(days=h - 7)] if h <= 7 else y[origin] for h in range(1, H + 1)])


def prophet_fc(y: pd.Series, origin: pd.Timestamp, w: pd.DataFrame | None) -> np.ndarray:
    from prophet import Prophet
    hist = pd.DataFrame({"ds": y.index[y.index <= origin], "y": y[y.index <= origin].values})
    m = Prophet(weekly_seasonality=True, yearly_seasonality=True, daily_seasonality=False)
    m.add_country_holidays(country_name="UK")
    if w is not None:
        for c in W_COLS:
            m.add_regressor(c)
        hist = hist.join(w, on="ds")
    m.fit(hist)
    fut = pd.DataFrame({"ds": [origin + timedelta(days=h) for h in range(1, H + 1)]})
    if w is not None:
        fut = fut.join(w, on="ds")
    return np.clip(m.predict(fut)["yhat"].to_numpy(), 0, None)


def stable_id(key: str) -> int:
    """Item feature that is the same in every run (built-in hash() is randomised per process)."""
    return int(hashlib.sha256(key.encode()).hexdigest(), 16) % 997


def features(y: pd.Series, target: pd.Timestamp, h: int, w: pd.DataFrame | None) -> dict:
    o = target - timedelta(days=h)
    past = y[y.index <= o]
    f = {"h": h, "dow": target.dayofweek, "month": target.month, "doy": target.dayofyear,
         "lag7": y.get(target - timedelta(days=7), 0.0) if h <= 7 else past.iloc[-7],
         "lag14": y.get(target - timedelta(days=14), 0.0), "mean7": past.iloc[-7:].mean(), "mean28": past.iloc[-28:].mean(),
         "same_dow_mean4": np.mean([y.get(target - timedelta(days=7 * k), 0.0) for k in range(1 if h <= 7 else 2, 5)]),
         "to_xmas": (pd.Timestamp(target.year, 12, 25) - target).days}
    if w is not None:
        f.update({c: w.at[target, c] for c in W_COLS})
    return f


def xgb_fc(panel: dict[str, pd.Series], origin: pd.Timestamp, w: pd.DataFrame | None) -> dict[str, np.ndarray]:
    import xgboost as xgb
    rows, ys = [], []
    for key, y in panel.items():
        for t in y.index[(y.index > y.index[0] + timedelta(days=60)) & (y.index <= origin)][::2]:
            for h in (1, 3, 5, 7):
                rows.append({**features(y, t, h, w), "item": stable_id(key)})
                ys.append(y[t])
    X = pd.DataFrame(rows)
    params = {"max_depth": 5, "eta": 0.05, "subsample": 0.8, "colsample_bytree": 0.8, "seed": SEED, "nthread": 8,
              "objective": "reg:squarederror"}
    booster = xgb.train(params, xgb.DMatrix(X, label=np.array(ys)), num_boost_round=300)
    out = {}
    for key, y in panel.items():
        targets = [origin + timedelta(days=h) for h in range(1, H + 1)]
        Xt = pd.DataFrame([{**features(y, t, h, w), "item": stable_id(key)} for h, t in enumerate(targets, 1)])[X.columns]
        out[key] = np.clip(booster.predict(xgb.DMatrix(Xt)), 0, None)
    return out


def scores(y: np.ndarray, f: np.ndarray) -> dict:
    return {"mae": round(mae(y, f), 3), "rmse": round(rmse(y, f), 3), "wape": None if wape(y, f) is None else round(wape(y, f), 4),
            "mape_nonzero_days": None if mape(y, f) is None else round(mape(y, f), 4)}


def paired(err_with: np.ndarray, err_without: np.ndarray, groups: np.ndarray) -> dict:
    """Mean of (|e| with weather - |e| without), 95 % bootstrap interval resampling whole origins."""
    rng = np.random.default_rng(SEED)
    d = err_with - err_without
    ids = np.unique(groups)
    boots = []
    for _ in range(BOOT):
        pick = rng.choice(ids, size=len(ids), replace=True)
        boots.append(np.mean(np.concatenate([d[groups == g] for g in pick])))
    lo, hi = np.percentile(boots, [2.5, 97.5])
    base = np.mean(err_without)
    return {"mean_abs_error_change": round(float(d.mean()), 3), "ci95": [round(float(lo), 3), round(float(hi), 3)],
            "relative_to_without": round(float(d.mean() / base), 4) if base else None,
            "clear": bool(hi < 0 or lo > 0)}


def main() -> None:
    logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
    logging.getLogger("prophet").setLevel(logging.WARNING)
    w, w_sha = weather()
    df = load()
    start, end = df["day"].min(), pd.Timestamp(ORIGINS[-1] + timedelta(days=H))
    total = dense(df.groupby("day")["u"].sum(), start, end)
    train_end = pd.Timestamp(ORIGINS[0])
    top = (df[df["day"] <= train_end].groupby("sku_id")["u"].sum().sort_values(ascending=False).head(TOP_N).index.tolist())
    skus = {k: dense(g.set_index("day")["u"], start, end) for k, g in df[df["sku_id"].isin(top)].groupby("sku_id")}
    t0 = time.time()
    rec = {lvl: {m: [] for m in ("seasonal_naive", "prophet", "prophet_weather", "xgboost", "xgboost_weather")} for lvl in ("total", "skus")}
    actual = {"total": [], "skus": []}
    origin_of = {"total": [], "skus": []}
    for i, o in enumerate(ORIGINS):
        o = pd.Timestamp(o)
        days = [o + timedelta(days=h) for h in range(1, H + 1)]
        actual["total"] += [total[d] for d in days]
        origin_of["total"] += [i] * H
        rec["total"]["seasonal_naive"] += list(snaive(total, o))
        rec["total"]["prophet"] += list(prophet_fc(total, o, None))
        rec["total"]["prophet_weather"] += list(prophet_fc(total, o, w))
        for name, ww in (("xgboost", None), ("xgboost_weather", w)):
            rec["total"][name] += list(xgb_fc({"total": total}, o, ww)["total"])
        sk_no, sk_w = xgb_fc(skus, o, None), xgb_fc(skus, o, w)
        for k, y in skus.items():
            actual["skus"] += [y[d] for d in days]
            origin_of["skus"] += [i] * H
            rec["skus"]["seasonal_naive"] += list(snaive(y, o))
            rec["skus"]["xgboost"] += list(sk_no[k])
            rec["skus"]["xgboost_weather"] += list(sk_w[k])
        print(f"origin {o.date()} done ({time.time() - t0:.0f}s)", flush=True)
    rec["skus"].pop("prophet"), rec["skus"].pop("prophet_weather")       # Prophet per product is out of scope (50 x 13 fits x 2)
    results = {}
    for lvl in ("total", "skus"):
        y = np.array(actual[lvl])
        g = np.array(origin_of[lvl])
        results[lvl] = {"models": {m: scores(y, np.array(f)) for m, f in rec[lvl].items()}, "points": len(y),
                        "weather_effect": {}}
        for base_m in ("prophet", "xgboost"):
            if base_m in rec[lvl]:
                ew = np.abs(y - np.array(rec[lvl][f"{base_m}_weather"]))
                en = np.abs(y - np.array(rec[lvl][base_m]))
                results[lvl]["weather_effect"][base_m] = paired(ew, en, g)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = REPO_ROOT / "artifacts" / "experiments" / f"W1-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    corr = pd.DataFrame({"u": total}).join(w)
    corr = corr[(corr.index >= start + timedelta(days=30)) & (corr.index <= train_end) & (corr["u"] > 0)]
    metrics = {
        "experiment_id": out.name, "study": "W1", "kind": "measured (backtest)",
        "question": "How do Prophet and XGBoost compare on MAE, RMSE, WAPE and MAPE, and does London weather improve the forecasts?",
        "data": {"sales": "UCI Online Retail II daily units", "weather": "Open-Meteo archive, London 51.51N 0.13W",
                 "weather_sha256": w_sha, "weather_licence": "CC BY 4.0", "top_products": TOP_N},
        "protocol": {"origins": [o.isoformat() for o in ORIGINS], "horizon_days": H, "refit_each_origin": True,
                     "weather_on_target_day": "observed (upper bound: a perfect weather forecast)", "bootstrap": f"{BOOT} resamples of origins"},
        "results": results,
        "context": {"corr_units_temp_mean": round(float(corr["u"].corr(corr["temp_mean"])), 3),
                    "corr_units_precip": round(float(corr["u"].corr(corr["precip"])), 3), "corr_window": f"{(start + timedelta(days=30)).date()} to {train_end.date()}, trading days"},
        "seconds": round(time.time() - t0),
        "limits": ["one retailer, one city's weather, one autumn test period", "observed weather stands in for a forecast",
                   "MAPE leaves out zero-sales days; WAPE is the comparable figure", "Prophet is run on the total only",
                   "Prophet's yearly seasonality is fitted on under two years of history (it warns that it may be under-identified)"],
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str))
    (out / "config.json").write_text(json.dumps({"origins": [o.isoformat() for o in ORIGINS], "horizon": H, "top_n": TOP_N, "seed": SEED}, indent=1))
    print(json.dumps({"experiment_id": out.name, "results": results, "context": metrics["context"]}, indent=1))


if __name__ == "__main__":
    main()
