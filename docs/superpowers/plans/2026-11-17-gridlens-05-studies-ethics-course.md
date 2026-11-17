# GridLens Plan 5 — Studies, ethics and the course pack

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the evidence and the deliverables Dr Roy grades: the formal benchmark proving (or disproving) that the AI controllers beat two classical baselines in normal and disrupted regimes, forecasting with calibrated intervals, unit commitment, fairness of load-shedding, cybersecurity under spoofed sensors, demand response and environmental justice of diesel use — then the report, the 40-minute deck, the live-demo and stress-test scripts, the GenAI disclosure and the seven-member contribution record.

**Architecture:** Every study is a script in `evaluations/` that writes `artifacts/experiments/<ID>-<UTC>/metrics.json` and `config.json`, is registered in `evaluations/study_registry.json`, and feeds `docs/course/metrics.md` through `scripts/course_metrics.py`; presentation numbers come only from there. Statistical comparisons are paired by day and scenario with bootstrap confidence intervals. Two simulator extensions support the ethics studies: selectable shed policies and observation-only spoofing events with a plausibility guard.

**Tech Stack:** Python (NumPy, pandas, multiprocessing), the Plans 2–4 packages, Markdown documents rendered by the web app and exported to PDF/PPTX by the team.

**Spec:** §7, §9, §12, §13. **Requires:** Plans 1–4 merged (Task 1–7 need only Plans 1–3).

## Global Constraints

- Test period 2018-11-01 … 2018-12-31 (61 days); validation October; training January 8 … September 30. Never tune on test days.
- Regimes: `normal`, `blackout`, `cloud_drop`, `machine_start`, `combined`, `dr_event`; disrupted regimes run 5 scenario seeds per day; RL controllers run each of their 5 training seeds.
- A controller "beats" another only when the 95 % paired-bootstrap confidence interval of the per-day difference excludes zero. Negative results are reported, not hidden.
- Every number carries its kind: observed, simulated, assumed. Nothing is presented as a real-world saving.
- Worker processes of the benchmark import neither PyTorch nor LightGBM (`NumpyPolicy`, `CachedForecaster`).
- GenAI: every AI-generated paragraph, figure or code block in the deck and report is visibly encircled (CSS class `genai`, a dashed outline with a "GenAI" tag) and its prompt is logged in `docs/course/genai-prompts.md` (slide 20).
- Commit after each task; messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Study index

| ID | Question | Script |
|---|---|---|
| GF1 | Do learned forecasters beat seasonal naive, and are 80 % intervals calibrated? (extended with TCN, LSTM, conformal) | `evaluations/gf1_forecast_study.py` |
| MB1 | Do MPC, PPO and SAC beat the two classical baselines in normal and disrupted regimes (Korea)? | `evaluations/mb_benchmark.py --site kr_gwangyang` |
| MB2 | Same for the UAE what-if | `evaluations/mb_benchmark.py --site ae_industrial` |
| UC1 | Does day-ahead unit commitment with storm warnings reduce unserved energy, at what diesel cost? | `evaluations/uc1_study.py` |
| FS1 | Strict vs rotating vs proportional shedding: equity vs critical load served | `evaluations/fs1_fairness_study.py` |
| CY1 | What do spoofed irradiance/meter values cost, and how much does the plausibility guard recover? | `evaluations/cy1_cyber_study.py` |
| DR1 | Which controllers earn demand-response credit at 10/20/30 % commitments? | `evaluations/dr1_demand_response_study.py` |
| EJ1 | What does a diesel running-hour cap cost in unserved energy, and how much NOx/PM does it avoid? | `evaluations/ej1_diesel_cap_study.py` |

---

### Task 1: Statistics helpers

**Files:**
- Create: `evaluations/energy_stats.py`
- Test: `tests_energy/test_energy_stats.py`

**Interfaces:**
- Produces: `paired_bootstrap(a, b, *, n=10_000, seed=0) -> dict` (`mean_diff` = mean(a − b), `lo`, `hi`, `n_pairs`, `beats` = "a lower" / "b lower" / "no clear difference" for costs); `gini(x) -> float`; `regret(costs, oracle_costs) -> dict` (mean and 95 % CI of `cost − oracle`).

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pytest

from evaluations.energy_stats import gini, paired_bootstrap


def test_clear_difference_is_detected():
    rng = np.random.default_rng(0)
    b = rng.normal(100, 5, 60)
    r = paired_bootstrap(b - 10, b)
    assert r["hi"] < 0 and r["beats"] == "a lower"


def test_no_difference_is_reported_as_such():
    rng = np.random.default_rng(1)
    a = rng.normal(100, 5, 60)
    r = paired_bootstrap(a, a + rng.normal(0, 5, 60))
    assert r["lo"] < 0 < r["hi"] and r["beats"] == "no clear difference"


def test_gini():
    assert gini([1, 1, 1, 1]) == pytest.approx(0.0)
    assert gini([0, 0, 0, 4]) == pytest.approx(0.75)
```
Make `evaluations/` importable for tests: add `evaluations/__init__.py` (empty) if it does not exist, and add `"evaluations"` to nothing else (it is imported only by tests and scripts run from the repo root).

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests_energy/test_energy_stats.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `evaluations/energy_stats.py`**

```python
"""Paired bootstrap, Gini and regret for the GridLens studies (spec §7)."""
from __future__ import annotations

import numpy as np


def paired_bootstrap(a, b, *, n: int = 10_000, seed: int = 0) -> dict:
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    rng = np.random.default_rng(seed)
    means = d[rng.integers(0, len(d), size=(n, len(d)))].mean(axis=1)
    lo, hi = np.quantile(means, [0.025, 0.975])
    beats = "a lower" if hi < 0 else "b lower" if lo > 0 else "no clear difference"
    return {"mean_diff": float(d.mean()), "lo": float(lo), "hi": float(hi), "n_pairs": int(len(d)), "beats": beats}


def gini(x) -> float:
    v = np.sort(np.asarray(x, dtype=float))
    if v.sum() == 0:
        return 0.0
    n = len(v)
    return float((2 * np.arange(1, n + 1) - n - 1) @ v / (n * v.sum()))


def regret(costs, oracle_costs, *, seed: int = 0) -> dict:
    r = paired_bootstrap(costs, oracle_costs, seed=seed)
    return {"mean": r["mean_diff"], "lo": r["lo"], "hi": r["hi"]}
```

- [ ] **Step 4: Run tests and commit**

```bash
uv run pytest tests_energy/test_energy_stats.py -q
git add evaluations/energy_stats.py evaluations/__init__.py tests_energy/test_energy_stats.py
git commit -m "Add paired bootstrap, Gini and regret helpers for GridLens studies

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Benchmark MB1/MB2

**Files:**
- Create: `evaluations/mb_benchmark.py`
- Modify: `evaluations/study_registry.json`, `scripts/course_metrics.py`

**Interfaces:**
- Consumes: `summarise`-style loop (Plan 2/3), controllers (Plan 3), `CachedForecaster`, `NumpyPolicy`, `paired_bootstrap`, `regret`.
- Produces: `artifacts/experiments/MB1-<UTC>/episodes.csv` (git-ignored, one row per day × regime × seed × controller × forecaster) and `metrics.json` (committed): per regime and controller the mean of every KPI, paired bootstrap of `operating_cost`, `total_cost`, `unserved_kwh`, `co2_kg` against `rule_tou` and `greedy_self`, regret against `oracle`, and the forecaster factor for MPC (`naive` vs `lgbm`).

- [ ] **Step 1: Write the script**

```python
"""MB1/MB2: every controller on 2018-11-01..12-31 in normal and disrupted regimes (spec §7).

    uv run python evaluations/mb_benchmark.py --site kr_gwangyang [--seeds 5] [--workers 10] [--days 61]
"""
from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from evaluations.energy_stats import paired_bootstrap, regret

ROOT = Path(__file__).resolve().parents[1]
REGIMES = ["normal", "blackout", "cloud_drop", "machine_start", "combined", "dr_event"]
KPIS = ["operating_cost", "total_cost", "peak_import_kw", "co2_kg", "nox_g", "pm_g", "unserved_kwh",
        "critical_served_pct", "shed_events", "min_nadir_hz", "dr_cost", "dr_shortfall_kwh", "mean_power_factor",
        "pf_penalty", "capacity_fade_pct", "battery_cycles", "diesel_unit_hours", "decision_ms_mean"]


def _episodes(job: tuple) -> list[dict]:
    site_id, day_start, regime, seed = job
    from gridlens_control.baselines import GreedySelf, NoBattery, RuleTOU
    from gridlens_control.mpc import PerfectInfoOracle, StochasticMPC
    from gridlens_control.policy import NumpyPolicy, RLController
    from gridlens_control.runner import run_episode
    from gridlens_sim.disruptions import generate
    from gridlens_sim.env import MicrogridEnv
    from gridlens_sim.factory import load_park
    from gridlens_sim.forecast import CachedForecaster, SeasonalNaiveForecaster
    park = load_park(site_id)
    site, s = park.site, park.series
    naive = SeasonalNaiveForecaster(s)
    lgbm = CachedForecaster(ROOT / "data" / "silver" / "energy" / f"forecasts_{site_id}.npz", naive)
    scenario = generate(seed * 100_003 + day_start, regime, site.p_peak_kw)
    rows = []
    for fname, fc in (("lgbm", lgbm), ("naive", naive)):
        env = MicrogridEnv(site, s, fc)
        ctrls = [StochasticMPC(site, scenarios=5, horizon=48, name="stochastic_mpc")]
        if fname == "lgbm":
            ctrls += [NoBattery(), RuleTOU(site), GreedySelf(site), PerfectInfoOracle(site, env, horizon=48)]
            for meta_path in sorted((ROOT / "models" / "rl" / site_id).glob("*_seed*.json")):
                meta = json.loads(meta_path.read_text())
                pol = NumpyPolicy.load(meta_path.with_suffix(".npz"), expected_sha256=meta["sha256"])
                tag = f"{meta['algo']}{'_bc' if meta.get('warm_start') else ''}"
                ctrls.append(RLController(pol, site, f"{tag}|{meta['seed']}"))
        for c in ctrls:
            k = run_episode(env, c, day_start, scenario).kpis()
            name, _, train_seed = c.name.partition("|")
            rows.append({"controller": name, "train_seed": train_seed or None, "forecaster": fname,
                         "regime": regime, "day_start": day_start, "seed": seed, **k})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", default="kr_gwangyang")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--days", type=int, default=61)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = ap.parse_args()
    from gridlens_sim.factory import load_park
    s = load_park(args.site).series
    days = s.day_starts("2018-11-01", "2018-12-31")[: args.days]
    jobs = [(args.site, d, r, seed) for d in days for r in REGIMES
            for seed in ([0] if r == "normal" else range(args.seeds))]
    with ProcessPoolExecutor(args.workers) as pool:
        df = pd.DataFrame([row for rows in pool.map(_episodes, jobs) for row in rows])
    study = "MB1" if args.site == "kr_gwangyang" else "MB2"
    run = f"{study}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    out = ROOT / "artifacts" / "experiments" / run
    out.mkdir(parents=True)
    df.to_csv(out / "episodes.csv", index=False)
    main_df = df[df.forecaster == "lgbm"]
    # RL: average over training seeds per (day, regime, scenario seed) before pairing
    agg = main_df.groupby(["controller", "regime", "day_start", "seed"])[KPIS].mean().reset_index()
    results = {}
    for regime, g in agg.groupby("regime"):
        piv = {m: g.pivot_table(index=["day_start", "seed"], columns="controller", values=m) for m in
               ("operating_cost", "total_cost", "unserved_kwh", "co2_kg")}
        res = {"means": g.groupby("controller")[KPIS].mean().round(4).to_dict(orient="index"), "comparisons": {}}
        for ctrl in piv["total_cost"].columns:
            for base in ("rule_tou", "greedy_self"):
                if ctrl == base or base not in piv["total_cost"]:
                    continue
                res["comparisons"][f"{ctrl}_vs_{base}"] = {
                    m: paired_bootstrap(piv[m][ctrl], piv[m][base]) for m in piv}
            if "oracle" in piv["total_cost"] and ctrl != "oracle":
                res["comparisons"][f"{ctrl}_regret"] = regret(piv["total_cost"][ctrl], piv["total_cost"]["oracle"])
        results[regime] = res
    mpc = df[df.controller == "stochastic_mpc"].pivot_table(index=["regime", "day_start", "seed"],
                                                             columns="forecaster", values="total_cost")
    metrics = {"study": study, "site": args.site, "days": len(days), "seeds": args.seeds,
               "results": results,
               "forecaster_effect_mpc": paired_bootstrap(mpc["lgbm"], mpc["naive"]),
               "data": {"load": "observed", "pv": "simulated from observed weather", "assets": "assumed",
                        "disruptions": "simulated, seeded", "results": "simulation, not real outcomes"}}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2, default=float) + "\n")
    (out / "config.json").write_text(json.dumps({"regimes": REGIMES, "mpc": {"scenarios": 5, "horizon": 48},
                                                 "bootstrap": 10_000}, indent=2) + "\n")
    print(run)


if __name__ == "__main__":
    main()
```
Add `artifacts/experiments/*/episodes.csv` to `.gitignore` (the whitelist only admits `metrics.json`, `config.json`, `selection.json`, `cohort.json`; confirm with `git check-ignore`).

- [ ] **Step 2: Smoke-run, then the full runs (long; run in the background on the owner's machine)**

```bash
uv run python evaluations/mb_benchmark.py --days 2 --seeds 1 --workers 4
uv run python evaluations/mb_benchmark.py --site kr_gwangyang
uv run python evaluations/mb_benchmark.py --site ae_industrial
```
Expected: each prints its run ID. Open `metrics.json` and read the comparisons before writing any headline.

- [ ] **Step 3: Register and regenerate course metrics**

Add MB1 and MB2 entries to `evaluations/study_registry.json` (`status`, `headline` stating for each regime whether MPC/PPO/SAC beat `rule_tou` and `greedy_self` on total cost with the CI, the forecaster effect, and the regret; `notes` with the data kinds). Add `DATA_KIND` and size rows for MB1, MB2 in `scripts/course_metrics.py`; run it with `--check`.

- [ ] **Step 4: Commit**

```bash
git add evaluations/mb_benchmark.py evaluations/study_registry.json scripts/course_metrics.py docs/course/metrics.* \
  artifacts/experiments/MB*/metrics.json artifacts/experiments/MB*/config.json .gitignore
git commit -m "Add MB1/MB2 benchmark with paired bootstrap against both baselines and oracle regret

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: GF1 extension — TCN, LSTM and conformal calibration

**Files:**
- Create: `ml/gridlens_ml/conformal.py`, `evaluations/gf1_deep_child.py`
- Modify: `evaluations/gf1_forecast_study.py`, `scripts/cache_forecasts.py` (store calibrated forecasts when `--conformal`)
- Delete (moved): `evaluations/lstm_study.py`, `evaluations/lstm_child.py` after their model code lives in `gf1_deep_child.py`
- Test: `tests_energy/test_conformal.py`

**Interfaces:**
- Produces: `fit_band_offsets(pred (n,H,5), truth (n,H), target=0.8, bands=BANDS) -> dict[str, float]` (per horizon band, the additive widening that gives 80 % coverage on calibration data, split-conformal with the finite-sample correction); `apply_offsets(pred, offsets, bands) -> pred` (q10 −= offset, q90 += offset, q25/q75 by half, re-sorted, non-negative); the child script trains the quantile TCN (from `ml/gridlens_ml/tcn.py`) and an LSTM on the same features and issue times, in its own process, and writes test predictions to an `.npz` the study reads.

- [ ] **Step 1: Write the failing test**

```python
import numpy as np

from gridlens_ml.conformal import apply_offsets, fit_band_offsets

BANDS = {"all": (1, 96)}


def test_conformal_widening_restores_coverage():
    rng = np.random.default_rng(0)
    truth = rng.normal(0, 1, (400, 96))
    narrow = np.stack([np.full((400, 96), q) for q in (-0.4, -0.2, 0.0, 0.2, 0.4)], axis=-1)   # too narrow
    off = fit_band_offsets(narrow[:200], truth[:200], bands=BANDS)
    fixed = apply_offsets(narrow[200:], off, BANDS)
    cover = np.mean((truth[200:] >= fixed[..., 0]) & (truth[200:] <= fixed[..., 4]))
    assert 0.76 <= cover <= 0.86
```
(Negative values are allowed in this synthetic test; pass `nonnegative=False` to `apply_offsets`.)

- [ ] **Step 2: Run it to see it fail, then implement**

`ml/gridlens_ml/conformal.py`:
```python
"""Split-conformal widening of quantile intervals per horizon band (calibrated on October, applied to test)."""
from __future__ import annotations

import numpy as np


def fit_band_offsets(pred, truth, target: float = 0.8, bands=None) -> dict[str, float]:
    bands = bands or {"1h": (1, 4), "6h": (5, 24), "24h": (25, 96)}
    out = {}
    for name, (lo, hi) in bands.items():
        p, y = pred[:, lo - 1:hi], truth[:, lo - 1:hi]
        score = np.maximum(p[..., 0] - y, y - p[..., 4]).ravel()      # > 0 when outside the 80 % interval
        n = len(score)
        level = min(1.0, np.ceil((n + 1) * target) / n)
        out[name] = float(np.quantile(score, level, method="higher"))
    return out


def apply_offsets(pred, offsets: dict[str, float], bands=None, nonnegative: bool = True):
    bands = bands or {"1h": (1, 4), "6h": (5, 24), "24h": (25, 96)}
    out = np.array(pred, dtype=float, copy=True)
    for name, (lo, hi) in bands.items():
        o = offsets[name]
        sl = slice(lo - 1, hi)
        out[:, sl, 0] -= o
        out[:, sl, 1] -= o / 2
        out[:, sl, 3] += o / 2
        out[:, sl, 4] += o
    out = np.sort(out, axis=-1)
    return np.clip(out, 0.0, None) if nonnegative else out
```
Run: `uv run pytest tests_energy/test_conformal.py -q` → `1 passed`.

- [ ] **Step 3: Deep models in a child process**

Write `evaluations/gf1_deep_child.py` by moving the model-building and training code from `evaluations/lstm_child.py` and `ml/gridlens_ml/tcn.py` and pointing it at the GF1 features: input = the `features()` matrix of `gridlens_ml.energy_forecast` for each issue time (96 rows × feature columns), output = 96 × 5 quantiles, pinball loss averaged over the five quantiles, 3 seeds, early stopping on October. CLI: `python evaluations/gf1_deep_child.py --site kr_gwangyang --model tcn|lstm --out <npz>`; it must not import LightGBM. In `gf1_forecast_study.py` call it with `subprocess.run([sys.executable, ...], check=True)  # noqa: S603`, load the `.npz`, and add `tcn` and `lstm` to the results; then fit conformal offsets on October for every model and report raw and calibrated coverage and pinball loss.

- [ ] **Step 4: Run, register, commit**

```bash
uv run python evaluations/gf1_forecast_study.py
git rm -q evaluations/lstm_study.py evaluations/lstm_child.py tests/test_lstm_study.py
# update the GF1 registry entry (new run supersedes the Plan 2 run: mark the old one "superseded" with the reason)
uv run python scripts/course_metrics.py && uv run python scripts/course_metrics.py --check
git add -A ml/gridlens_ml/conformal.py evaluations tests_energy/test_conformal.py scripts/course_metrics.py docs/course \
  artifacts/experiments/GF1-*/metrics.json artifacts/experiments/GF1-*/config.json
git commit -m "Extend GF1 with quantile TCN, LSTM and split-conformal calibration

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Shed policies and study FS1 (fairness)

**Files:**
- Modify: `sim/gridlens_sim/tenants.py` (`allocate_shed(..., policy="rotating")`), `sim/gridlens_sim/env.py` (`MicrogridEnv(..., shed_policy="rotating")`)
- Create: `evaluations/fs1_fairness_study.py`
- Test: `tests_energy/test_shed_policies.py`

**Interfaces:**
- Produces: shed policies `"strict"` (fixed order, no rotation), `"rotating"` (default, Plan 2), `"proportional"` (non-critical tenants shed in proportion to their demand; critical only after all non-critical load is shed).

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pytest

from gridlens_sim.tenants import DEFAULT_TENANTS, allocate_shed

KW = np.array([350.0, 250.0, 150.0, 150.0, 100.0])


def test_strict_ignores_rotation():
    a = allocate_shed(200.0, KW, DEFAULT_TENANTS, rotation=0, policy="strict")
    b = allocate_shed(200.0, KW, DEFAULT_TENANTS, rotation=1, policy="strict")
    assert a.tolist() == b.tolist() == [0, 0, 0, 150, 50]


def test_proportional_spreads_over_non_critical():
    out = allocate_shed(130.0, KW, DEFAULT_TENANTS, rotation=0, policy="proportional")
    assert out[0] == 0 and out.sum() == pytest.approx(130.0)
    np.testing.assert_allclose(out[1:] / KW[1:], np.full(4, 130.0 / KW[1:].sum()))


def test_proportional_reaches_critical_last():
    out = allocate_shed(700.0, KW, DEFAULT_TENANTS, rotation=0, policy="proportional")
    assert out[1:].tolist() == KW[1:].tolist() and out[0] == pytest.approx(50.0)
```

- [ ] **Step 2: Implement**

In `tenants.py` change the signature to `allocate_shed(shed_kw, tenant_kw, tenants, rotation, policy="rotating")`; for `"strict"` call the existing loop with `rotation=0`; for `"proportional"`:
```python
    if policy == "proportional":
        out = np.zeros(len(tenants))
        non = np.array([t.priority != "critical" for t in tenants])
        pool = float(tenant_kw[non].sum())
        take = min(float(shed_kw), pool)
        if pool > 0:
            out[non] = tenant_kw[non] * (take / pool)
        rest = float(shed_kw) - take
        if rest > 1e-9:
            crit = ~non
            cpool = float(tenant_kw[crit].sum())
            if rest > cpool + 1e-6:
                raise ValueError(f"cannot shed {shed_kw:.3f} kW")
            out[crit] = tenant_kw[crit] * (rest / cpool)
        return out
```
In `env.py` add the constructor argument `shed_policy: str = "rotating"` and pass it to `allocate_shed`. UFLS stages are unchanged (they are physical relays by class).
Run: `uv run pytest tests_energy -q`.

- [ ] **Step 3: Write `evaluations/fs1_fairness_study.py`**

For each policy in (`strict`, `rotating`, `proportional`) and controllers (`rule_tou`, `stochastic_mpc` with cached LightGBM forecasts), run the 61 test days under `blackout` and `combined` with 5 seeds; per tenant accumulate demand and shed energy; report per policy: Gini of `shed / demand` across non-critical tenants, maximum single-tenant share of all shed energy, number of distinct tenants shed first, critical-load served %, total unserved kWh, total cost; paired bootstrap of unserved kWh and Gini between policies. Write `FS1-<UTC>/metrics.json` and `config.json`; register; add to course metrics.

- [ ] **Step 4: Run and commit**

```bash
uv run python evaluations/fs1_fairness_study.py
git add -A sim evaluations tests_energy scripts/course_metrics.py docs/course artifacts/experiments/FS1-*/*.json
git commit -m "Add strict/rotating/proportional shed policies and fairness study FS1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Spoofed sensors, plausibility guard and study CY1 (cybersecurity)

**Files:**
- Modify: `sim/gridlens_sim/disruptions.py` (kinds `spoof_pv`, `spoof_load`; `Scenario.spoof_factor(kind, k)`), `sim/gridlens_sim/env.py` (controllers see spoofed observations; physics uses the truth)
- Create: `control/gridlens_control/guard.py`, `evaluations/cy1_cyber_study.py`, `docs/security/gridlens-threat-model.md`
- Test: `tests_energy/test_cyber.py`

**Interfaces:**
- Produces: `Event("spoof_pv" | "spoof_load", start, duration, magnitude)` where magnitude multiplies the *observed* value and the observed forecast for the next 8 steps; `PlausibilityGuard(inner: Controller, site)` (name `f"{inner.name}+guard"`) that flags PV above `1.05 × kWp × inverter efficiency` or above 5 % of kWp while the sun is down (pvlib solar position), and load outside `[0, 1.3 × P_peak]` or more than `0.5 × P_peak` away from the last clean observation; it replaces flagged values (PV 0 at night, otherwise the last clean forecast median), counts detections (`guard.detections`) and passes the cleaned observation to the inner controller.

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np

from gridlens_control.baselines import GreedySelf
from gridlens_control.guard import PlausibilityGuard
from gridlens_control.runner import run_episode
from gridlens_sim.disruptions import Event, Scenario
from gridlens_sim.env import MicrogridEnv
from gridlens_sim.forecast import PerfectForecaster
from gridlens_sim.testing import synthetic_series


def env_and_scenario(site):
    s = synthetic_series(site, days=3)
    env = MicrogridEnv(site, s, PerfectForecaster(s))
    sc = Scenario(seed=0, regime="spoof", events=(Event("spoof_pv", 76, 8, 5.0),))   # fake sun at 19:00
    return s, env, sc


def test_spoof_changes_what_the_controller_sees_not_the_physics(site):
    s, env, sc = env_and_scenario(site)
    _, info = env.reset(options={"day_start": 96, "scenario": sc})
    for _ in range(76):
        _, _, _, _, info = env.step(np.array([0.0, 0.0], dtype=np.float32))
    assert info["observation"].pv_kw > 0                 # spoofed observation
    rec = env.step(np.array([0.0, 0.0], dtype=np.float32))[4]["record"]
    assert rec.pv_kw == 0                                  # real PV at night is zero


def test_guard_detects_and_limits_the_damage(site):
    s, env, sc = env_and_scenario(site)
    raw = run_episode(env, GreedySelf(site), 96, sc).kpis()["total_cost"]
    guard = PlausibilityGuard(GreedySelf(site), site)
    guarded = run_episode(env, guard, 96, sc).kpis()["total_cost"]
    assert guard.detections >= 8 and guarded <= raw
```
(With spoofed sun, greedy self-consumption believes there is surplus and charges from the grid at night, so the guarded run is cheaper or equal.)

- [ ] **Step 2: Implement spoofing in the simulator**

`disruptions.py`: add `SPOOF_KINDS = ("spoof_pv", "spoof_load")` and
```python
    def spoof_factor(self, kind: str, k: int) -> float:
        f = 1.0
        for e in self.events:
            if e.kind == kind and e.active(k):
                f *= e.magnitude
        return f
```
For `spoof_pv` at night (true PV 0) a multiplicative factor has no effect, so define the observed PV as `true_pv * f + (f - 1) * 0.1 * kWp` when `f > 1` — document this ("an attacker injects a plausible-looking daytime value"); add `regime="spoof"` handling to `generate`: one `spoof_pv` event of 2–4 h starting 17:00–21:00 with magnitude 5.0, or one `spoof_load` event of 1–2 h with magnitude 0.3 (under-reporting load), chosen by the seed.
`env.py`: keep `self._obs` as the truth for physics; build the controller's view with
```python
    def _view(self, o: Observation) -> Observation:
        sc, k, kwp = self.scenario, o.k, self.site.pv.kwp
        fp, fl = sc.spoof_factor("spoof_pv", k), sc.spoof_factor("spoof_load", k)
        if fp == 1.0 and fl == 1.0:
            return o
        pv = o.pv_kw * fp + (max(fp - 1.0, 0.0) * 0.1 * kwp)
        fc = o.forecast.copy()
        fc[1, :8] = fc[1, :8] * fp + max(fp - 1.0, 0.0) * 0.1 * kwp
        fc[0, :8] = fc[0, :8] * fl
        return dataclasses.replace(o, pv_kw=pv, load_kw=o.load_kw * fl, forecast=fc)
```
and return `self._view(self._obs)` in `info["observation"]` and as the basis of the observation vector (both in `reset` and `step_action`), while `step_action` keeps using `self._obs` for the physics.

- [ ] **Step 3: Write `control/gridlens_control/guard.py`**

```python
"""Plausibility guard against spoofed irradiance and meter values (spec §9.1, study CY1).

Checks use only what an attacker on the data feed cannot change: physical limits, the sun's position (pvlib) and
the last observation the guard accepted as clean. A spoofed forecast cannot vouch for a spoofed reading."""
from __future__ import annotations

import dataclasses

import pandas as pd
from pvlib import solarposition

from gridlens_sim.env import Action, Observation


class PlausibilityGuard:
    def __init__(self, inner, site):
        self.inner, self.site = inner, site
        self.name = f"{inner.name}+guard"
        self.reset()

    def reset(self) -> None:
        self.inner.reset()
        self.last_clean: Observation | None = None
        self.detections = 0

    def _sun_up(self, ts: pd.Timestamp) -> bool:
        sp = solarposition.get_solarposition(pd.DatetimeIndex([ts + pd.Timedelta(minutes=7.5)]),
                                             self.site.latitude, self.site.longitude)
        return float(sp["apparent_elevation"].iloc[0]) > 0.0

    def act(self, obs: Observation) -> Action:
        site, ref = self.site, self.last_clean
        pv, load = obs.pv_kw, obs.load_kw
        sun = self._sun_up(obs.timestamp)
        pv_cap = 1.05 * site.pv.kwp * site.pv.inverter_efficiency
        bad_pv = pv > pv_cap or (not sun and pv > 0.05 * site.pv.kwp)
        bad_load = load < 0 or load > 1.3 * site.p_peak_kw or (
            ref is not None and abs(load - ref.load_kw) > 0.5 * site.p_peak_kw)
        if not (bad_pv or bad_load):
            self.last_clean = obs
            return self.inner.act(obs)
        self.detections += 1
        pv_fix = 0.0 if not sun else (float(ref.forecast[1, 0, 2]) if ref is not None else 0.0)
        load_fix = float(ref.forecast[0, 0, 2]) if ref is not None else min(max(load, 0.0), site.p_peak_kw)
        clean = dataclasses.replace(obs, pv_kw=pv_fix if bad_pv else pv, load_kw=load_fix if bad_load else load)
        return self.inner.act(clean)
```
`generate` must accept the new regime: add `"spoof"` to `REGIMES` (not to `DISRUPTED`, so RL training never sees attacks unless a study asks for it).

- [ ] **Step 4: Threat model and study**

`docs/security/gridlens-threat-model.md`: STRIDE table for the EMS data flows (meters → API, weather/forecast feed → controllers, controller → safety layer → plant adapter, operator approvals, tenant portal): threat, example, impact on the park, control in GridLens (with file paths: plausibility guard, safety layer, HMAC-signed plant commands, approvals bound to payload hash with separation of duties, row-level security, append-only audit, rate limits), residual risk, and what a real deployment adds (IEC 62443 zones, OT network segregation, signed firmware). 
`evaluations/cy1_cyber_study.py`: for controllers `greedy_self`, `rule_tou`, `stochastic_mpc` (each raw and with `PlausibilityGuard`), run the 61 test days under `spoof` with 5 seeds plus the same days under `normal`; report cost increase vs normal, unserved energy, detection rate (detected steps / spoofed steps) and false alarms on normal days; paired bootstrap guard vs raw. Register CY1; add to course metrics.

- [ ] **Step 5: Run and commit**

```bash
uv run pytest tests_energy -q && uv run python evaluations/cy1_cyber_study.py
git add -A sim control evaluations docs/security tests_energy scripts/course_metrics.py docs/course artifacts/experiments/CY1-*/*.json
git commit -m "Add sensor-spoofing scenarios, plausibility guard, STRIDE threat model and study CY1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Studies UC1, DR1 and EJ1

**Files:**
- Modify: `optimisation/gridlens_opt/unit_commitment.py` (optional `max_hours_per_unit`), `config/sites/*.yaml` (`diesel.max_hours_per_day: 8`)
- Create: `evaluations/uc1_study.py`, `evaluations/dr1_demand_response_study.py`, `evaluations/ej1_diesel_cap_study.py`
- Test: `tests_energy/test_unit_commitment.py` (one new case)

**Interfaces:**
- Produces: `commit_day(..., max_hours_per_unit=None)` adding `Σ_h on[u,h] ≤ 4 × max_hours` per unit (planned commitment only; emergency starts in islanded mode are never blocked — safety first, and the study reports how often they happen).

- [ ] **Step 1: Write the failing test and implement the cap**

```python
def test_running_hour_cap(site):
    net90 = np.full(N, site.grid.import_limit_kw + site.battery.power_kw + 200.0)
    c = commit_day(site, np.full(N, 500.0), net90, np.full(N, 100.0), max_hours_per_unit=4)
    assert (c.on.sum(axis=0) <= 16).all()
```
Add to `commit_day`: `if max_hours_per_unit is not None: solver.Add(solver.Sum(on[u]) <= int(4 * max_hours_per_unit))` per unit. Run the tests.

- [ ] **Step 2: Write the three studies**

- `uc1_study.py`: 61 test days × (`normal`, `blackout`, `combined`) × 5 seeds; controller `stochastic_mpc` with cached forecasts; arms: no commitment, rule ("commit one unit in every step where forecast q90 net demand exceeds the grid limit"), UC without warning, UC with storm warning on blackout days. Report unserved kWh, critical served %, minimum frequency nadir, diesel unit-hours, fuel, CO2, NOx, PM, total cost; paired bootstrap UC-with-warning vs no commitment.
- `dr1_demand_response_study.py`: `dr_event` regime with committed reduction at 10 %, 20 % and 30 % of peak (override the event magnitude), controllers `rule_tou`, `greedy_self`, `stochastic_mpc`, best `ppo`, best `sac`, `oracle`; report DR credit, shortfall kWh and the share of events fully met; plus the effect on operating cost.
- `ej1_diesel_cap_study.py`: blackout and combined regimes with UC + warning; cap off vs 8 h vs 4 h per unit; report unserved kWh, critical served %, NOx and PM grams, diesel hours and emergency starts that overrode the plan; a short paragraph template in the metrics `notes` for the report's environmental-justice section (who is exposed: workers and neighbours of the generator yard; the cap is a policy lever with a measured reliability price).

Each writes `<ID>-<UTC>/metrics.json` and `config.json`, is registered, and is added to `scripts/course_metrics.py`.

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests_energy -q
uv run python evaluations/uc1_study.py && uv run python evaluations/dr1_demand_response_study.py && uv run python evaluations/ej1_diesel_cap_study.py
uv run python scripts/course_metrics.py && uv run python scripts/course_metrics.py --check
git add -A optimisation config evaluations tests_energy scripts/course_metrics.py docs/course artifacts/experiments/{UC1,DR1,EJ1}-*/*.json
git commit -m "Add unit-commitment, demand-response and diesel-cap studies (UC1, DR1, EJ1)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Course pack

**Files:**
- Create: `docs/course/final-report.md`, `docs/course/final-deck.md`, `docs/course/demo-script.md`, `docs/course/stress-test-runbook.md`, `docs/course/rubric-map.md`, `docs/course/submission-checklist.md`, `docs/course/rehearsal-log.md`
- Rewrite: `docs/course/ai-use-statement.md`, `docs/course/references.md`, `docs/course/responsible-ai.md`
- Update: `docs/course/genai-prompts.md`, `CONTRIBUTIONS.md`, `README.md` (results table from `docs/course/metrics.md`)

- [ ] **Step 1: `final-report.md` skeleton with owners and budgets**

Sections, each with an owner from `CONTRIBUTIONS.md`, a word budget and the studies it draws on:
1. Executive summary (300) — all.
2. The challenge: an industrial park microgrid; costs, power quality, outages (500) — member 7.
3. Related work: deep RL vs MPC for microgrid dispatch; unit commitment; UFLS; demand response; fairness of load-shedding; false-data injection on EMS (900) — members 3, 4, 7.
4. Data and provenance: UCI steel load, Open-Meteo, pvlib, tariffs (assumed values flagged), simulated tenants (500) — member 1.
5. Forecasting (GF1): models, features, calibration, results (700) — member 1.
6. Simulator: physics, safety layer, disruptions, frequency/UFLS, power factor, ageing (700) — member 2.
7. Optimisation and learning: UC MILP, stochastic MPC, PPO/SAC, oracle (900) — members 3, 4.
8. Benchmark (MB1/MB2): protocol, statistics, results by regime, negative results (900) — member 5.
9. Resilience, fairness, cybersecurity, demand response, environmental justice (UC1, FS1, CY1, DR1, EJ1) (1,000) — members 5, 7.
10. The product: architecture, EMS dashboard, approvals, plant adapter, hosting (600) — member 6.
11. Ethical considerations (slide 22 bullets one by one) (600) — member 7.
12. Implementation roadmap: pilot in shadow mode (read-only meters, no commands) → supervised control with approvals → automatic dispatch within limits; data, people, cost, risks, KPIs per phase (600) — all.
13. Limitations (400) — all. 14. References. Appendix: GenAI disclosure, contribution record.
Every number quoted must be copied from `docs/course/metrics.md`.

- [ ] **Step 2: `final-deck.md` — 40 minutes, seven speakers**

Slide plan with time and speaker: (1) Title and team 1 min; (2) The park and the problem 3 min; (3) Requirements map (slides 19/22 → GridLens) 2 min; (4) Data and provenance 3 min; (5) Forecasting 4 min; (6) Simulator and disruptions 4 min; (7) UC and stochastic MPC 4 min; (8) PPO and SAC 4 min; (9) Benchmark results with CIs 5 min; (10) Live demo and stress test 6 min (Task 7 Step 3); (11) Fairness, cyber, DR, diesel justice 3 min; (12) Roadmap and limitations 1 min. Speaker notes per slide; every chart names its study ID; GenAI-assisted content carries the encircled `genai` style.

- [ ] **Step 3: `demo-script.md` and `stress-test-runbook.md`**

Demo script (6 minutes, minute by minute): open hosted Overview (fallback: `docker compose up` already running on the laptop) → precomputed Korea weekday under stochastic MPC playing at 16 steps/s → pause at 14:00 during a DR event, read the "Why" panel → Dispatch: MPC vs rule_tou side by side → Stress test: hand the keyboard to a peer: they press `B` at any step → islanding, frequency nadir, UFLS stages, shed log with reasons, diesel emergency start → Tenants & fairness: the bill allocation with shed compensation → What-if: double the battery → Benchmarks: the MB1 card with its confidence intervals.
Runbook: the 25 most likely peer questions with a one-paragraph answer and the screen or study that proves it, for example "Why not just use the rule?", "Is your RL overfitted?", "What if the forecast is wrong?", "Who decides which factory loses power?", "Is any of this real data?", "What if someone hacks the irradiance feed?", "What does the diesel cap cost?", "Why 15 minutes?", "How would you deploy this tomorrow?", "What did GenAI write?". Include the fault matrix: hosted down → local Docker; projector resolution → zoom settings; solver slow → precomputed replays only.

- [ ] **Step 4: GenAI disclosure, AI-use statement, rubric map, references, checklist**

- `genai-prompts.md`: one row per prompt used (date, tool, member, prompt or link, output, where used); include the prompts that produced the spec, these plans and any code.
- `ai-use-statement.md`: what GenAI produced (code drafts, documentation drafts), what the team verified and how (tests, studies, reviews), what is the team's own work, and how GenAI content is encircled in the deck and report.
- `rubric-map.md`: the slide 20 rubric rows (research depth, innovation, application of techniques, presentation and reporting) mapped to concrete evidence (study IDs, screens, documents).
- `references.md`: verified references only (author, year, title, venue, DOI/URL): UCI steel dataset; Open-Meteo; pvlib; stable-baselines3; PPO (Schulman et al. 2017); SAC (Haarnoja et al. 2018); stochastic MPC and microgrid EMS surveys; unit commitment formulations; ASTM E1049 rainflow; split conformal prediction; CityLearn; KEPCO and ADDC tariff pages. Each one opened and checked before it is listed.
- `submission-checklist.md`: Blackboard upload by 23:59 on 9 Feb 2027 — report PDF, deck PDF/PPTX, repository link and tag `v1.0-final`, GenAI prompt log, contribution record signed off by all seven, demo video backup.
- `rehearsal-log.md`: two full timed rehearsals (dates, timings per section, problems, fixes), one of them fully offline.

- [ ] **Step 5: Final consistency check and commit**

```bash
uv run python scripts/course_metrics.py --check
uv run pytest -q && uv run pytest tests_energy -q && npm --prefix apps/web test
git add -A docs/course CONTRIBUTIONS.md README.md docs/security
git commit -m "Add GridLens course pack: report, deck, demo script, stress-test runbook, GenAI disclosure

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git tag -a v1.0-final -m "GridLens final submission"
```

---

## Done when

- GF1, MB1, MB2, UC1, FS1, CY1, DR1 and EJ1 are registered with headlines written from their metrics files; `scripts/course_metrics.py --check` passes.
- The report, deck, demo script, runbook, GenAI log, AI-use statement, rubric map, references and contribution record are complete, and two rehearsals are logged.
