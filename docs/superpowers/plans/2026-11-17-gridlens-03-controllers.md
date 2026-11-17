# GridLens Plan 3 — Controllers, demand response, power quality and explanations

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the AI and operations-research controllers (day-ahead unit commitment, stochastic MPC, perfect-information oracle, PPO and SAC with NumPy serving) and the energy features the brief's title and scenario call for but Plan 2 does not cover yet: demand-response events, power-factor (reactive power) support, battery ageing, and plain-language explanations of every decision.

**Architecture:** One linear dispatch model (`gridlens_opt/dispatch_lp.py`, OR-Tools GLOP) serves both the stochastic MPC and the oracle; unit commitment is a separate MILP (OR-Tools SCIP) whose output feeds `MicrogridEnv.reset(options={"commitment": ...})`. Reinforcement learning uses stable-baselines3 in its own process (PyTorch and LightGBM must not share a process) and exports the actor to `.npz`, served by a NumPy forward pass. Every controller implements `gridlens_control.base.Controller` and passes through the same safety layer.

**Tech Stack:** OR-Tools (GLOP, SCIP), stable-baselines3 + PyTorch (training only), NumPy, Gymnasium, pytest.

**Spec:** §5.4 (events), §6.1–§6.4, §9.2 (transparency). **Requires:** Plans 1 and 2 merged.

## Global Constraints

- All Plan 2 constraints hold (15-minute steps, battery sign positive = discharge, energy balance < 1e-6 kW, B905 `strict=True`, no database or network in `tests_energy/`, `uv run ruff check --fix` before commits).
- PyTorch is imported only inside `control/gridlens_control/rl.py` functions, `scripts/train_rl.py` and `tests_energy/rl_export_child.py`; never in a process that imports LightGBM.
- Demand response: a committed reduction `R` kW against the customer baseline `CBL = load − PV` (what the park would import without the EMS); credit `incentive × min(reduction, R)`, penalty `penalty × max(0, R − reduction)` per kWh. Rates in site YAML, marked assumed.
- Power factor target 0.90 lagging at the grid point; battery inverter apparent-power rating 1.1 × battery power; reactive power from the steel data's lagging kVArh × 4 (observed).
- Battery ageing: rainflow cycle counting; 6,000 cycles at 80 % depth of discharge to 20 % capacity fade, Wöhler exponent 2 (assumed LFP-like datasheet values).
- Trained policies, forecast caches and RL logs live in git-ignored `models/` and `data/silver/`.
- Commit after each task; messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File map

| File | Change |
|---|---|
| `config/sites/*.yaml` | add `demand_response`, `power_quality`, battery ageing keys |
| `sim/gridlens_sim/config.py` | `DRSpec`, `PQSpec`, ageing fields on `BatterySpec` |
| `ml/gridlens_ml/steel.py` | keep lagging reactive energy |
| `sim/gridlens_sim/series.py`, `testing.py`, `factory.py` | `reactive_kvar` series |
| `sim/gridlens_sim/disruptions.py` | `dr_event` kind and regime, `dr_reduction_kw`, `mixed_sampler` |
| `sim/gridlens_sim/env.py` | observation fields, DR and power-factor accounting, `OBS_DIM = 64` |
| `sim/gridlens_sim/ageing.py` | rainflow and capacity fade |
| `sim/gridlens_sim/forecast.py` | `CachedForecaster` |
| `control/gridlens_control/runner.py` | new KPIs, `commitment_fn` |
| `optimisation/gridlens_opt/dispatch_lp.py` | shared LP |
| `optimisation/gridlens_opt/unit_commitment.py` | day-ahead MILP |
| `control/gridlens_control/mpc.py` | `StochasticMPC`, `PerfectInfoOracle`, `sample_paths` |
| `control/gridlens_control/commitment.py` | UC hooks for the runner |
| `control/gridlens_control/policy.py` | `NumpyPolicy`, `RLController` |
| `control/gridlens_control/rl.py` | SB3 training, export, behaviour cloning |
| `control/gridlens_control/explain.py` | decision explanations |
| `scripts/cache_forecasts.py`, `scripts/train_rl.py`, `scripts/compare_controllers.py` | tools |
| `tests_energy/test_*.py`, `tests_energy/rl_export_child.py` | tests |

---

### Task 1: Demand-response events and new observation fields

**Files:**
- Modify: `config/sites/kr_gwangyang.yaml`, `config/sites/ae_industrial.yaml`, `sim/gridlens_sim/config.py`, `sim/gridlens_sim/disruptions.py`, `sim/gridlens_sim/env.py`, `control/gridlens_control/runner.py`
- Test: `tests_energy/test_demand_response.py`

**Interfaces:**
- Produces: `Site.demand_response: DRSpec(incentive_per_kwh, penalty_per_kwh)`; regime `"dr_event"` and `Event` kind `"dr_event"` (magnitude = committed reduction kW); `Scenario.dr_reduction_kw(k) -> float`; `mixed_sampler(p_peak_kw, p_disrupted=0.5, regimes=DISRUPTED) -> Callable[[Generator], Scenario]`; `Observation.flex_kw`, `Observation.dr_reduction_kw`, `Observation.dr_ahead (H,)`; `StepRecord.dr_cost`, `StepRecord.dr_shortfall_kw`; KPI `dr_cost`, `dr_shortfall_kwh`; `OBS_DIM` grows (final value set in Task 2).

- [ ] **Step 1: Add the configuration**

Append to `config/sites/kr_gwangyang.yaml`:
```yaml
demand_response: {incentive_per_kwh: 500.0, penalty_per_kwh: 1000.0}   # assumed, KPX-style reliability DR
```
Append to `config/sites/ae_industrial.yaml`:
```yaml
demand_response: {incentive_per_kwh: 0.50, penalty_per_kwh: 1.00}      # assumed what-if programme
```
In `sim/gridlens_sim/config.py` add:
```python
@dataclass(frozen=True)
class DRSpec:
    incentive_per_kwh: float
    penalty_per_kwh: float
```
add the field `demand_response: DRSpec` to `Site` (after `voll_per_kwh`), and in `load_site` pass
`demand_response=DRSpec(**{k: float(v) for k, v in raw["demand_response"].items()})`.

- [ ] **Step 2: Write the failing tests**

`tests_energy/test_demand_response.py`:
```python
import numpy as np
import pytest

from gridlens_sim.disruptions import Event, Scenario, generate, mixed_sampler
from gridlens_sim.env import MicrogridEnv
from gridlens_sim.forecast import PerfectForecaster
from gridlens_sim.testing import synthetic_series


def test_dr_regime_window_and_size():
    for seed in range(30):
        e = generate(seed, "dr_event", 1000.0).events[0]
        assert e.kind == "dr_event" and 8 <= e.duration <= 16
        assert 52 <= e.start and e.start + e.duration <= 72 and e.magnitude == pytest.approx(200.0)


def test_mixed_sampler_is_seeded():
    a = mixed_sampler(1000.0)(np.random.default_rng(3))
    b = mixed_sampler(1000.0)(np.random.default_rng(3))
    assert a == b


def test_dr_credit_when_battery_delivers_and_penalty_when_not(site):
    s = synthetic_series(site, days=3)
    env = MicrogridEnv(site, s, PerfectForecaster(s))
    sc = Scenario(seed=0, regime="dr_event", events=(Event("dr_event", 56, 8, 200.0),))
    env.reset(options={"day_start": 96, "scenario": sc, "soc": 0.9})
    recs = [env.step(np.array([1.0 if 56 <= k < 64 else 0.0, 0.0], dtype=np.float32))[4]["record"]
            for k in range(96)]
    assert all(r.dr_cost < 0 and r.dr_shortfall_kw == 0 for r in recs[56:58])
    assert all(r.dr_cost == 0 for r in recs[:56])
    env.reset(options={"day_start": 96, "scenario": sc, "soc": 0.5})
    idle = [env.step(np.array([0.0, 0.0], dtype=np.float32))[4]["record"] for _ in range(96)]
    assert idle[56].dr_shortfall_kw == pytest.approx(200.0) and idle[56].dr_cost > 0


def test_observation_announces_dr_ahead(site):
    s = synthetic_series(site, days=3)
    env = MicrogridEnv(site, s, PerfectForecaster(s))
    sc = Scenario(seed=0, regime="dr_event", events=(Event("dr_event", 56, 8, 200.0),))
    _, info = env.reset(options={"day_start": 96, "scenario": sc})
    o = info["observation"]
    assert o.dr_reduction_kw == 0 and o.dr_ahead[55] == 200.0 and o.dr_ahead[63] == 0.0
    assert o.flex_kw == pytest.approx(s.flex_kw[96])
```
(`dr_ahead[h]` covers step `k + 1 + h`; step 56 is index 55 at k = 0.)

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests_energy/test_demand_response.py -q`
Expected: FAIL (`ValueError: unknown regime 'dr_event'` / import error for `mixed_sampler`).

- [ ] **Step 4: Extend `sim/gridlens_sim/disruptions.py`**

Change the constants and add the method, the generator branch and the sampler:
```python
KINDS = ("blackout", "cloud_drop", "machine_start")
REGIMES = ("normal", "blackout", "cloud_drop", "machine_start", "combined", "dr_event")
DISRUPTED = ("blackout", "cloud_drop", "machine_start", "combined", "dr_event")
```
In `Scenario` add:
```python
    def dr_reduction_kw(self, k: int) -> float:
        return float(sum(e.magnitude for e in self.events if e.kind == "dr_event" and e.active(k)))
```
In `generate`, before the loop over kinds, add:
```python
    if regime == "dr_event":                                    # 2-4 h utility event inside 13:00-18:00
        dur = int(rng.integers(8, 17))
        return Scenario(seed, regime, (Event("dr_event", int(rng.integers(52, 73 - dur)), dur, 0.2 * p_peak_kw),))
```
At the end of the module add:
```python
def mixed_sampler(p_peak_kw: float, p_disrupted: float = 0.5, regimes=DISRUPTED):
    """Scenario sampler for training: normal days with probability 1 - p_disrupted, else a random regime."""
    def sample(rng: np.random.Generator) -> Scenario:
        seed = int(rng.integers(2**31 - 1))
        regime = "normal" if rng.random() >= p_disrupted else str(rng.choice(list(regimes)))
        return generate(seed, regime, p_peak_kw)
    return sample
```

- [ ] **Step 5: Extend the environment**

In `sim/gridlens_sim/env.py`:

1. Add to `Observation` (after `band_ahead`): `flex_kw: float`, `dr_reduction_kw: float`, `dr_ahead: np.ndarray`.
2. Add to `StepRecord` (after `total_cost` is fine; keep `reward` last): `dr_cost: float`, `dr_shortfall_kw: float`.
3. In `observe()` add:
```python
            flex_kw=float(s.flex_kw[t]),
            dr_reduction_kw=self.scenario.dr_reduction_kw(k),
            dr_ahead=np.array([self.scenario.dr_reduction_kw(k + 1 + h) if k + 1 + h < self.steps else 0.0
                               for h in range(H)]),
```
4. In `step_action`, after `energy_cost` is computed, add:
```python
        r_dr = o.dr_reduction_kw
        dr_shortfall = max(0.0, r_dr - ((o.load_kw - o.pv_kw) - d.grid_import_kw)) if r_dr > 0 else 0.0
        dr_cost = ((site.demand_response.penalty_per_kwh * dr_shortfall
                    - site.demand_response.incentive_per_kwh * (r_dr - dr_shortfall)) * DT_H) if r_dr > 0 else 0.0
```
and add `dr_cost` to `total`, and `dr_cost=dr_cost, dr_shortfall_kw=dr_shortfall` to the `StepRecord(...)` call.
5. In `obs_vector`, append to `head`: `obs.flex_kw / p, obs.dr_reduction_kw / p`, and append `_blocks(obs.dr_ahead / p)` to `tail`. Set `OBS_DIM = 15 + 6 * 8` (Task 2 adds one more head value).

- [ ] **Step 6: Extend the runner KPIs**

In `control/gridlens_control/runner.py` `kpis()`: add `+ total("dr_cost")` to `operating_cost`, and add the keys
`"dr_cost": total("dr_cost")` and `"dr_shortfall_kwh": total("dr_shortfall_kw") * DT_H`.

- [ ] **Step 7: Run all energy tests**

Run: `uv run pytest tests_energy -q && uv run ruff check --fix sim control tests_energy`
Expected: all pass (Plan 2 tests included).

- [ ] **Step 8: Commit**

```bash
git add config sim control tests_energy
git commit -m "Add demand-response events with CBL credit/penalty and DR-aware observations

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Power factor and battery VAR support

**Files:**
- Modify: `config/sites/*.yaml`, `sim/gridlens_sim/config.py`, `ml/gridlens_ml/steel.py`, `sim/gridlens_sim/series.py`, `sim/gridlens_sim/testing.py`, `sim/gridlens_sim/factory.py`, `sim/gridlens_sim/env.py`, `control/gridlens_control/runner.py`
- Test: `tests_energy/test_power_quality.py`

**Interfaces:**
- Produces: `Site.power_quality: PQSpec(target_pf, inverter_kva_ratio, pf_penalty_per_kvarh)`; `read_steel(...)` column `lagging_kvarh`; `ParkSeries.reactive_kvar` (defaults to zeros); `build_series(..., reactive_kvar=None)`; `Observation.reactive_kvar`; `StepRecord.reactive_kvar, q_battery_kvar, power_factor, pf_penalty`; KPIs `mean_power_factor` (import-weighted), `pf_penalty`, `low_pf_steps`; `OBS_DIM = 16 + 6 * 8 = 64`.

- [ ] **Step 1: Configuration**

Append to `config/sites/kr_gwangyang.yaml`:
```yaml
power_quality: {target_pf: 0.90, inverter_kva_ratio: 1.1, pf_penalty_per_kvarh: 10.0}   # penalty assumed
```
Append to `config/sites/ae_industrial.yaml`:
```yaml
power_quality: {target_pf: 0.90, inverter_kva_ratio: 1.1, pf_penalty_per_kvarh: 0.02}   # penalty assumed
```
In `config.py` add `PQSpec(target_pf: float, inverter_kva_ratio: float, pf_penalty_per_kvarh: float)`, the `Site` field `power_quality: PQSpec`, and in `load_site` `power_quality=PQSpec(**{k: float(v) for k, v in raw["power_quality"].items()})`.

- [ ] **Step 2: Write the failing tests**

`tests_energy/test_power_quality.py`:
```python
import numpy as np
import pytest

from gridlens_sim.env import OBS_DIM, MicrogridEnv
from gridlens_sim.forecast import PerfectForecaster
from gridlens_sim.testing import synthetic_series


def test_synthetic_series_has_reactive_power(site):
    s = synthetic_series(site, days=2)
    assert s.reactive_kvar.shape == s.load_kw.shape and (s.reactive_kvar > 0).all()


def test_battery_supplies_vars_to_reach_target_pf(site):
    s = synthetic_series(site, days=3)
    env = MicrogridEnv(site, s, PerfectForecaster(s))
    _, info = env.reset(options={"day_start": 96})
    assert info["observation"].reactive_kvar == pytest.approx(s.reactive_kvar[96])
    r = env.step(np.array([0.0, 0.0], dtype=np.float32))[4]["record"]
    assert r.q_battery_kvar > 0
    assert r.power_factor >= site.power_quality.target_pf - 1e-9
    assert r.pf_penalty == pytest.approx(0.0)
    assert OBS_DIM == 64


def test_full_discharge_leaves_less_var_headroom(site):
    s = synthetic_series(site, days=3)
    env = MicrogridEnv(site, s, PerfectForecaster(s))
    env.reset(options={"day_start": 96, "soc": 0.9})
    full = env.step(np.array([1.0, 0.0], dtype=np.float32))[4]["record"]
    kva = site.battery.power_kw * site.power_quality.inverter_kva_ratio
    assert full.q_battery_kvar <= np.sqrt(kva**2 - full.battery_kw**2) + 1e-6
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests_energy/test_power_quality.py -q`
Expected: FAIL (`AttributeError: 'ParkSeries' object has no attribute 'reactive_kvar'`).

- [ ] **Step 4: Carry reactive power through the data path**

`ml/gridlens_ml/steel.py`: change `RENAME` to
```python
RENAME = {"Usage_kWh": "usage_kwh", "Lagging_Current_Reactive.Power_kVarh": "lagging_kvarh",
          "WeekStatus": "week_status", "Load_Type": "load_type"}
```
`sim/gridlens_sim/series.py`: add the last field `reactive_kvar: np.ndarray | None = None` to `ParkSeries` with
```python
    def __post_init__(self):
        if self.reactive_kvar is None:
            object.__setattr__(self, "reactive_kvar", np.zeros_like(self.load_kw))
```
and give `build_series` a keyword `reactive_kvar=None` passed through as `np.asarray(reactive_kvar, dtype=float) if reactive_kvar is not None else None`.
`sim/gridlens_sim/testing.py`: pass `reactive_kvar=0.55 * load` (power factor ≈ 0.88, below the 0.90 target, so
VAR support is exercised; simulated).
`sim/gridlens_sim/factory.py`: pass `reactive_kvar=steel["lagging_kvarh"].to_numpy(dtype=float) * 4.0` (observed).

- [ ] **Step 5: Power-factor accounting in the environment**

In `env.py` add `reactive_kvar: float` to `Observation`, set in `observe()` as `float(s.reactive_kvar[t])`; add to `StepRecord`: `reactive_kvar: float`, `q_battery_kvar: float`, `power_factor: float`, `pf_penalty: float`. In `step_action`, after the dispatch and before costs:
```python
        pq = site.power_quality
        q_load = o.reactive_kvar * (load / o.load_kw if o.load_kw > 1e-9 else 0.0)
        p_grid = d.grid_import_kw
        allowed_q = p_grid * np.tan(np.arccos(pq.target_pf))
        kva = site.battery.power_kw * pq.inverter_kva_ratio
        q_headroom = float(np.sqrt(max(kva**2 - d.battery_kw**2, 0.0)))
        q_battery = min(max(q_load - allowed_q, 0.0), q_headroom) if o.grid_available else 0.0
        q_grid = max(q_load - q_battery, 0.0) if o.grid_available else 0.0
        power_factor = p_grid / float(np.hypot(p_grid, q_grid)) if p_grid > 1e-9 else 1.0
        pf_penalty = max(q_grid - allowed_q, 0.0) * DT_H * pq.pf_penalty_per_kvarh
```
Add `pf_penalty` to `total`, and pass the four new record fields. In `obs_vector` append `obs.reactive_kvar / p` to `head` and set `OBS_DIM = 16 + 6 * 8`.

- [ ] **Step 6: KPIs**

In `runner.py` `kpis()`: add `+ total("pf_penalty")` to `operating_cost`, and:
```python
        imp = np.array([x.grid_import_kw for x in r])
        pfs = np.array([x.power_factor for x in r])
        ...
            "pf_penalty": total("pf_penalty"),
            "mean_power_factor": float((pfs * imp).sum() / imp.sum()) if imp.sum() > 0 else 1.0,
            "low_pf_steps": float(sum(1 for x in r if x.grid_import_kw > 0
                                      and x.power_factor < 0.9 - 1e-9)),
```

- [ ] **Step 7: Run all energy tests and commit**

```bash
uv run pytest tests_energy -q && uv run ruff check --fix sim control ml tests_energy
git add config sim control ml tests_energy
git commit -m "Add power-factor accounting with battery VAR support from observed reactive power

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Battery ageing (rainflow) KPI

**Files:**
- Create: `sim/gridlens_sim/ageing.py`
- Modify: `config/sites/*.yaml` (battery block), `sim/gridlens_sim/config.py` (`BatterySpec`), `control/gridlens_control/runner.py`
- Test: `tests_energy/test_ageing.py`

**Interfaces:**
- Produces: `rainflow(series) -> list[tuple[float, float]]` (depth, count 0.5 or 1.0); `capacity_fade(soc_trace, spec) -> float` (fraction); `BatterySpec.cycle_life_at_80dod`, `end_of_life_fade`, `wohler_exponent` (defaults 6000, 0.2, 2.0); KPI `capacity_fade_pct`. `EpisodeResult` gains `battery_spec` (the `BatterySpec`).

- [ ] **Step 1: Configuration**

Add to the `battery:` mapping in both site files: `cycle_life_at_80dod: 6000, end_of_life_fade: 0.20, wohler_exponent: 2.0`. Add the three fields with those defaults at the end of `BatterySpec`, and pass them in `load_site` with `.get(...)` falling back to the defaults.

- [ ] **Step 2: Write the failing tests**

`tests_energy/test_ageing.py`:
```python
import pytest

from gridlens_sim.ageing import capacity_fade, rainflow


def test_rainflow_counts_two_full_cycles():
    cycles = rainflow([0.0, 1.0, 0.0, 1.0, 0.0])
    assert sum(c for d, c in cycles if d == pytest.approx(1.0)) == pytest.approx(2.0)


def test_flat_series_has_no_cycles():
    assert rainflow([0.5, 0.5, 0.5]) == []


def test_deeper_cycles_age_faster(site):
    shallow = capacity_fade([0.5, 0.6] * 20, site.battery)
    deep = capacity_fade([0.1, 0.9] * 5, site.battery)
    assert deep > shallow > 0


def test_one_full_80pct_cycle_matches_datasheet(site):
    b = site.battery
    assert capacity_fade([0.1, 0.9, 0.1], b) == pytest.approx(b.end_of_life_fade / b.cycle_life_at_80dod)
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests_energy/test_ageing.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Write `sim/gridlens_sim/ageing.py`**

```python
"""Battery cycle ageing: rainflow counting (ASTM E1049) and a depth-of-discharge stress model.

Fade per cycle of depth d = end_of_life_fade / cycle_life_at_80dod * (d / 0.8) ** wohler_exponent. Parameters are
assumed datasheet-style values (spec: battery wear cost is also in every controller's objective).
"""
from __future__ import annotations

import numpy as np


def _reversals(series) -> list[float]:
    x = np.asarray(series, dtype=float)
    if len(x) == 0:
        return []
    x = x[np.r_[True, np.diff(x) != 0]]
    if len(x) < 3:
        return [float(v) for v in x]
    d = np.diff(x)
    keep = [0] + [i for i in range(1, len(x) - 1) if d[i - 1] * d[i] < 0] + [len(x) - 1]
    return [float(x[i]) for i in keep]


def rainflow(series) -> list[tuple[float, float]]:
    stack: list[float] = []
    out: list[tuple[float, float]] = []
    for p in _reversals(series):
        stack.append(p)
        while len(stack) >= 3:
            r_old = abs(stack[-2] - stack[-3])
            r_new = abs(stack[-1] - stack[-2])
            if r_new < r_old:
                break
            if len(stack) == 3:
                out.append((r_old, 0.5))
                stack.pop(0)
            else:
                out.append((r_old, 1.0))
                last = stack.pop()
                stack.pop()
                stack.pop()
                stack.append(last)
    out += [(abs(stack[i + 1] - stack[i]), 0.5) for i in range(len(stack) - 1)]
    return [(d, c) for d, c in out if d > 0]


def capacity_fade(soc_trace, spec) -> float:
    per_cycle = spec.end_of_life_fade / spec.cycle_life_at_80dod
    return float(sum(c * per_cycle * (d / 0.8) ** spec.wohler_exponent for d, c in rainflow(soc_trace)))
```

- [ ] **Step 5: KPI**

In `runner.py`: add the field `battery_spec: object` to `EpisodeResult` (set in `run_episode` as `env.site.battery`) and the KPI
```python
            "capacity_fade_pct": 100.0 * capacity_fade([x.soc for x in r], self.battery_spec),
```
with `from gridlens_sim.ageing import capacity_fade`.

- [ ] **Step 6: Run tests and commit**

```bash
uv run pytest tests_energy -q && uv run ruff check --fix sim control tests_energy
git add config sim control tests_energy
git commit -m "Add rainflow battery ageing KPI

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Shared linear dispatch model

**Files:**
- Create: `optimisation/gridlens_opt/dispatch_lp.py`
- Test: `tests_energy/test_dispatch_lp.py`

**Interfaces:**
- Consumes: `Site` (with `demand_response`), `PRIORITY_WEIGHT`, `DT_H`.
- Produces: `CLASSES = ("critical", "essential", "flexible")`; `LPInput(load (S,N), pv (S,N), grid_available (S,N), price (N,), diesel_on (N,U), dr_reduction (N,), weights (S,), soc0, backlog0_kwh, due0_kwh, peak_so_far_kw, flex_share, class_share: dict, terminal_value_per_kwh, deadline_steps=16)`; `LPPlan(status, battery_kw, backlog_after_kwh, objective, stored_energy_value, battery_path (N,), import_path (N,), solve_ms)`; `solve_dispatch_lp(site, x, time_limit_ms=5000) -> LPPlan`.

- [ ] **Step 1: Write the failing tests**

`tests_energy/test_dispatch_lp.py`:
```python
import numpy as np
import pytest

from gridlens_opt.dispatch_lp import LPInput, solve_dispatch_lp

N = 16


def lp_input(site, *, price, load=600.0, pv=0.0, grid=True, soc0=0.5, dr=None, s=1, diesel_on=None):
    shares = {"critical": 0.35, "essential": 0.40, "flexible": 0.25}
    return LPInput(load=np.full((s, N), load), pv=np.full((s, N), pv), grid_available=np.full((s, N), grid),
                   price=np.asarray(price, dtype=float),
                   diesel_on=np.zeros((N, 2), bool) if diesel_on is None else diesel_on,
                   dr_reduction=np.zeros(N) if dr is None else dr, weights=np.full(s, 1.0 / s), soc0=soc0,
                   backlog0_kwh=0.0, due0_kwh=0.0, peak_so_far_kw=0.0, flex_share=0.145, class_share=shares,
                   terminal_value_per_kwh=0.0)


def test_discharges_into_the_expensive_hours(site):
    price = [60.0] * 8 + [190.0] * 8
    plan = solve_dispatch_lp(site, lp_input(site, price=price))
    assert plan.status == "optimal"
    assert plan.battery_path[8:].sum() > 0 and plan.battery_path[8:].sum() > plan.battery_path[:8].sum()


def test_islanded_without_diesel_battery_carries_the_load(site):
    # 100 kW for 4 h needs 400 kWh; the battery holds 850 kWh above its floor, so nothing is shed
    plan = solve_dispatch_lp(site, lp_input(site, price=[100.0] * N, load=100.0, grid=False, soc0=0.95))
    assert plan.status == "optimal" and plan.battery_kw == pytest.approx(100.0, abs=1e-3)
    assert plan.import_path.max() == 0


def test_dr_event_makes_the_battery_cut_import(site):
    dr = np.zeros(N)
    dr[4:8] = 200.0
    plan = solve_dispatch_lp(site, lp_input(site, price=[100.0] * N, dr=dr, soc0=0.9))
    assert (plan.import_path[4:8] <= 600.0 - 200.0 + 1e-6).all()


def test_stored_energy_has_value_before_a_peak(site):
    price = [60.0] * 4 + [190.0] * 12
    plan = solve_dispatch_lp(site, lp_input(site, price=price, soc0=0.3))
    assert plan.stored_energy_value > 60.0


def test_first_step_is_shared_by_scenarios(site):
    x = lp_input(site, price=[60.0] * 8 + [190.0] * 8, s=3)
    x = LPInput(**{**x.__dict__, "load": x.load * np.array([[0.8], [1.0], [1.2]])})
    plan = solve_dispatch_lp(site, x)
    assert plan.status == "optimal"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests_energy/test_dispatch_lp.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `optimisation/gridlens_opt/dispatch_lp.py`**

```python
"""Linear dispatch model shared by the stochastic MPC and the perfect-information oracle (spec §6.3-§6.4).

Diesel commitment is fixed, so this is a linear programme solved with GLOP. Per scenario s and step h (h = 0 is the
current step): battery charge/discharge and stored energy, grid import/export, diesel output, PV curtailment, shed per
priority class, postponed and recovered flexible demand with a backlog that clears within the deadline and by the
horizon end, a spill slack, demand-response shortfall and one peak-import variable per scenario. Battery,
flexible-demand and backlog decisions of step 0 are shared by all scenarios (non-anticipativity). Costs match
MicrogridEnv. `stored_energy_value` is the dual price of the starting energy: what one more kWh in the battery now
would save.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from ortools.linear_solver import pywraplp

from gridlens_sim.constants import DT_H
from gridlens_sim.tenants import PRIORITY_WEIGHT

CLASSES = ("critical", "essential", "flexible")
SPILL_COST_FACTOR = 1000.0
SHIFT_COST_FACTOR = 0.01


@dataclass(frozen=True)
class LPInput:
    load: np.ndarray
    pv: np.ndarray
    grid_available: np.ndarray
    price: np.ndarray
    diesel_on: np.ndarray
    dr_reduction: np.ndarray
    weights: np.ndarray
    soc0: float
    backlog0_kwh: float
    due0_kwh: float
    peak_so_far_kw: float
    flex_share: float
    class_share: dict
    terminal_value_per_kwh: float
    deadline_steps: int = 16


@dataclass(frozen=True)
class LPPlan:
    status: str
    battery_kw: float
    backlog_after_kwh: float
    objective: float
    stored_energy_value: float
    battery_path: np.ndarray
    import_path: np.ndarray
    solve_ms: float


def solve_dispatch_lp(site, x: LPInput, time_limit_ms: int = 5000) -> LPPlan:
    t0 = time.perf_counter()
    s_n, n = x.load.shape
    b, g, dt = site.battery, site.grid, DT_H
    e_cap, eta = b.energy_kwh, b.eta
    drs = site.demand_response
    solver = pywraplp.Solver.CreateSolver("GLOP")
    solver.SetTimeLimit(time_limit_ms)
    inf = solver.infinity()
    obj = solver.Objective()
    grid_co2_cost = site.carbon_price_per_kg * g.co2_kg_per_kwh
    min_price = max(float(np.min(x.price)), 1e-6)
    ch = [[None] * n for _ in range(s_n)]
    dis = [[None] * n for _ in range(s_n)]
    imp = [[None] * n for _ in range(s_n)]
    first: list[tuple] = []
    soc_rows = []
    for s in range(s_n):
        w = float(x.weights[s])
        peak = solver.NumVar(x.peak_so_far_kw, inf, f"peak{s}")
        obj.SetCoefficient(peak, w * site.tariff.demand_charge_per_kw_month / 30.0)
        soc_prev = backlog_prev = None
        shifts = []
        for h in range(n):
            avail = bool(x.grid_available[s, h])
            load, pv = float(x.load[s, h]), float(x.pv[s, h])
            c = solver.NumVar(0, b.power_kw, f"ch{s}_{h}")
            d = solver.NumVar(0, b.power_kw, f"dis{s}_{h}")
            i = solver.NumVar(0, g.import_limit_kw if avail else 0.0, f"imp{s}_{h}")
            e = solver.NumVar(0, g.export_limit_kw if avail else 0.0, f"exp{s}_{h}")
            cu = solver.NumVar(0, pv, f"curt{s}_{h}")
            sp = solver.NumVar(0, inf, f"spill{s}_{h}")
            sh = solver.NumVar(0, x.flex_share * load, f"shift{s}_{h}")
            sb = solver.NumVar(x.due0_kwh / dt if h == 0 else 0.0, inf, f"back{s}_{h}")
            sheds = [solver.NumVar(0, x.class_share[k] * load, f"shed_{k}{s}_{h}") for k in CLASSES]
            dg = []
            for u, spec in enumerate(site.diesels):
                on = bool(x.diesel_on[h, u])
                v = solver.NumVar(spec.p_min_kw if on else 0.0, spec.p_max_kw if on else 0.0, f"dg{u}_{s}_{h}")
                dg.append(v)
                marginal = spec.fuel_a_l_per_kwh * (spec.fuel_price_per_l
                                                    + site.carbon_price_per_kg * spec.co2_kg_per_l)
                obj.SetCoefficient(v, w * marginal * dt)
            bal = solver.Constraint(load - pv, load - pv, f"bal{s}_{h}")
            for var, coef in ((i, 1), (d, 1), (cu, -1), (sh, 1), (sb, -1), (c, -1), (e, -1), (sp, -1)):
                bal.SetCoefficient(var, coef)
            for v in dg + sheds:
                bal.SetCoefficient(v, 1)
            soc = solver.NumVar(b.soc_min * e_cap, b.soc_max * e_cap, f"soc{s}_{h}")
            row = solver.Constraint(0, 0, f"soc_row{s}_{h}")
            if soc_prev is None:
                row.SetBounds(x.soc0 * e_cap, x.soc0 * e_cap)
                soc_rows.append(row)
            else:
                row.SetCoefficient(soc_prev, -1)
            row.SetCoefficient(soc, 1)
            row.SetCoefficient(c, -eta * dt)
            row.SetCoefficient(d, dt / eta)
            soc_prev = soc
            bl = solver.NumVar(0, 0.0 if h == n - 1 else inf, f"backlog{s}_{h}")
            brow = solver.Constraint(0, 0)
            if backlog_prev is None:
                brow.SetBounds(x.backlog0_kwh, x.backlog0_kwh)
            else:
                brow.SetCoefficient(backlog_prev, -1)
            brow.SetCoefficient(bl, 1)
            brow.SetCoefficient(sh, -dt)
            brow.SetCoefficient(sb, dt)
            backlog_prev = bl
            shifts.append(sh)
            cap = x.backlog0_kwh if h < x.deadline_steps else 0.0
            drow = solver.Constraint(-inf, cap)
            drow.SetCoefficient(bl, 1)
            for v in shifts[-x.deadline_steps:]:
                drow.SetCoefficient(v, -dt)
            prow = solver.Constraint(-inf, 0)
            prow.SetCoefficient(i, 1)
            prow.SetCoefficient(peak, -1)
            r_dr = float(x.dr_reduction[h])
            if r_dr > 0:
                sf = solver.NumVar(0, inf, f"drsf{s}_{h}")
                rr = solver.Constraint(r_dr - (load - pv), inf)
                rr.SetCoefficient(sf, 1)
                rr.SetCoefficient(i, -1)
                obj.SetCoefficient(sf, w * (drs.incentive_per_kwh + drs.penalty_per_kwh) * dt)
            obj.SetCoefficient(i, w * (float(x.price[h]) + grid_co2_cost) * dt)
            obj.SetCoefficient(e, -w * site.tariff.export_price * dt)
            obj.SetCoefficient(c, w * b.degradation_cost_per_kwh * dt)
            obj.SetCoefficient(d, w * b.degradation_cost_per_kwh * dt)
            obj.SetCoefficient(sp, w * SPILL_COST_FACTOR * min_price * dt)
            obj.SetCoefficient(sh, w * SHIFT_COST_FACTOR * min_price * dt)
            for k, v in zip(CLASSES, sheds, strict=True):
                obj.SetCoefficient(v, w * site.voll_per_kwh * PRIORITY_WEIGHT[k] * dt)
            ch[s][h], dis[s][h], imp[s][h] = c, d, i
            if h == 0:
                first.append((c, d, sh, sb, bl))
        obj.SetCoefficient(soc_prev, -w * x.terminal_value_per_kwh)
    for s in range(1, s_n):
        for a, other in zip(first[0], first[s], strict=True):
            r = solver.Constraint(0, 0)
            r.SetCoefficient(a, 1)
            r.SetCoefficient(other, -1)
    obj.SetMinimization()
    code = solver.Solve()
    ms = (time.perf_counter() - t0) * 1000.0
    status = {pywraplp.Solver.OPTIMAL: "optimal", pywraplp.Solver.FEASIBLE: "feasible"}.get(code, "failed")
    if status == "failed":
        return LPPlan(status, 0.0, x.backlog0_kwh, float("nan"), 0.0, np.zeros(n), np.zeros(n), ms)
    wts = np.asarray(x.weights, dtype=float)
    bat = np.array([[dis[s][h].solution_value() - ch[s][h].solution_value() for h in range(n)]
                    for s in range(s_n)])
    imps = np.array([[imp[s][h].solution_value() for h in range(n)] for s in range(s_n)])
    c0, d0, _, _, bl0 = first[0]
    return LPPlan(status=status, battery_kw=d0.solution_value() - c0.solution_value(),
                  backlog_after_kwh=bl0.solution_value(), objective=obj.Value(),
                  stored_energy_value=-float(sum(r.dual_value() for r in soc_rows)),   # rows are in kWh
                  battery_path=wts @ bat, import_path=wts @ imps, solve_ms=ms)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests_energy/test_dispatch_lp.py -q && uv run ruff check --fix optimisation tests_energy`
Expected: `5 passed`. If `test_stored_energy_has_value_before_a_peak` fails because the sign is reversed, GLOP's dual convention differs from the one assumed: change the sign in `stored_energy_value` and note it in a comment (do not weaken the test).

- [ ] **Step 5: Commit**

```bash
git add optimisation/gridlens_opt/dispatch_lp.py tests_energy/test_dispatch_lp.py
git commit -m "Add shared scenario LP for dispatch with DR, deferral deadlines and stored-energy value

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Stochastic MPC and the perfect-information oracle

**Files:**
- Create: `control/gridlens_control/mpc.py`
- Test: `tests_energy/test_mpc.py`

**Interfaces:**
- Consumes: `solve_dispatch_lp`, `LPInput`, `CLASSES` (Task 4); `Observation` with `flex_kw`, `dr_reduction_kw`, `dr_ahead` (Task 1); `QUANTILES`.
- Produces: `sample_paths(q: (N,5), u: (S,)) -> (S,N)`; `StochasticMPC(site, tenants=DEFAULT_TENANTS, scenarios=10, horizon=96, seed=0, assumed_outage_steps=4, time_limit_ms=5000, name="stochastic_mpc")` with `reset()`, `act(obs) -> Action`, `build_input(obs) -> LPInput`, attribute `last_plan: LPPlan | None`; `PerfectInfoOracle(site, env, tenants=DEFAULT_TENANTS, horizon=96)` (name `"oracle"`).

- [ ] **Step 1: Write the failing tests**

`tests_energy/test_mpc.py`:
```python
import numpy as np

from gridlens_control.baselines import NoBattery, RuleTOU
from gridlens_control.mpc import PerfectInfoOracle, StochasticMPC, sample_paths
from gridlens_control.runner import run_episode
from gridlens_sim.disruptions import generate
from gridlens_sim.env import MicrogridEnv
from gridlens_sim.forecast import PerfectForecaster, SeasonalNaiveForecaster
from gridlens_sim.testing import synthetic_series


def test_sample_paths_interpolates_quantiles():
    q = np.tile([1.0, 2.0, 3.0, 4.0, 5.0], (4, 1))
    out = sample_paths(q, np.array([0.1, 0.5, 0.9, 0.0]))
    np.testing.assert_allclose(out[:, 0], [1.0, 3.0, 5.0, 1.0])


def test_mpc_beats_no_battery_on_a_weekday(site):
    s = synthetic_series(site, days=21)
    env = MicrogridEnv(site, s, SeasonalNaiveForecaster(s))
    day = 15 * 96                                     # a weekday with 14 days of history
    mpc = StochasticMPC(site, scenarios=3, horizon=96)
    cost = {c.name: run_episode(env, c, day).kpis()["operating_cost"]
            for c in (NoBattery(), RuleTOU(site), mpc)}
    assert cost["stochastic_mpc"] < cost["no_battery"]
    print("MPC vs rule_tou (reported, not asserted):", cost)   # the comparison is a study result, not a unit test


def test_mpc_is_feasible_and_deterministic_on_a_combined_disruption(site):
    s = synthetic_series(site, days=21)
    env = MicrogridEnv(site, s, SeasonalNaiveForecaster(s))
    sc = generate(4, "combined", site.p_peak_kw)
    a = run_episode(env, StochasticMPC(site, scenarios=3, horizon=32, seed=1), 15 * 96, sc).kpis()
    b = run_episode(env, StochasticMPC(site, scenarios=3, horizon=32, seed=1), 15 * 96, sc).kpis()
    assert a == {**b, "decision_ms_mean": a["decision_ms_mean"]}


def test_oracle_is_at_least_as_cheap_as_mpc(site):
    s = synthetic_series(site, days=7)
    env = MicrogridEnv(site, s, PerfectForecaster(s))
    oracle = run_episode(env, PerfectInfoOracle(site, env, horizon=48), 96).kpis()["total_cost"]
    mpc = run_episode(env, StochasticMPC(site, scenarios=3, horizon=48), 96).kpis()["total_cost"]
    assert oracle <= mpc * 1.01
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests_energy/test_mpc.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `control/gridlens_control/mpc.py`**

```python
"""Stochastic model predictive control and the perfect-information oracle (spec §6.3, §6.4)."""
from __future__ import annotations

import numpy as np

from gridlens_opt.dispatch_lp import CLASSES, LPInput, LPPlan, solve_dispatch_lp
from gridlens_sim.constants import DT_H, QUANTILES
from gridlens_sim.env import Action, Observation
from gridlens_sim.tenants import DEFAULT_TENANTS


def sample_paths(q: np.ndarray, u: np.ndarray) -> np.ndarray:
    """Comonotone paths through the forecast quantiles: scenario s takes quantile level u[s] at every step
    (linear between the stored quantiles, clamped to the outer ones). q: (N, 5) -> (S, N)."""
    qs = np.asarray(QUANTILES)
    u = np.clip(np.asarray(u, dtype=float), qs[0], qs[-1])
    j = np.clip(np.searchsorted(qs, u, side="right") - 1, 0, len(qs) - 2)
    w = (u - qs[j]) / (qs[j + 1] - qs[j])
    return q[:, j].T * (1.0 - w)[:, None] + q[:, j + 1].T * w[:, None]


class StochasticMPC:
    def __init__(self, site, tenants=DEFAULT_TENANTS, scenarios: int = 10, horizon: int = 96, seed: int = 0,
                 assumed_outage_steps: int = 4, time_limit_ms: int = 5000, name: str = "stochastic_mpc"):
        self.site, self.scenarios, self.horizon, self.seed = site, scenarios, horizon, seed
        self.assumed_outage_steps, self.time_limit_ms, self.name = assumed_outage_steps, time_limit_ms, name
        self.flex_share = float(sum(t.share * t.flexible_share for t in tenants))
        self.class_share = {k: float(sum(t.share for t in tenants if t.priority == k)) for k in CLASSES}
        self.reset()

    def reset(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        self.last_plan: LPPlan | None = None

    def _common(self, obs: Observation, n: int) -> dict:
        return {
            "price": np.concatenate([[obs.price], obs.price_ahead[: n - 1]]),
            "dr_reduction": np.concatenate([[obs.dr_reduction_kw], obs.dr_ahead[: n - 1]]),
            "diesel_on": np.tile(np.asarray(obs.diesel_on, dtype=bool), (n, 1)),
            "soc0": obs.soc, "backlog0_kwh": obs.backlog_kwh, "due0_kwh": obs.due_kwh,
            "peak_so_far_kw": obs.peak_import_kw, "flex_share": self.flex_share, "class_share": self.class_share,
            "terminal_value_per_kwh": float(np.median(obs.price_ahead[: n])) * self.site.battery.eta,
        }

    def build_input(self, obs: Observation) -> LPInput:
        n, s_n = self.horizon, self.scenarios
        q_load = np.vstack([np.full((1, len(QUANTILES)), obs.load_kw), obs.forecast[0, : n - 1]])
        q_pv = np.vstack([np.full((1, len(QUANTILES)), obs.pv_kw), obs.forecast[1, : n - 1]])
        strata = (np.arange(s_n) + self.rng.random(s_n)) / s_n
        load = sample_paths(q_load, strata)
        pv = np.clip(sample_paths(q_pv, self.rng.permutation(strata)), 0.0, None)
        grid = np.ones((s_n, n), dtype=bool)
        if not obs.grid_available:
            grid[:, : self.assumed_outage_steps] = False
        return LPInput(load=load, pv=pv, grid_available=grid, weights=np.full(s_n, 1.0 / s_n),
                       **self._common(obs, n))

    def act(self, obs: Observation) -> Action:
        plan = solve_dispatch_lp(self.site, self.build_input(obs), self.time_limit_ms)
        self.last_plan = plan
        if plan.status == "failed":
            return Action(0.0, 0.0)
        deferrable = obs.flex_kw * DT_H + max(obs.backlog_kwh - obs.due_kwh, 0.0)
        defer = float(np.clip(plan.backlog_after_kwh / deferrable, 0.0, 1.0)) if deferrable > 1e-9 else 0.0
        return Action(float(np.clip(plan.battery_kw / self.site.battery.power_kw, -1.0, 1.0)), defer)


class PerfectInfoOracle(StochasticMPC):
    """Bound, not a deployable controller: re-plans every step knowing the realised load, PV, outages and
    demand-response events (one scenario)."""

    def __init__(self, site, env, tenants=DEFAULT_TENANTS, horizon: int = 96, time_limit_ms: int = 5000):
        super().__init__(site, tenants, scenarios=1, horizon=horizon, time_limit_ms=time_limit_ms, name="oracle")
        self.env = env

    def build_input(self, obs: Observation) -> LPInput:
        env, n = self.env, self.horizon
        sc, steps = env.scenario, env.steps
        ks = obs.k + np.arange(n)
        idx = np.minimum(env.start + ks, len(env.series) - 1)
        inday = ks < steps
        load = env.series.load_kw[idx] + np.array(
            [sc.extra_load_kw(int(k)) if d else 0.0 for k, d in zip(ks, inday, strict=True)])
        pv = env.series.pv_kw[idx] * np.array(
            [sc.pv_factor(int(k)) if d else 1.0 for k, d in zip(ks, inday, strict=True)])
        grid = np.array([sc.grid_available(int(k)) if d else True for k, d in zip(ks, inday, strict=True)])
        common = self._common(obs, n)
        common["price"] = env.series.price[idx]
        common["dr_reduction"] = np.array(
            [sc.dr_reduction_kw(int(k)) if d else 0.0 for k, d in zip(ks, inday, strict=True)])
        return LPInput(load=load[None, :], pv=pv[None, :], grid_available=grid[None, :], weights=np.ones(1),
                       **common)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests_energy/test_mpc.py -q && uv run ruff check --fix control tests_energy`
Expected: `4 passed` (the MPC tests take tens of seconds). If `test_mpc_beats_no_battery_and_rule_on_a_weekday` fails, use superpowers:systematic-debugging: print per-step `plan.battery_kw`, price band and SoC for the day before changing the model.

- [ ] **Step 5: Commit**

```bash
git add control/gridlens_control/mpc.py tests_energy/test_mpc.py
git commit -m "Add stochastic MPC with quantile scenarios and the perfect-information oracle

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Day-ahead unit commitment and runner hook

**Files:**
- Create: `optimisation/gridlens_opt/unit_commitment.py`, `control/gridlens_control/commitment.py`
- Modify: `control/gridlens_control/runner.py` (`summarise` gains `commitment_fn`)
- Test: `tests_energy/test_unit_commitment.py`

**Interfaces:**
- Produces: `Commitment(on: (N,U) bool, starts: int, objective: float, status: str, solve_ms: float)`; `commit_day(site, net_q50, net_q90, price, *, islanding_risk=None, time_limit_s=10.0) -> Commitment`; `day_ahead(site, forecaster, series, day_start, islanding_risk=None) -> Commitment`; `uc_commitment_fn(site, forecaster, series, alert_on_blackout=False) -> Callable[[int, Scenario], np.ndarray]`; `summarise(env, controllers, day_starts, regimes, seeds, commitment_fn=None)`.

- [ ] **Step 1: Write the failing tests**

`tests_energy/test_unit_commitment.py`:
```python
import numpy as np

from gridlens_opt.unit_commitment import commit_day

N = 96


def test_no_units_when_the_grid_covers_everything(site):
    c = commit_day(site, np.full(N, 500.0), np.full(N, 600.0), np.full(N, 100.0))
    assert c.status in ("optimal", "feasible") and not c.on.any()


def test_units_cover_demand_beyond_grid_and_battery(site):
    net90 = np.full(N, 600.0)
    net90[40:48] = site.grid.import_limit_kw + site.battery.power_kw + 200.0
    c = commit_day(site, np.full(N, 500.0), net90, np.full(N, 100.0))
    assert c.on[40:48].any(axis=1).all()


def test_islanding_risk_holds_reserve_and_respects_minimum_up_time(site):
    risk = np.zeros(N, bool)
    risk[72:80] = True
    c = commit_day(site, np.full(N, 600.0), np.full(N, 700.0), np.full(N, 100.0), islanding_risk=risk)
    cap = c.on.astype(float) @ np.array([d.p_max_kw for d in site.diesels])
    assert (cap[72:80] >= 700.0 - site.battery.power_kw - 1e-6).all()
    for u, spec in enumerate(site.diesels):
        on = c.on[:, u]
        starts = [h for h in range(1, N) if on[h] and not on[h - 1]]
        for h in starts:
            assert on[h:h + spec.min_up_steps].all() or h + spec.min_up_steps > N
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests_energy/test_unit_commitment.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `optimisation/gridlens_opt/unit_commitment.py`**

```python
"""Day-ahead diesel unit commitment (spec §6.1): a MILP over 96 quarter-hours solved with SCIP.

Binary on/start/stop per unit, minimum up/down times, minimum load, start-up and fuel cost, grid import cost, and two
adequacy rows: the median net demand must be met by grid + diesel + battery power; the 90th-percentile net demand
needs capacity from grid + online diesel + battery, or, in hours with an islanding risk (for example a storm warning),
from online diesel + battery alone. A slack with a very high cost keeps the model feasible and is reported.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from ortools.linear_solver import pywraplp

from gridlens_sim.constants import DT_H

SHORT_COST = 1e7


@dataclass(frozen=True)
class Commitment:
    on: np.ndarray
    starts: int
    objective: float
    status: str
    solve_ms: float


def commit_day(site, net_q50, net_q90, price, *, islanding_risk=None, time_limit_s: float = 10.0) -> Commitment:
    t0 = time.perf_counter()
    n = len(net_q50)
    units, b, g, dt = site.diesels, site.battery, site.grid, DT_H
    risk = np.zeros(n, dtype=bool) if islanding_risk is None else np.asarray(islanding_risk, dtype=bool)
    solver = pywraplp.Solver.CreateSolver("SCIP")
    solver.SetTimeLimit(int(time_limit_s * 1000))
    on = [[solver.BoolVar(f"on{u}_{h}") for h in range(n)] for u in range(len(units))]
    st = [[solver.BoolVar(f"st{u}_{h}") for h in range(n)] for u in range(len(units))]
    sd = [[solver.BoolVar(f"sd{u}_{h}") for h in range(n)] for u in range(len(units))]
    dg = [[solver.NumVar(0, spec.p_max_kw, f"dg{u}_{h}") for h in range(n)] for u, spec in enumerate(units)]
    imp = [solver.NumVar(0, g.import_limit_kw, f"imp{h}") for h in range(n)]
    short = [solver.NumVar(0, solver.infinity(), f"short{h}") for h in range(n)]
    terms = []
    carbon = site.carbon_price_per_kg
    for u, spec in enumerate(units):
        for h in range(n):
            prev = on[u][h - 1] if h else 0
            solver.Add(on[u][h] - prev == st[u][h] - sd[u][h])
            solver.Add(dg[u][h] >= spec.p_min_kw * on[u][h])
            solver.Add(dg[u][h] <= spec.p_max_kw * on[u][h])
            solver.Add(solver.Sum(st[u][max(0, h - spec.min_up_steps + 1): h + 1]) <= on[u][h])
            solver.Add(solver.Sum(sd[u][max(0, h - spec.min_down_steps + 1): h + 1]) <= 1 - on[u][h])
            per_l = spec.fuel_price_per_l + carbon * spec.co2_kg_per_l
            terms += [spec.fuel_a_l_per_kwh * per_l * dt * dg[u][h],
                      spec.fuel_b_l_per_kwh_rated * spec.p_max_kw * per_l * dt * on[u][h],
                      spec.startup_cost * st[u][h]]
    for h in range(n):
        online = solver.Sum(spec.p_max_kw * on[u][h] for u, spec in enumerate(units))
        solver.Add(imp[h] + solver.Sum(dg[u][h] for u in range(len(units))) + short[h]
                   >= float(net_q50[h]) - b.power_kw)
        if risk[h]:
            solver.Add(online + short[h] >= max(0.0, float(net_q90[h]) - b.power_kw))
        else:
            solver.Add(online + g.import_limit_kw + b.power_kw + short[h] >= float(net_q90[h]))
        terms += [(float(price[h]) + carbon * g.co2_kg_per_kwh) * dt * imp[h], SHORT_COST * short[h]]
    solver.Minimize(solver.Sum(terms))
    code = solver.Solve()
    ms = (time.perf_counter() - t0) * 1000.0
    status = {pywraplp.Solver.OPTIMAL: "optimal", pywraplp.Solver.FEASIBLE: "feasible"}.get(code, "failed")
    if status == "failed":
        return Commitment(np.zeros((n, len(units)), dtype=bool), 0, float("nan"), status, ms)
    on_arr = np.array([[on[u][h].solution_value() > 0.5 for u in range(len(units))] for h in range(n)])
    starts = int(sum(st[u][h].solution_value() > 0.5 for u in range(len(units)) for h in range(n)))
    return Commitment(on_arr, starts, solver.Objective().Value(), status, ms)
```

- [ ] **Step 4: Write `control/gridlens_control/commitment.py` and the runner hook**

```python
"""Day-ahead unit commitment for the runner: forecasts issued at the end of the previous day."""
from __future__ import annotations

import numpy as np

from gridlens_opt.unit_commitment import Commitment, commit_day
from gridlens_sim.constants import DAY


def day_ahead(site, forecaster, series, day_start: int, islanding_risk=None) -> Commitment:
    fc = forecaster.forecast(max(day_start - 1, 0))
    net50 = fc[0, :, 2] - fc[1, :, 2]
    net90 = fc[0, :, 4] - fc[1, :, 0]
    price = series.price[np.minimum(np.arange(day_start, day_start + DAY), len(series) - 1)]
    return commit_day(site, net50, net90, price, islanding_risk=islanding_risk)


def uc_commitment_fn(site, forecaster, series, alert_on_blackout: bool = False):
    """When `alert_on_blackout` is set, a day with a scheduled blackout carries an islanding warning for 07:00-24:00
    (a storm warning known the day before); otherwise UC plans without outage knowledge."""
    def fn(day_start: int, scenario) -> np.ndarray:
        risk = None
        if alert_on_blackout and any(e.kind == "blackout" for e in scenario.events):
            risk = np.arange(DAY) >= 28
        return day_ahead(site, forecaster, series, day_start, risk).on
    return fn
```
In `runner.py`, give `summarise` the keyword `commitment_fn=None`, and inside the scenario loop compute
`commitment = commitment_fn(ds, scenario) if commitment_fn else None` once per scenario, passing
`commitment=commitment` to `run_episode`.

- [ ] **Step 5: Run tests and commit**

```bash
uv run pytest tests_energy -q && uv run ruff check --fix optimisation control tests_energy
git add optimisation/gridlens_opt/unit_commitment.py control/gridlens_control/commitment.py control/gridlens_control/runner.py tests_energy/test_unit_commitment.py
git commit -m "Add day-ahead diesel unit commitment MILP with islanding reserve and runner hook

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Cached LightGBM forecasts

**Files:**
- Modify: `sim/gridlens_sim/forecast.py` (add `CachedForecaster`)
- Create: `scripts/cache_forecasts.py`
- Test: `tests_energy/test_cached_forecaster.py`

**Interfaces:**
- Produces: `CachedForecaster(path, fallback)` implementing `forecast(t)`; cache file `data/silver/energy/forecasts_<site>.npz` with `positions (n,) int64` and `values (n, 2, 96, 5) float32`.

- [ ] **Step 1: Write the failing test**

`tests_energy/test_cached_forecaster.py`:
```python
import numpy as np

from gridlens_sim.forecast import CachedForecaster, PerfectForecaster
from gridlens_sim.testing import synthetic_series


def test_cache_hit_and_fallback(site, tmp_path):
    s = synthetic_series(site, days=3)
    vals = np.ones((2, 2, 96, 5), dtype=np.float32)
    np.savez(tmp_path / "f.npz", positions=np.array([10, 11]), values=vals)
    f = CachedForecaster(tmp_path / "f.npz", PerfectForecaster(s))
    assert (f.forecast(10) == 1.0).all()
    np.testing.assert_allclose(f.forecast(12), PerfectForecaster(s).forecast(12))
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests_energy/test_cached_forecaster.py -q`
Expected: FAIL with `ImportError: cannot import name 'CachedForecaster'`.

- [ ] **Step 3: Add `CachedForecaster` to `sim/gridlens_sim/forecast.py`**

```python
class CachedForecaster:
    """Pre-computed forecasts (written by scripts/cache_forecasts.py) with a fallback for positions not cached.
    Lets controllers use LightGBM forecasts without loading LightGBM (and its OpenMP runtime) in the process."""

    def __init__(self, path, fallback: Forecaster):
        z = np.load(path)
        self.index = {int(p): i for i, p in enumerate(z["positions"])}
        self.values = z["values"]
        self.fallback = fallback

    def forecast(self, t: int) -> np.ndarray:
        i = self.index.get(int(t))
        return self.values[i].astype(float) if i is not None else self.fallback.forecast(t)
```

- [ ] **Step 4: Write `scripts/cache_forecasts.py`**

```python
"""Train the GF1 LightGBM models on 2018-01-08..09-30 and cache their forecasts for every position from
2018-09-30 23:45 to the end of the data (validation and test), for one site.

    uv run python scripts/cache_forecasts.py [--site kr_gwangyang] [--rounds 300]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from gridlens_ml.energy_forecast import H, WEEK, LGBMForecaster, train_quantile_models
from gridlens_sim.factory import load_park

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", default="kr_gwangyang")
    ap.add_argument("--rounds", type=int, default=300)
    args = ap.parse_args()
    park = load_park(args.site)
    s, w = park.series, park.weather
    load_exog = w[["temperature_2m"]].to_numpy()
    pv_exog = w[["ghi", "temperature_2m", "cloud_cover"]].to_numpy()
    a = s.day_starts("2018-01-08", "2018-01-08")[0]
    b = s.day_starts("2018-09-30", "2018-09-30")[0] + 95
    train = [t for t in range(max(a, WEEK), b + 1, 8) if t + H < len(s)]
    f = LGBMForecaster(train_quantile_models(s.load_kw, s.index, load_exog, train, rounds=args.rounds),
                       train_quantile_models(s.pv_kw, s.index, pv_exog, train, rounds=args.rounds),
                       s.load_kw, s.pv_kw, s.index, load_exog, pv_exog, daylight=w["ghi"].to_numpy() > 0)
    positions = np.arange(s.day_starts("2018-10-01", "2018-10-01")[0] - 1, len(s) - 1)
    values = np.stack([f.forecast(int(t)) for t in positions]).astype(np.float32)
    out = ROOT / "data" / "silver" / "energy" / f"forecasts_{args.site}.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, positions=positions, values=values)
    print(out, values.shape)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the test; run the script on real data**

```bash
uv run pytest tests_energy/test_cached_forecaster.py -q
uv run python scripts/cache_forecasts.py --site kr_gwangyang
uv run python scripts/cache_forecasts.py --site ae_industrial
```
Expected: test passes; each script prints the cache path and `(8833, 2, 96, 5)` (positions from 2018-09-30 23:45 to 2018-12-31 23:30).

- [ ] **Step 6: Commit**

```bash
git add sim/gridlens_sim/forecast.py scripts/cache_forecasts.py tests_energy/test_cached_forecaster.py
git commit -m "Add cached LightGBM forecasts for controllers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: NumPy policy serving and SB3 export

**Files:**
- Create: `control/gridlens_control/policy.py`, `control/gridlens_control/rl.py`, `tests_energy/rl_export_child.py`
- Modify: `pyproject.toml` (`uv add stable-baselines3`)
- Test: `tests_energy/test_rl_export.py`

**Interfaces:**
- Produces: `NumpyPolicy.load(path, expected_sha256=None) -> NumpyPolicy` (callable `(OBS_DIM,) -> (2,)`, attributes `price_scale`, `meta`); `RLController(policy, site, name)`; `export_sb3(model, algo, path, price_scale, meta) -> str` (sha256); `file_sha256(path) -> str`.

- [ ] **Step 1: Add the dependency**

Run: `uv add stable-baselines3` then `chflags nohidden .venv/lib/python3.12/site-packages/*.pth`.

- [ ] **Step 2: Write `control/gridlens_control/policy.py`**

```python
"""Serve exported RL actors with NumPy only (no PyTorch in the API). Files are hash-verified before use."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np

from gridlens_sim.env import Action, Observation, obs_vector


def file_sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class NumpyPolicy:
    def __init__(self, layers, head, activation: str, squash: bool, low, high, price_scale: float, meta: dict):
        self.layers, self.head, self.activation, self.squash = layers, head, activation, squash
        self.low, self.high, self.price_scale, self.meta = np.asarray(low), np.asarray(high), price_scale, meta

    @classmethod
    def load(cls, path, expected_sha256: str | None = None) -> NumpyPolicy:
        data = Path(path).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise ValueError(f"policy file {path} has sha256 {digest}, expected {expected_sha256}")
        z = np.load(io.BytesIO(data), allow_pickle=False)
        n = int(z["n_layers"])
        return cls([(z[f"W{i}"], z[f"b{i}"]) for i in range(n)], (z["Wh"], z["bh"]), str(z["activation"]),
                   bool(z["squash"]), z["low"], z["high"], float(z["price_scale"]), json.loads(str(z["meta"])))

    def __call__(self, x) -> np.ndarray:
        h = np.asarray(x, dtype=np.float64)
        for w, b in self.layers:
            h = w @ h + b
            h = np.tanh(h) if self.activation == "tanh" else np.maximum(h, 0.0)
        a = self.head[0] @ h + self.head[1]
        if self.squash:
            return self.low + (np.tanh(a) + 1.0) * 0.5 * (self.high - self.low)
        return np.clip(a, self.low, self.high)


class RLController:
    def __init__(self, policy: NumpyPolicy, site, name: str):
        self.policy, self.site, self.name = policy, site, name

    def reset(self) -> None:
        pass

    def act(self, obs: Observation) -> Action:
        a = self.policy(obs_vector(obs, self.site, self.policy.price_scale))
        return Action(float(np.clip(a[0], -1.0, 1.0)), float(np.clip(a[1], 0.0, 1.0)))
```

- [ ] **Step 3: Write `control/gridlens_control/rl.py` (export part)**

```python
"""Reinforcement learning with stable-baselines3 (PPO, SAC). Imports PyTorch: never import this module in a process
that has loaded LightGBM."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .policy import file_sha256


def export_sb3(model, algo: str, path, price_scale: float, meta: dict) -> str:
    from torch import nn
    if algo == "ppo":
        if model.policy.activation_fn is not nn.Tanh:
            raise ValueError("PPO export expects Tanh activations")
        seq, head, activation, squash = model.policy.mlp_extractor.policy_net, model.policy.action_net, "tanh", False
    elif algo == "sac":
        seq, head, activation, squash = model.policy.actor.latent_pi, model.policy.actor.mu, "relu", True
    else:
        raise ValueError(f"unknown algorithm {algo}")
    linears = [m for m in seq if isinstance(m, nn.Linear)]

    def arr(t):
        return t.detach().cpu().numpy().astype(np.float64)

    arrays = {}
    for i, m in enumerate(linears):
        arrays[f"W{i}"], arrays[f"b{i}"] = arr(m.weight), arr(m.bias)
    space = model.action_space
    path = Path(path)
    np.savez(path, n_layers=len(linears), Wh=arr(head.weight), bh=arr(head.bias), activation=np.array(activation),
             squash=np.array(squash), low=space.low.astype(np.float64), high=space.high.astype(np.float64),
             price_scale=np.array(price_scale), meta=np.array(json.dumps(meta)), **arrays)
    return file_sha256(path)
```

- [ ] **Step 4: Write the child script and the test**

`tests_energy/rl_export_child.py` (runs in its own process because PyTorch and LightGBM must not share one):
```python
"""Child process for test_rl_export: tiny PPO and SAC runs, export, compare NumPy and PyTorch actions."""
import json
import sys
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO, SAC

from gridlens_control.policy import NumpyPolicy
from gridlens_control.rl import export_sb3
from gridlens_sim.config import load_site
from gridlens_sim.env import MicrogridEnv
from gridlens_sim.forecast import PerfectForecaster
from gridlens_sim.testing import synthetic_series

out = Path(sys.argv[1])
site = load_site("kr_gwangyang", p_peak_kw=1000.0)
s = synthetic_series(site, days=7)
env = MicrogridEnv(site, s, PerfectForecaster(s))
result = {}
for algo, model in (
    ("ppo", PPO("MlpPolicy", env, seed=0, n_steps=128, batch_size=64, verbose=0,
                policy_kwargs={"net_arch": {"pi": [32, 32], "vf": [32, 32]}})),
    ("sac", SAC("MlpPolicy", env, seed=0, learning_starts=32, batch_size=32, verbose=0,
                policy_kwargs={"net_arch": [32, 32]})),
):
    model.learn(256)
    path = out / f"{algo}.npz"
    export_sb3(model, algo, path, env.price_scale, {"algo": algo})
    pol = NumpyPolicy.load(path)
    obs, _ = env.reset(seed=1)
    diffs = []
    for _ in range(20):
        torch_a, _ = model.predict(obs, deterministic=True)
        diffs.append(float(np.max(np.abs(torch_a - pol(obs)))))
        obs, _, term, _, _ = env.step(torch_a)
        if term:
            obs, _ = env.reset()
    result[algo] = max(diffs)
print(json.dumps(result))
```

`tests_energy/test_rl_export.py`:
```python
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gridlens_control.policy import NumpyPolicy


def test_numpy_policy_matches_pytorch(tmp_path):
    child = Path(__file__).with_name("rl_export_child.py")
    done = subprocess.run([sys.executable, str(child), str(tmp_path)], capture_output=True,  # noqa: S603
                          text=True, timeout=600, check=True)
    diffs = json.loads(done.stdout.strip().splitlines()[-1])
    assert diffs["ppo"] < 1e-5 and diffs["sac"] < 1e-5


def test_policy_hash_is_checked(tmp_path):
    child = Path(__file__).with_name("rl_export_child.py")
    subprocess.run([sys.executable, str(child), str(tmp_path)], capture_output=True, timeout=600,  # noqa: S603
                   check=True)
    with pytest.raises(ValueError, match="sha256"):
        NumpyPolicy.load(tmp_path / "ppo.npz", expected_sha256="0" * 64)
```

- [ ] **Step 5: Run tests and commit**

```bash
uv run pytest tests_energy/test_rl_export.py -q && uv run ruff check --fix control tests_energy
git add pyproject.toml uv.lock control/gridlens_control/policy.py control/gridlens_control/rl.py tests_energy/rl_export_child.py tests_energy/test_rl_export.py
git commit -m "Add SB3 actor export and hash-verified NumPy policy serving

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected: `2 passed`.

---

### Task 9: PPO and SAC training with validation-based selection and optional warm start

**Files:**
- Modify: `control/gridlens_control/rl.py` (add `train`, `behaviour_clone`)
- Create: `scripts/train_rl.py`

**Interfaces:**
- Consumes: `mixed_sampler` (Task 1), `export_sb3`, `NumpyPolicy`, `RLController` (Task 8), `run_episode` (Plan 2), `load_park`, `SeasonalNaiveForecaster`.
- Produces: `models/rl/<site>/<algo>_seed<n>.npz` and `.json` (sha256, validation history, best step count, price scale); `train(algo, park, *, seed, total_steps, eval_every, train_days, val_days, out_dir, warm_start=False, p_disrupted=0.5) -> dict`.

- [ ] **Step 1: Add training to `control/gridlens_control/rl.py`**

```python
def behaviour_clone(model, algo: str, park, day_starts, epochs: int = 20) -> float:
    """Pre-train the actor to imitate the rule-based TOU baseline on normal days (spec §14 risk mitigation).
    Returns the final mean squared error."""
    import torch

    from gridlens_sim.env import MicrogridEnv, obs_vector
    from gridlens_sim.forecast import SeasonalNaiveForecaster

    from .baselines import RuleTOU
    env = MicrogridEnv(park.site, park.series, SeasonalNaiveForecaster(park.series))
    rule = RuleTOU(park.site)
    xs, ys = [], []
    for ds in day_starts:
        _, info = env.reset(options={"day_start": ds})
        obs = info["observation"]
        while True:
            a = rule.act(obs)
            xs.append(obs_vector(obs, park.site, env.price_scale))
            ys.append([a.battery, a.defer])
            _, _, term, _, info = env.step_action(a)
            obs = info["observation"]
            if term:
                break
    x = torch.tensor(np.array(xs), dtype=torch.float32)
    y = torch.tensor(np.array(ys), dtype=torch.float32)
    low = torch.tensor(model.action_space.low)
    high = torch.tensor(model.action_space.high)
    if algo == "ppo":
        params = list(model.policy.mlp_extractor.policy_net.parameters()) + list(model.policy.action_net.parameters())

        def predict(v):
            return model.policy.action_net(model.policy.mlp_extractor.policy_net(v))
        target = y
    else:
        params = list(model.policy.actor.latent_pi.parameters()) + list(model.policy.actor.mu.parameters())

        def predict(v):
            return torch.tanh(model.policy.actor.mu(model.policy.actor.latent_pi(v)))
        target = 2.0 * (y - low) / (high - low) - 1.0
    opt = torch.optim.Adam(params, lr=1e-3)
    loss = torch.tensor(0.0)
    for _ in range(epochs):
        perm = torch.randperm(len(x))
        for i in range(0, len(x), 256):
            idx = perm[i:i + 256]
            opt.zero_grad()
            loss = torch.mean((predict(x[idx]) - target[idx]) ** 2)
            loss.backward()
            opt.step()
    return float(loss)


def train(algo: str, park, *, seed: int, total_steps: int, eval_every: int, train_days, val_days, out_dir,
          warm_start: bool = False, p_disrupted: float = 0.5) -> dict:
    from stable_baselines3 import PPO, SAC
    from stable_baselines3.common.monitor import Monitor

    from gridlens_sim.disruptions import generate, mixed_sampler
    from gridlens_sim.env import MicrogridEnv
    from gridlens_sim.forecast import SeasonalNaiveForecaster

    from .policy import NumpyPolicy, RLController
    from .runner import run_episode
    site, s = park.site, park.series
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    forecaster = SeasonalNaiveForecaster(s)
    env = Monitor(MicrogridEnv(site, s, forecaster, day_starts=train_days,
                               scenario_sampler=mixed_sampler(site.p_peak_kw, p_disrupted)))
    if algo == "ppo":
        model = PPO("MlpPolicy", env, seed=seed, n_steps=2048, batch_size=256, gamma=0.995, learning_rate=3e-4,
                    policy_kwargs={"net_arch": {"pi": [64, 64], "vf": [64, 64]}}, verbose=0)
    else:
        model = SAC("MlpPolicy", env, seed=seed, buffer_size=200_000, learning_starts=5_000, batch_size=256,
                    gamma=0.995, learning_rate=3e-4, policy_kwargs={"net_arch": [64, 64]}, verbose=0)
    bc_loss = behaviour_clone(model, algo, park, train_days[:20]) if warm_start else None
    price_scale = env.unwrapped.price_scale
    eval_env = MicrogridEnv(site, s, forecaster)
    val = [(d, generate(10_000 + i, regime, site.p_peak_kw))
           for i, d in enumerate(val_days) for regime in ("normal", "combined")]
    meta = {"algo": algo, "seed": seed, "site": site.id, "warm_start": warm_start, "forecaster": "seasonal_naive"}
    final = out_dir / f"{algo}_seed{seed}.npz"
    tmp = out_dir / f"{algo}_seed{seed}.candidate.npz"
    best_cost, best_steps, history, done = float("inf"), 0, [], 0
    while done < total_steps:
        model.learn(eval_every, reset_num_timesteps=False)
        done += eval_every
        export_sb3(model, algo, tmp, price_scale, {**meta, "steps": done})
        ctrl = RLController(NumpyPolicy.load(tmp), site, algo)
        cost = float(np.mean([run_episode(eval_env, ctrl, d, sc).kpis()["total_cost"] for d, sc in val]))
        history.append({"steps": done, "val_total_cost": cost})
        if cost < best_cost:
            best_cost, best_steps = cost, done
            tmp.replace(final)
    tmp.unlink(missing_ok=True)
    record = {**meta, "best_steps": best_steps, "val_total_cost": best_cost, "history": history,
              "behaviour_clone_mse": bc_loss, "price_scale": price_scale, "sha256": file_sha256(final)}
    final.with_suffix(".json").write_text(json.dumps(record, indent=2) + "\n")
    return record
```

- [ ] **Step 2: Write `scripts/train_rl.py`**

```python
"""Train PPO or SAC on MicrogridEnv (Jan 8 - Sep 30 days, normal and disrupted), select on October days.

    uv run python scripts/train_rl.py --algo ppo --seed 0 [--steps 300000] [--eval-every 25000] [--warm-start]
Writes models/rl/<site>/<algo>_seed<seed>.npz and .json (git-ignored). Do not import LightGBM in this process.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gridlens_control.rl import train
from gridlens_sim.factory import load_park

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--algo", choices=["ppo", "sac"], required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--site", default="kr_gwangyang")
    ap.add_argument("--steps", type=int, default=300_000)
    ap.add_argument("--eval-every", type=int, default=25_000)
    ap.add_argument("--warm-start", action="store_true")
    args = ap.parse_args()
    park = load_park(args.site)
    s = park.series
    record = train(args.algo, park, seed=args.seed, total_steps=args.steps, eval_every=args.eval_every,
                   train_days=s.day_starts("2018-01-08", "2018-09-30"),
                   val_days=s.day_starts("2018-10-01", "2018-10-31")[::3],
                   out_dir=ROOT / "models" / "rl" / args.site, warm_start=args.warm_start)
    print(json.dumps({k: v for k, v in record.items() if k != "history"}, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Smoke-run, then the full training set (owner's machine; long-running, run in the background)**

```bash
uv run python scripts/train_rl.py --algo ppo --seed 0 --steps 4096 --eval-every 2048
for algo in ppo sac; do for seed in 0 1 2 3 4; do
  uv run python scripts/train_rl.py --algo $algo --seed $seed
done; done
uv run python scripts/train_rl.py --algo ppo --seed 0 --warm-start
```
Expected: the smoke run prints a record with two history points; each full run writes `models/rl/kr_gwangyang/<algo>_seed<n>.npz/.json`. Record wall time per run in the `.json` (`history` timestamps are not needed).

- [ ] **Step 4: Commit**

```bash
uv run pytest tests_energy -q && uv run ruff check --fix control scripts
git add control/gridlens_control/rl.py scripts/train_rl.py
git commit -m "Add PPO/SAC training with validation selection and rule-based warm start

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Plain-language decision explanations

**Files:**
- Create: `control/gridlens_control/explain.py`
- Test: `tests_energy/test_explain.py`

**Interfaces:**
- Consumes: `StepRecord` (with Tasks 1–2 fields), `Site`, `Tenant`, optional `LPPlan`.
- Produces: `explain_step(rec, site, tenants=DEFAULT_TENANTS, plan=None) -> list[str]` — every sentence states a measured value from the record (or plan) and the rule or cost that produced it.

- [ ] **Step 1: Write the failing tests**

`tests_energy/test_explain.py`:
```python
import numpy as np

from gridlens_control.explain import explain_step
from gridlens_sim.disruptions import Event, Scenario
from gridlens_sim.env import MicrogridEnv
from gridlens_sim.forecast import PerfectForecaster
from gridlens_sim.testing import synthetic_series


def records(site, scenario, discharge_at=None, soc=0.5):
    s = synthetic_series(site, days=3)
    env = MicrogridEnv(site, s, PerfectForecaster(s))
    env.reset(options={"day_start": 96, "scenario": scenario, "soc": soc})
    return [env.step(np.array([1.0 if k == discharge_at else 0.0, 0.0], dtype=np.float32))[4]["record"]
            for k in range(96)]


def test_blackout_explanation_names_islanding_ufls_and_tenants(site):
    sc = Scenario(seed=0, regime="blackout", events=(Event("blackout", 72, 16, 0.0),))
    text = " ".join(explain_step(records(site, sc)[72], site))
    assert "islanded" in text and "UFLS stage" in text and "Coil packaging" in text


def test_peak_discharge_explanation_quotes_price_and_band(site):
    from gridlens_sim.disruptions import NORMAL
    rec = records(site, NORMAL, discharge_at=40, soc=0.9)[40]        # 10:00, winter peak band
    text = " ".join(explain_step(rec, site))
    assert "discharged" in text and "peak band" in text and f"{rec.price:.1f}" in text
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests_energy/test_explain.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `control/gridlens_control/explain.py`**

```python
"""Plain-language explanation of one 15-minute decision (spec §9.2 algorithmic transparency).

Sentences are built only from recorded values; nothing is generated by a language model.
"""
from __future__ import annotations

from gridlens_sim.tenants import DEFAULT_TENANTS


def explain_step(rec, site, tenants=DEFAULT_TENANTS, plan=None) -> list[str]:
    cur = site.currency
    out: list[str] = []
    when = rec.timestamp[11:16]
    if not rec.grid_available:
        out.append(f"{when}: the grid was unavailable, so the park islanded and ran on battery, solar"
                   f"{' and diesel' if rec.diesel_on else ''}.")
    if rec.battery_kw > 1e-6:
        out.append(f"The battery discharged {rec.battery_kw:.0f} kW in the {rec.band} band at "
                   f"{rec.price:.1f} {cur}/kWh, ending at {rec.soc:.0%} charge.")
    elif rec.battery_kw < -1e-6:
        out.append(f"The battery charged {-rec.battery_kw:.0f} kW in the {rec.band} band at "
                   f"{rec.price:.1f} {cur}/kWh, ending at {rec.soc:.0%} charge.")
    if plan is not None and plan.status != "failed":
        out.append(f"The optimiser valued stored energy at {plan.stored_energy_value:.1f} {cur}/kWh against a "
                   f"current price of {rec.price:.1f} {cur}/kWh.")
    if rec.stages_tripped:
        stages = ", ".join(str(i + 1) for i in rec.stages_tripped)
        out.append(f"Frequency fell to {rec.nadir_hz:.2f} Hz and UFLS stage {stages} tripped automatically.")
    shed = [(t.name, kw) for t, kw in zip(tenants, rec.shed_by_tenant, strict=True) if kw > 1e-6]
    if shed:
        names = "; ".join(f"{n} {kw:.0f} kW" for n, kw in shed)
        out.append(f"Load was shed by the published priority order (flexible, then essential, then critical, "
                   f"rotating within a class): {names}.")
    if rec.dr_cost != 0:
        if rec.dr_shortfall_kw > 1e-6:
            out.append(f"A demand-response event was missed by {rec.dr_shortfall_kw:.0f} kW "
                       f"(cost {rec.dr_cost:.1f} {cur}).")
        else:
            out.append(f"A demand-response commitment was met (credit {-rec.dr_cost:.1f} {cur}).")
    if rec.deferred_kwh > 1e-6:
        out.append(f"{rec.deferred_kwh:.0f} kWh of flexible machine load was postponed (served within 4 hours).")
    if rec.q_battery_kvar > 1e-6:
        out.append(f"The battery inverter supplied {rec.q_battery_kvar:.0f} kVAr, keeping the power factor at "
                   f"{rec.power_factor:.2f}.")
    out += [f"Safety layer: {c}." for c in rec.corrections if not c.startswith("UFLS")]
    return out or [f"{when}: no action needed; the grid supplied {rec.grid_import_kw:.0f} kW."]
```

- [ ] **Step 4: Run tests and commit**

```bash
uv run pytest tests_energy/test_explain.py -q && uv run ruff check --fix control tests_energy
git add control/gridlens_control/explain.py tests_energy/test_explain.py
git commit -m "Add plain-language decision explanations built from recorded values

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Controller comparison on real data

**Files:**
- Create: `scripts/compare_controllers.py` (replaces `scripts/run_baselines.py`; delete that file)
- Modify: `PROJECT_STATUS.md`

**Interfaces:**
- Consumes: everything above. Two process modes: `--forecaster naive` (default) or `--forecaster lgbm` (cache from Task 7; LightGBM is not imported).

- [ ] **Step 1: Write the script**

```python
"""Compare every controller on the real test period (exploratory; the formal benchmark is MB1 in Plan 5).

    uv run python scripts/compare_controllers.py [--site kr_gwangyang] [--days 10] [--seeds 1]
        [--forecaster naive|lgbm] [--uc] [--alert] [--mpc-scenarios 5] [--mpc-horizon 48] [--no-oracle]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gridlens_control.baselines import GreedySelf, NoBattery, RuleTOU
from gridlens_control.commitment import uc_commitment_fn
from gridlens_control.mpc import PerfectInfoOracle, StochasticMPC
from gridlens_control.policy import NumpyPolicy, RLController
from gridlens_control.runner import summarise
from gridlens_sim.env import MicrogridEnv
from gridlens_sim.factory import load_park
from gridlens_sim.forecast import CachedForecaster, SeasonalNaiveForecaster

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = ["operating_cost", "total_cost", "peak_import_kw", "co2_kg", "unserved_kwh", "critical_served_pct",
           "min_nadir_hz", "dr_shortfall_kwh", "mean_power_factor", "capacity_fade_pct", "decision_ms_mean"]


def rl_controllers(site):
    out = []
    for meta_path in sorted((ROOT / "models" / "rl" / site.id).glob("*_seed*.json")):
        meta = json.loads(meta_path.read_text())
        pol = NumpyPolicy.load(meta_path.with_suffix(".npz"), expected_sha256=meta["sha256"])
        out.append(RLController(pol, site, f"{meta['algo']}_s{meta['seed']}"))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", default="kr_gwangyang")
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--forecaster", choices=["naive", "lgbm"], default="naive")
    ap.add_argument("--uc", action="store_true")
    ap.add_argument("--alert", action="store_true")
    ap.add_argument("--mpc-scenarios", type=int, default=5)
    ap.add_argument("--mpc-horizon", type=int, default=48)
    ap.add_argument("--no-oracle", action="store_true")
    args = ap.parse_args()
    park = load_park(args.site)
    site, s = park.site, park.series
    fc = SeasonalNaiveForecaster(s)
    if args.forecaster == "lgbm":
        fc = CachedForecaster(ROOT / "data" / "silver" / "energy" / f"forecasts_{site.id}.npz", fc)
    env = MicrogridEnv(site, s, fc)
    controllers = [NoBattery(), RuleTOU(site), GreedySelf(site),
                   StochasticMPC(site, scenarios=args.mpc_scenarios, horizon=args.mpc_horizon), *rl_controllers(site)]
    if not args.no_oracle:
        controllers.append(PerfectInfoOracle(site, env, horizon=args.mpc_horizon))
    days = s.day_starts("2018-11-01", "2018-12-31")[: args.days]
    cfn = uc_commitment_fn(site, fc, s, alert_on_blackout=args.alert) if args.uc else None
    df = summarise(env, controllers, days, ["normal", "blackout", "cloud_drop", "machine_start", "combined",
                                            "dr_event"], list(range(args.seeds)), commitment_fn=cfn)
    print(f"{site.name} · {len(days)} days · forecaster {args.forecaster} · UC {args.uc} · simulated")
    print(df.groupby(["regime", "controller"])[COLUMNS].mean().round(3).to_string())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

```bash
git rm scripts/run_baselines.py
uv run python scripts/compare_controllers.py --days 2 --no-oracle
uv run python scripts/compare_controllers.py --days 10 --forecaster lgbm --uc --alert
```
Expected: one table row per regime × controller. Sanity checks before moving on: `oracle` has the lowest `total_cost` in every regime (within rounding); MPC is below `no_battery` in `normal` and `dr_event`; `dr_shortfall_kwh` is lowest for MPC/oracle in `dr_event`. If not, use superpowers:systematic-debugging.

- [ ] **Step 3: Update `PROJECT_STATUS.md` and commit**

Mark the Plan 3 row done with the date.
```bash
uv run pytest tests_energy -q && uv run ruff check --fix .
git add -A scripts PROJECT_STATUS.md
git commit -m "Add controller comparison (baselines, MPC, oracle, RL, UC, LightGBM forecasts)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Done when

- `uv run pytest tests_energy -q` passes (RL export test runs in a child process).
- `scripts/compare_controllers.py --forecaster lgbm --uc --alert` runs on both sites.
- Ten trained policies (PPO and SAC × 5 seeds) and one warm-started PPO exist in `models/rl/kr_gwangyang/` with sha256 records.
