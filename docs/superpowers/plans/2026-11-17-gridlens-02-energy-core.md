# GridLens Plan 2 — Energy core (data, forecasting, simulator, baselines)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure-Python energy core of GridLens: site and tariff configuration, real-data adapters (UCI steel load, Open-Meteo weather, pvlib solar), tenants, a Gymnasium `MicrogridEnv` with a safety layer, disruptions, a frequency/UFLS model, forecasters (perfect, seasonal naive, LightGBM quantile), the three classical baseline controllers and an episode runner with KPIs.

**Architecture:** Two new packages beside the existing ones: `sim/gridlens_sim` (configuration, data series, plant physics, environment) and `control/gridlens_control` (controller protocol, baselines, runner). Data adapters and the LightGBM forecaster live in `ml/gridlens_ml`, which does not import `gridlens_sim`. Tests live in `tests_energy/` and need no database or network. Real data enters only through `gridlens_sim.factory.load_park`.

**Tech Stack:** Python 3.12, NumPy, pandas, Gymnasium, pvlib, LightGBM, PyYAML, httpx, pytest.

**Spec:** `docs/superpowers/specs/2026-11-17-gridlens-design.md` §4–§6.4. **Requires:** Plan 1 finished (packages are named `gridlens_*`).

## Global Constraints

- Step length 15 minutes (`DT_H = 0.25`), day = 96 steps, forecast horizon 96 steps, quantiles `(0.1, 0.25, 0.5, 0.75, 0.9)`.
- Battery sign: **positive = discharge, negative = charge** (kW at the battery terminals).
- Sizes are ratios of `P_peak` (largest 15-minute usage × 4): PV 0.8, battery power 0.5 for 2 h, 2 diesel units of 0.3, grid import 1.1, export 0.3; SoC 10–95 %; round-trip efficiency 90 %; diesel minimum load 30 %, minimum up/down 1 h.
- Korea site 60 Hz, `Asia/Seoul`; UAE what-if 50 Hz, `Asia/Dubai`; UFLS stages at −1.0 %, −1.5 %, −2.0 %.
- ADDC 2025 industrial: 0.366 AED/kWh peak, 0.270 off-peak, peak 10:00–22:00 from June to September.
- KEPCO 2018 values are not verified: the tariff file carries `assumed: true` until someone copies the official table.
- Energy balance at every step: `pv_used + import + discharge + diesel = (load − shed) + charge + export + spill`, error < 1e-6 kW.
- Every number's provenance (observed / simulated / assumed) is stated where it is defined.
- Tests in `tests_energy/` must not touch PostgreSQL or the network. Ruff rule B905 is on: every `zip()` passes `strict=True`.
- Run `uv run ruff check --fix` before each commit so import order (rule I) matches the project settings.
- Commit after each task; messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File map

| File | Responsibility |
|---|---|
| `config/tariffs/kr_industrial_b_2018.yaml`, `config/tariffs/ae_addc_industrial_2025.yaml` | time-of-use tariffs |
| `config/sites/kr_gwangyang.yaml`, `config/sites/ae_industrial.yaml` | site location, ratios, asset parameters |
| `sim/gridlens_sim/constants.py` | step, horizon, quantiles |
| `sim/gridlens_sim/config.py` | `Tariff`, `Site` and spec dataclasses, YAML loaders |
| `ml/gridlens_ml/steel.py` | UCI steel load reader |
| `ml/gridlens_ml/weather.py` | Open-Meteo archive client, interpolation |
| `ml/gridlens_ml/pv.py` | quarter-hour irradiance and PV output |
| `sim/gridlens_sim/tenants.py` | tenants, load split, shed order |
| `sim/gridlens_sim/series.py` | `ParkSeries` (aligned arrays) |
| `sim/gridlens_sim/testing.py` | synthetic series for tests and offline demos |
| `sim/gridlens_sim/components.py` | battery limits/SoC, diesel state |
| `sim/gridlens_sim/dispatch.py` | safety-layer dispatch with energy balance |
| `sim/gridlens_sim/disruptions.py` | `Event`, `Scenario`, `generate` |
| `sim/gridlens_sim/frequency.py` | islanded frequency transient and UFLS |
| `sim/gridlens_sim/forecast.py` | `Forecaster` protocol, perfect and seasonal-naive forecasters |
| `sim/gridlens_sim/env.py` | `MicrogridEnv`, `Observation`, `Action`, `StepRecord` |
| `sim/gridlens_sim/factory.py` | `load_park` from raw files |
| `control/gridlens_control/base.py` | `Controller` protocol |
| `control/gridlens_control/baselines.py` | `NoBattery`, `RuleTOU`, `GreedySelf` |
| `control/gridlens_control/runner.py` | `run_episode`, `EpisodeResult.kpis`, `summarise` |
| `ml/gridlens_ml/energy_forecast.py` | LightGBM quantile multi-horizon forecaster |
| `scripts/fetch_energy_data.py` | download raw data |
| `scripts/run_baselines.py` | baseline comparison on real data |
| `evaluations/gf1_forecast_study.py` | study GF1 |
| `tests_energy/*` | tests |

---

### Task 1: Packages, tariffs and site configuration

**Files:**
- Modify: `pyproject.toml`
- Create: `sim/gridlens_sim/__init__.py`, `sim/gridlens_sim/constants.py`, `sim/gridlens_sim/config.py`, `control/gridlens_control/__init__.py`
- Create: `config/tariffs/kr_industrial_b_2018.yaml`, `config/tariffs/ae_addc_industrial_2025.yaml`, `config/sites/kr_gwangyang.yaml`, `config/sites/ae_industrial.yaml`
- Test: `tests_energy/conftest.py`, `tests_energy/test_config.py`

**Interfaces:**
- Produces: `load_tariff(path) -> Tariff` with `band_at(ts) -> str`, `price_at(ts) -> float`; `load_site(site_id: str, p_peak_kw: float, config_dir=CONFIG_DIR) -> Site`; `Site` fields `id, name, currency, timezone, latitude, longitude, p_peak_kw, pv: PVSpec, battery: BatterySpec, diesels: tuple[DieselSpec, ...], grid: GridSpec, tariff: Tariff, frequency: FrequencySpec, carbon_price_per_kg, voll_per_kwh`; `BatterySpec.eta` (one-way efficiency); `DieselSpec.p_min_kw`, `DieselSpec.fuel_l(p_kw, dt_h)`. Constants `DT_H, DAY, WEEK, H, QUANTILES`.

- [ ] **Step 1: Add packages, dependencies and the test path**

```bash
uv add gymnasium pvlib pyyaml
mkdir -p sim/gridlens_sim control/gridlens_control config/tariffs config/sites tests_energy
touch sim/gridlens_sim/__init__.py control/gridlens_control/__init__.py
```
In `pyproject.toml` add the two packages to `[tool.hatch.build.targets.wheel] packages` and the test directory to pytest:
```toml
packages = [
  "services/api/src/gridlens",
  "services/worker/src/gridlens_worker",
  "ml/gridlens_ml",
  "optimisation/gridlens_opt",
  "sim/gridlens_sim",
  "control/gridlens_control",
]

[tool.pytest.ini_options]
testpaths = ["tests", "tests_energy"]
timeout = 300
```
Run `uv sync && chflags nohidden .venv/lib/python3.12/site-packages/*.pth` (macOS hides the editable-install file; see Plan 1, Task 1).

- [ ] **Step 2: Write the constants module**

`sim/gridlens_sim/constants.py`:
```python
"""Time grid shared by the simulator, the forecasters and the controllers (spec §4.3, §5.1)."""
DT_H = 0.25                                   # one step is 15 minutes
DAY = 96                                      # steps per day
WEEK = 7 * DAY
H = 96                                        # forecast horizon in steps (24 h)
QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)
```

- [ ] **Step 3: Write the tariff and site files**

`config/tariffs/kr_industrial_b_2018.yaml`:
```yaml
id: kr_industrial_b_2018
currency: KRW
source: >-
  KEPCO Industrial (B), high voltage A, option II, time-of-use structure in force in 2018. Band hours follow the
  KEPCO light/mid/maximum-load periods. Prices, export price and demand charge are planning values entered from
  memory and NOT yet checked against KEPCO's published 2018 table; replace them and set assumed to false once checked.
assumed: true
export_price: 90.0
demand_charge_per_kw_month: 8320.0
seasons:
  - name: summer
    months: [6, 7, 8]
    prices: {light: 56.1, mid: 109.0, peak: 191.1}
    hours:
      light: [23, 0, 1, 2, 3, 4, 5, 6, 7, 8]
      mid: [9, 12, 17, 18, 19, 20, 21, 22]
      peak: [10, 11, 13, 14, 15, 16]
  - name: spring_autumn
    months: [3, 4, 5, 9, 10]
    prices: {light: 56.1, mid: 78.6, peak: 109.3}
    hours:
      light: [23, 0, 1, 2, 3, 4, 5, 6, 7, 8]
      mid: [9, 12, 17, 18, 19, 20, 21, 22]
      peak: [10, 11, 13, 14, 15, 16]
  - name: winter
    months: [11, 12, 1, 2]
    prices: {light: 63.1, mid: 109.2, peak: 166.7}
    hours:
      light: [23, 0, 1, 2, 3, 4, 5, 6, 7, 8]
      mid: [9, 12, 13, 14, 15, 16, 20, 21]
      peak: [10, 11, 17, 18, 19, 22]
```

`config/tariffs/ae_addc_industrial_2025.yaml`:
```yaml
id: ae_addc_industrial_2025
currency: AED
source: >-
  ADDC 2025 industrial tariff: 36.6 fils/kWh in peak hours (10:00-22:00, 1 June to 30 September), 27.0 fils/kWh
  otherwise (https://www.addc.ae/en-US/business/Pages/RatesAndTariffs2025.aspx). Export price 0 and no demand charge
  are assumptions for the what-if.
assumed: false
export_price: 0.0
demand_charge_per_kw_month: 0.0
seasons:
  - name: summer
    months: [6, 7, 8, 9]
    prices: {light: 0.270, peak: 0.366}
    hours:
      light: [22, 23, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
      peak: [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]
  - name: rest_of_year
    months: [1, 2, 3, 4, 5, 10, 11, 12]
    prices: {light: 0.270}
    hours:
      light: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]
```

`config/sites/kr_gwangyang.yaml`:
```yaml
id: kr_gwangyang
name: Gwangyang steel park (Korea)
currency: KRW
timezone: Asia/Seoul
latitude: 34.94
longitude: 127.70
tariff: kr_industrial_b_2018
assumptions: >-
  Asset sizes are ratios of the observed peak load. Battery, diesel, carbon price and value of lost load are assumed
  planning values. Grid CO2 factor is an assumed national average.
ratios: {pv_kwp: 0.8, battery_power: 0.5, battery_hours: 2.0, diesel_unit: 0.3, diesel_units: 2,
         grid_import: 1.1, grid_export: 0.3}
pv: {tilt: 30.0, azimuth: 180.0, inverter_efficiency: 0.96, system_losses: 0.14}
battery: {soc_min: 0.10, soc_max: 0.95, round_trip_efficiency: 0.90, degradation_cost_per_kwh: 20.0}
diesel:
  min_load_frac: 0.30
  min_up_steps: 4
  min_down_steps: 4
  startup_cost: 30000.0
  fuel_a_l_per_kwh: 0.246
  fuel_b_l_per_kwh_rated: 0.08415
  fuel_price_per_l: 1400.0
  co2_kg_per_l: 2.68
  nox_g_per_kwh: 9.2
  pm_g_per_kwh: 0.54
  inertia_h_s: 2.0
grid: {co2_kg_per_kwh: 0.4594}
frequency: {nominal_hz: 60.0, ufls_stages: [0.010, 0.015, 0.020], load_damping: 1.0,
            battery_response_s: 0.2, governor_response_s: 2.0, battery_inertia_h_s: 1.0}
economics: {carbon_price_per_kg: 25.0, voll_per_kwh: 3000.0}
```

`config/sites/ae_industrial.yaml`:
```yaml
id: ae_industrial
name: Abu Dhabi industrial park (what-if)
currency: AED
timezone: Asia/Dubai
latitude: 24.33
longitude: 54.53
tariff: ae_addc_industrial_2025
assumptions: >-
  What-if: the Korean steel load profile on its local wall clock, UAE weather and the ADDC tariff. Battery, diesel,
  shadow carbon price and value of lost load are assumed; grid CO2 factor is an assumed national average.
ratios: {pv_kwp: 0.8, battery_power: 0.5, battery_hours: 2.0, diesel_unit: 0.3, diesel_units: 2,
         grid_import: 1.1, grid_export: 0.3}
pv: {tilt: 22.0, azimuth: 180.0, inverter_efficiency: 0.96, system_losses: 0.16}
battery: {soc_min: 0.10, soc_max: 0.95, round_trip_efficiency: 0.90, degradation_cost_per_kwh: 0.06}
diesel:
  min_load_frac: 0.30
  min_up_steps: 4
  min_down_steps: 4
  startup_cost: 90.0
  fuel_a_l_per_kwh: 0.246
  fuel_b_l_per_kwh_rated: 0.08415
  fuel_price_per_l: 2.8
  co2_kg_per_l: 2.68
  nox_g_per_kwh: 9.2
  pm_g_per_kwh: 0.54
  inertia_h_s: 2.0
grid: {co2_kg_per_kwh: 0.40}
frequency: {nominal_hz: 50.0, ufls_stages: [0.010, 0.015, 0.020], load_damping: 1.0,
            battery_response_s: 0.2, governor_response_s: 2.0, battery_inertia_h_s: 1.0}
economics: {carbon_price_per_kg: 0.10, voll_per_kwh: 10.0}
```

- [ ] **Step 4: Write the failing tests**

`tests_energy/conftest.py`:
```python
import pytest

from gridlens_sim.config import load_site


@pytest.fixture()
def site():
    return load_site("kr_gwangyang", p_peak_kw=1000.0)
```

`tests_energy/test_config.py`:
```python
import pandas as pd
import pytest

from gridlens_sim.config import CONFIG_DIR, load_site, load_tariff


def ts(s, tz="Asia/Seoul"):
    return pd.Timestamp(s, tz=tz)


def test_korea_bands_and_prices():
    t = load_tariff(CONFIG_DIR / "tariffs" / "kr_industrial_b_2018.yaml")
    assert t.band_at(ts("2018-07-02 03:00")) == "light"
    assert t.band_at(ts("2018-07-02 14:15")) == "peak"
    assert t.band_at(ts("2018-07-02 09:30")) == "mid"
    assert t.band_at(ts("2018-12-03 18:00")) == "peak"
    assert t.price_at(ts("2018-07-02 14:15")) > t.price_at(ts("2018-07-02 03:00"))
    assert t.assumed is True


def test_uae_peak_only_in_summer_afternoons():
    t = load_tariff(CONFIG_DIR / "tariffs" / "ae_addc_industrial_2025.yaml")
    assert t.price_at(ts("2018-07-02 12:00", "Asia/Dubai")) == pytest.approx(0.366)
    assert t.price_at(ts("2018-07-02 23:00", "Asia/Dubai")) == pytest.approx(0.270)
    assert t.price_at(ts("2018-12-03 12:00", "Asia/Dubai")) == pytest.approx(0.270)


def test_tariff_must_cover_every_hour(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "id: bad\ncurrency: X\nsource: test\nassumed: true\nexport_price: 0\n"
        "demand_charge_per_kw_month: 0\nseasons:\n  - name: all\n"
        "    months: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]\n"
        "    prices: {light: 1.0}\n    hours: {light: [0, 1, 2]}\n")
    with pytest.raises(ValueError, match="hours 0-23"):
        load_tariff(bad)


def test_site_sizes_follow_peak(site):
    assert site.pv.kwp == pytest.approx(800.0)
    assert site.battery.power_kw == pytest.approx(500.0)
    assert site.battery.energy_kwh == pytest.approx(1000.0)
    assert [d.p_max_kw for d in site.diesels] == [pytest.approx(300.0)] * 2
    assert site.diesels[0].p_min_kw == pytest.approx(90.0)
    assert site.grid.import_limit_kw == pytest.approx(1100.0)
    assert site.grid.export_limit_kw == pytest.approx(300.0)
    assert site.frequency.nominal_hz == 60.0
    assert site.tariff.id == "kr_industrial_b_2018"


def test_uae_site():
    s = load_site("ae_industrial", p_peak_kw=1000.0)
    assert s.frequency.nominal_hz == 50.0 and s.timezone == "Asia/Dubai" and s.currency == "AED"
```

- [ ] **Step 5: Run the tests to see them fail**

Run: `uv run pytest tests_energy/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'gridlens_sim.config'`.

- [ ] **Step 6: Write `sim/gridlens_sim/config.py`**

```python
"""Site, asset and tariff configuration (spec §4.1-§4.2). Asset sizes are ratios of the observed peak load."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@dataclass(frozen=True)
class Season:
    name: str
    months: tuple[int, ...]
    prices: dict[str, float]
    hours: dict[str, tuple[int, ...]]


@dataclass(frozen=True)
class Tariff:
    id: str
    currency: str
    seasons: tuple[Season, ...]
    export_price: float
    demand_charge_per_kw_month: float
    source: str
    assumed: bool

    def _season(self, month: int) -> Season:
        for s in self.seasons:
            if month in s.months:
                return s
        raise ValueError(f"tariff {self.id} has no season for month {month}")

    def band_at(self, ts: pd.Timestamp) -> str:
        season = self._season(ts.month)
        for band, hours in season.hours.items():
            if ts.hour in hours:
                return band
        raise ValueError(f"tariff {self.id} has no band for hour {ts.hour} in {season.name}")

    def price_at(self, ts: pd.Timestamp) -> float:
        return self._season(ts.month).prices[self.band_at(ts)]

    def validate(self) -> None:
        months = sorted(m for s in self.seasons for m in s.months)
        if months != list(range(1, 13)):
            raise ValueError(f"tariff {self.id}: seasons must cover months 1-12 exactly once, got {months}")
        for s in self.seasons:
            hours = sorted(h for hs in s.hours.values() for h in hs)
            if hours != list(range(24)):
                raise ValueError(f"tariff {self.id} season {s.name}: bands must cover hours 0-23 exactly once")
            if set(s.hours) != set(s.prices):
                raise ValueError(f"tariff {self.id} season {s.name}: every band needs hours and a price")


def load_tariff(path: Path) -> Tariff:
    raw = yaml.safe_load(Path(path).read_text())
    seasons = tuple(
        Season(name=s["name"], months=tuple(s["months"]),
               prices={k: float(v) for k, v in s["prices"].items()},
               hours={k: tuple(v) for k, v in s["hours"].items()})
        for s in raw["seasons"])
    tariff = Tariff(id=raw["id"], currency=raw["currency"], seasons=seasons,
                    export_price=float(raw["export_price"]),
                    demand_charge_per_kw_month=float(raw["demand_charge_per_kw_month"]),
                    source=raw["source"], assumed=bool(raw["assumed"]))
    tariff.validate()
    return tariff


@dataclass(frozen=True)
class PVSpec:
    kwp: float
    tilt: float
    azimuth: float
    inverter_efficiency: float
    system_losses: float


@dataclass(frozen=True)
class BatterySpec:
    power_kw: float
    energy_kwh: float
    soc_min: float
    soc_max: float
    round_trip_efficiency: float
    degradation_cost_per_kwh: float

    @property
    def eta(self) -> float:
        """One-way efficiency, applied on charge and on discharge."""
        return self.round_trip_efficiency ** 0.5


@dataclass(frozen=True)
class DieselSpec:
    name: str
    p_max_kw: float
    min_load_frac: float
    min_up_steps: int
    min_down_steps: int
    startup_cost: float
    fuel_a_l_per_kwh: float
    fuel_b_l_per_kwh_rated: float
    fuel_price_per_l: float
    co2_kg_per_l: float
    nox_g_per_kwh: float
    pm_g_per_kwh: float
    inertia_h_s: float

    @property
    def p_min_kw(self) -> float:
        return self.p_max_kw * self.min_load_frac

    def fuel_l(self, p_kw: float, dt_h: float) -> float:
        """Linear fuel curve for a running unit: a * output + b * rating (litres per hour)."""
        return (self.fuel_a_l_per_kwh * p_kw + self.fuel_b_l_per_kwh_rated * self.p_max_kw) * dt_h


@dataclass(frozen=True)
class GridSpec:
    import_limit_kw: float
    export_limit_kw: float
    co2_kg_per_kwh: float


@dataclass(frozen=True)
class FrequencySpec:
    nominal_hz: float
    ufls_stages: tuple[float, ...]
    load_damping: float
    battery_response_s: float
    governor_response_s: float
    battery_inertia_h_s: float


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    currency: str
    timezone: str
    latitude: float
    longitude: float
    p_peak_kw: float
    pv: PVSpec
    battery: BatterySpec
    diesels: tuple[DieselSpec, ...]
    grid: GridSpec
    tariff: Tariff
    frequency: FrequencySpec
    carbon_price_per_kg: float
    voll_per_kwh: float


def load_site(site_id: str, p_peak_kw: float, config_dir: Path = CONFIG_DIR) -> Site:
    raw = yaml.safe_load((Path(config_dir) / "sites" / f"{site_id}.yaml").read_text())
    r, pv, b, d, f = raw["ratios"], raw["pv"], raw["battery"], raw["diesel"], raw["frequency"]
    power = r["battery_power"] * p_peak_kw
    diesels = tuple(
        DieselSpec(name=f"DG{i + 1}", p_max_kw=r["diesel_unit"] * p_peak_kw,
                   min_load_frac=d["min_load_frac"], min_up_steps=int(d["min_up_steps"]),
                   min_down_steps=int(d["min_down_steps"]), startup_cost=float(d["startup_cost"]),
                   fuel_a_l_per_kwh=d["fuel_a_l_per_kwh"], fuel_b_l_per_kwh_rated=d["fuel_b_l_per_kwh_rated"],
                   fuel_price_per_l=float(d["fuel_price_per_l"]), co2_kg_per_l=d["co2_kg_per_l"],
                   nox_g_per_kwh=d["nox_g_per_kwh"], pm_g_per_kwh=d["pm_g_per_kwh"],
                   inertia_h_s=d["inertia_h_s"])
        for i in range(int(r["diesel_units"])))
    return Site(
        id=raw["id"], name=raw["name"], currency=raw["currency"], timezone=raw["timezone"],
        latitude=float(raw["latitude"]), longitude=float(raw["longitude"]), p_peak_kw=float(p_peak_kw),
        pv=PVSpec(kwp=r["pv_kwp"] * p_peak_kw, tilt=pv["tilt"], azimuth=pv["azimuth"],
                  inverter_efficiency=pv["inverter_efficiency"], system_losses=pv["system_losses"]),
        battery=BatterySpec(power_kw=power, energy_kwh=power * r["battery_hours"], soc_min=b["soc_min"],
                            soc_max=b["soc_max"], round_trip_efficiency=b["round_trip_efficiency"],
                            degradation_cost_per_kwh=float(b["degradation_cost_per_kwh"])),
        diesels=diesels,
        grid=GridSpec(import_limit_kw=r["grid_import"] * p_peak_kw, export_limit_kw=r["grid_export"] * p_peak_kw,
                      co2_kg_per_kwh=raw["grid"]["co2_kg_per_kwh"]),
        tariff=load_tariff(Path(config_dir) / "tariffs" / f"{raw['tariff']}.yaml"),
        frequency=FrequencySpec(nominal_hz=float(f["nominal_hz"]), ufls_stages=tuple(f["ufls_stages"]),
                                load_damping=f["load_damping"], battery_response_s=f["battery_response_s"],
                                governor_response_s=f["governor_response_s"],
                                battery_inertia_h_s=f["battery_inertia_h_s"]),
        carbon_price_per_kg=float(raw["economics"]["carbon_price_per_kg"]),
        voll_per_kwh=float(raw["economics"]["voll_per_kwh"]))
```

- [ ] **Step 7: Run the tests to see them pass**

Run: `uv run pytest tests_energy/test_config.py -q && uv run ruff check sim config tests_energy`
Expected: `5 passed`; ruff clean.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock sim control config tests_energy
git commit -m "Add GridLens site and tariff configuration (Korea KEPCO assumed, UAE ADDC 2025)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: UCI steel load reader

**Files:**
- Create: `ml/gridlens_ml/steel.py`, `tests_energy/steel_fixture.py`
- Test: `tests_energy/test_steel.py`

**Interfaces:**
- Produces: `read_steel(path, tz="Asia/Seoul") -> pd.DataFrame` indexed by 15-minute interval start (tz-aware), columns `usage_kwh, week_status, load_type, load_kw`; `peak_kw(df) -> float`; constant `URL`. Test helper `steel_fixture.HEADER`, `steel_fixture.steel_csv(stamps, values) -> str`.

- [ ] **Step 1: Write the fixture helper and failing tests**

`tests_energy/steel_fixture.py`:
```python
HEADER = ("date,Usage_kWh,Lagging_Current_Reactive.Power_kVarh,Leading_Current_Reactive_Power_kVarh,"
          "CO2(tCO2),Lagging_Current_Power_Factor,Leading_Current_Power_Factor,NSM,WeekStatus,"
          "Day_of_week,Load_Type\n")


def steel_csv(stamps, values) -> str:
    rows = (f"{s},{v},0,0,0,100,100,0,Weekday,Monday,Light_Load\n" for s, v in zip(stamps, values, strict=True))
    return HEADER + "".join(rows)
```

`tests_energy/test_steel.py`:
```python
import pandas as pd
import pytest
from steel_fixture import steel_csv

from gridlens_ml.steel import peak_kw, read_steel


def _write(tmp_path, stamps):
    p = tmp_path / "steel.csv"
    p.write_text(steel_csv(stamps, [i + 1.0 for i in range(len(stamps))]))
    return p


def test_interval_ending_stamps_move_to_interval_start(tmp_path):
    df = read_steel(_write(tmp_path, ["01/01/2018 00:15", "01/01/2018 00:30",
                                      "01/01/2018 00:45", "01/01/2018 01:00"]))
    assert df.index[0] == pd.Timestamp("2018-01-01 00:00", tz="Asia/Seoul")
    assert df.index[-1] == pd.Timestamp("2018-01-01 00:45", tz="Asia/Seoul")
    assert df["load_kw"].tolist() == [4.0, 8.0, 12.0, 16.0]


def test_midnight_written_as_same_day_goes_to_next_day(tmp_path):
    stamps = [f"01/01/2018 {h:02d}:{m:02d}" for h in range(24) for m in (0, 15, 30, 45)][1:]
    stamps.append("01/01/2018 00:00")
    df = read_steel(_write(tmp_path, stamps))
    assert len(df) == 96
    assert df.index[0] == pd.Timestamp("2018-01-01 00:00", tz="Asia/Seoul")
    assert df.index[-1] == pd.Timestamp("2018-01-01 23:45", tz="Asia/Seoul")


def test_gap_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="regular 15-minute grid"):
        read_steel(_write(tmp_path, ["01/01/2018 00:15", "01/01/2018 00:30", "01/01/2018 01:00"]))


def test_peak_kw(tmp_path):
    assert peak_kw(read_steel(_write(tmp_path, ["01/01/2018 00:15", "01/01/2018 00:30"]))) == 8.0
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests_energy/test_steel.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'gridlens_ml.steel'`.

- [ ] **Step 3: Write `ml/gridlens_ml/steel.py`**

```python
"""UCI Steel Industry Energy Consumption (id 851, doi:10.24432/C52G8C, CC BY 4.0).

15-minute kWh for one steel plant (DAEWOO Steel, Gwangyang, South Korea) through 2018. GridLens uses it as the
industrial park's aggregate load (observed).
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

URL = "https://archive.ics.uci.edu/static/public/851/steel+industry+energy+consumption.zip"
STEP = pd.Timedelta(minutes=15)
RENAME = {"Usage_kWh": "usage_kwh", "WeekStatus": "week_status", "Load_Type": "load_type"}


def _read_frame(path: Path) -> pd.DataFrame:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            return pd.read_csv(io.BytesIO(z.read(name)))
    return pd.read_csv(path)


def _parse_times(raw: pd.Series) -> pd.Series:
    try:
        ts = pd.to_datetime(raw, format="%d/%m/%Y %H:%M")
    except ValueError:
        ts = pd.to_datetime(raw, format="mixed", dayfirst=True)
    # Some exports write the interval that ends at 24:00 as 00:00 of the same day; in file order that row then
    # jumps back almost a day. Move such rows to the next day.
    back = ts.diff() < pd.Timedelta(0)
    return ts.where(~back, ts + pd.Timedelta(days=1))


def read_steel(path: Path, tz: str = "Asia/Seoul") -> pd.DataFrame:
    df = _read_frame(Path(path))
    ts = _parse_times(df["date"])
    first = ts.min()
    if first.hour == 0 and first.minute == 15:     # stamps mark the end of each 15-minute interval
        ts = ts - STEP
    out = df.rename(columns=RENAME)[list(RENAME.values())].copy()
    out.index = pd.DatetimeIndex(ts).tz_localize(tz)
    out.index.name = "interval_start"
    out = out.sort_index()
    if out.index.has_duplicates:
        raise ValueError(f"duplicate timestamps after parsing: {out.index[out.index.duplicated()][:3].tolist()}")
    expected = pd.date_range(out.index[0], out.index[-1], freq=STEP)
    if len(expected) != len(out):
        missing = expected.difference(out.index)[:3].tolist()
        raise ValueError(f"series is not a regular 15-minute grid; first missing: {missing}")
    out["load_kw"] = out["usage_kwh"].astype(float) * 4.0
    return out


def peak_kw(df: pd.DataFrame) -> float:
    return float(df["load_kw"].max())
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests_energy/test_steel.py -q && uv run ruff check ml tests_energy`
Expected: `4 passed`; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add ml/gridlens_ml/steel.py tests_energy/steel_fixture.py tests_energy/test_steel.py
git commit -m "Add UCI steel load reader with interval and midnight handling

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Weather client and PV model

**Files:**
- Create: `ml/gridlens_ml/weather.py`, `ml/gridlens_ml/pv.py`
- Test: `tests_energy/test_weather.py`, `tests_energy/test_pv.py`

**Interfaces:**
- Consumes: `Site` (Task 1): `latitude, longitude, timezone, pv.kwp, pv.tilt, pv.azimuth, pv.inverter_efficiency, pv.system_losses`.
- Produces: `ARCHIVE_URL`, `HOURLY`, `fetch_hourly(latitude, longitude, start, end, timezone, client=None) -> DataFrame`, `parse_hourly(payload, timezone) -> DataFrame`, `interpolate_to(hourly: Series, index) -> Series` (in `weather.py`); `ghi_quarter_hour(hourly_ghi, latitude, longitude, timezone) -> Series`, `pv_output_kw(ghi, temp_c, wind_ms, site) -> Series` (in `pv.py`). `pv.py` takes the site by duck typing and does not import `gridlens_sim`.

- [ ] **Step 1: Write the failing tests**

`tests_energy/test_weather.py`:
```python
import httpx
import pandas as pd
import pytest

from gridlens_ml.weather import fetch_hourly, interpolate_to, parse_hourly

PAYLOAD = {"hourly": {"time": ["2018-06-01T00:00", "2018-06-01T01:00"], "shortwave_radiation": [0, 10],
                      "temperature_2m": [20, 21], "cloud_cover": [0, 50], "wind_speed_10m": [1, 2]}}


def test_parse_hourly():
    df = parse_hourly(PAYLOAD, "Asia/Seoul")
    assert df.index[0] == pd.Timestamp("2018-06-01 00:00", tz="Asia/Seoul")
    assert df["shortwave_radiation"].iloc[1] == 10.0


def test_fetch_asks_the_archive_for_hourly_radiation():
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=PAYLOAD)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetch_hourly(34.94, 127.70, "2018-06-01", "2018-06-01", "Asia/Seoul", client=client)
    assert seen["start_date"] == "2018-06-01" and "shortwave_radiation" in seen["hourly"]
    assert seen["timezone"] == "Asia/Seoul"


def test_interpolate_to_quarter_hour_midpoints():
    idx = pd.DatetimeIndex(["2018-06-01 00:00", "2018-06-01 01:00"]).tz_localize("Asia/Seoul")
    q = pd.date_range("2018-06-01 00:00", periods=4, freq="15min", tz="Asia/Seoul")
    out = interpolate_to(pd.Series([0.0, 4.0], index=idx), q)
    assert out.tolist() == pytest.approx([0.5, 1.5, 2.5, 3.5])
```

`tests_energy/test_pv.py`:
```python
import numpy as np
import pandas as pd
from pvlib.location import Location

from gridlens_ml.pv import ghi_quarter_hour, pv_output_kw


def _hourly_clear_day(site, day="2018-06-21"):
    """Hourly means of the clear-sky model, stamped at the end of each hour as Open-Meteo does."""
    loc = Location(site.latitude, site.longitude, tz=site.timezone)
    q = pd.date_range(f"{day} 00:00", periods=96, freq="15min", tz=site.timezone)
    cs = loc.get_clearsky(q + pd.Timedelta(minutes=7.5), model="haurwitz")["ghi"].to_numpy()
    idx = pd.date_range(f"{day} 01:00", periods=24, freq="h", tz=site.timezone)
    return pd.Series(cs.reshape(24, 4).mean(axis=1), index=idx)


def test_quarter_hour_ghi_keeps_each_hours_energy(site):
    hourly = _hourly_clear_day(site)
    q = ghi_quarter_hour(hourly, site.latitude, site.longitude, site.timezone)
    assert len(q) == 96
    np.testing.assert_allclose(q.to_numpy().reshape(24, 4).mean(axis=1), hourly.to_numpy(), atol=1e-6)


def test_pv_is_zero_at_night_and_bounded(site):
    q = ghi_quarter_hour(_hourly_clear_day(site), site.latitude, site.longitude, site.timezone)
    pv = pv_output_kw(q, pd.Series(25.0, index=q.index), pd.Series(2.0, index=q.index), site)
    assert (pv.loc["2018-06-21 01:00":"2018-06-21 03:00"] == 0).all()
    assert pv.max() > 0.5 * site.pv.kwp
    assert pv.max() <= site.pv.kwp * site.pv.inverter_efficiency + 1e-9
    assert pv.min() >= 0
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests_energy/test_weather.py tests_energy/test_pv.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `ml/gridlens_ml/weather.py`**

```python
"""Open-Meteo historical weather (CC BY 4.0). Radiation values are backward averages over the preceding hour;
temperature, cloud cover and wind are instantaneous at the stamp."""
from __future__ import annotations

import httpx
import numpy as np
import pandas as pd

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY = ("shortwave_radiation", "temperature_2m", "cloud_cover", "wind_speed_10m")


def parse_hourly(payload: dict, timezone: str) -> pd.DataFrame:
    h = payload["hourly"]
    idx = pd.DatetimeIndex(pd.to_datetime(h["time"])).tz_localize(timezone)
    df = pd.DataFrame({k: h[k] for k in HOURLY}, index=idx).astype(float)
    df.index.name = "time"
    return df


def fetch_hourly(latitude: float, longitude: float, start: str, end: str, timezone: str,
                 client: httpx.Client | None = None) -> pd.DataFrame:
    params = {"latitude": latitude, "longitude": longitude, "start_date": start, "end_date": end,
              "hourly": ",".join(HOURLY), "timezone": timezone, "wind_speed_unit": "ms"}
    own = client is None
    c = client or httpx.Client(timeout=120)
    try:
        r = c.get(ARCHIVE_URL, params=params)
        r.raise_for_status()
        return parse_hourly(r.json(), timezone)
    finally:
        if own:
            c.close()


def interpolate_to(hourly: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """Linear interpolation of an instantaneous hourly variable onto 15-minute interval mid-points."""
    mid = index + pd.Timedelta(minutes=7.5)
    values = np.interp(mid.asi8, hourly.index.asi8, hourly.to_numpy(dtype=float))
    return pd.Series(values, index=index, name=hourly.name)
```

- [ ] **Step 4: Write `ml/gridlens_ml/pv.py`**

```python
"""Rooftop PV output from irradiance (simulated from observed weather; spec §4.1)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from pvlib import irradiance, pvsystem, temperature
from pvlib.location import Location


def ghi_quarter_hour(hourly_ghi: pd.Series, latitude: float, longitude: float, timezone: str) -> pd.Series:
    """Spread each hourly mean (stamped at the hour's end) over its four quarter-hours in proportion to clear-sky
    irradiance, so each hour's energy is unchanged. Hours with no clear-sky irradiance keep a flat value."""
    loc = Location(latitude, longitude, tz=timezone)
    hour_start = hourly_ghi.index - pd.Timedelta(hours=1)
    q_index = pd.date_range(hour_start[0], hour_start[-1] + pd.Timedelta(minutes=45), freq="15min")
    cs = loc.get_clearsky(q_index + pd.Timedelta(minutes=7.5), model="haurwitz")["ghi"].to_numpy()
    hour_of = q_index.floor("h")
    cs_mean = pd.Series(cs, index=q_index).groupby(hour_of).transform("mean").to_numpy()
    h_val = pd.Series(hourly_ghi.to_numpy(dtype=float), index=hour_start).reindex(hour_of).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        shaped = np.where(cs_mean > 1.0, h_val * cs / cs_mean, h_val)
    return pd.Series(np.nan_to_num(shaped), index=q_index, name="ghi")


def pv_output_kw(ghi: pd.Series, temp_c: pd.Series, wind_ms: pd.Series, site) -> pd.Series:
    """AC output of a fixed-tilt array: Erbs decomposition, isotropic transposition, Faiman cell temperature,
    PVWatts DC model (-0.4 %/°C), flat system losses and inverter efficiency, clipped at the inverter rating."""
    loc = Location(site.latitude, site.longitude, tz=site.timezone)
    mid = ghi.index + pd.Timedelta(minutes=7.5)
    sp = loc.get_solarposition(mid)
    zen = sp["apparent_zenith"].to_numpy()
    azi = sp["azimuth"].to_numpy()
    g = ghi.to_numpy(dtype=float)
    parts = irradiance.erbs(g, zen, np.asarray(mid.dayofyear))
    poa = irradiance.get_total_irradiance(site.pv.tilt, site.pv.azimuth, zen, azi,
                                          parts["dni"], g, parts["dhi"])["poa_global"]
    poa = np.clip(np.nan_to_num(np.asarray(poa, dtype=float)), 0.0, None)
    t_cell = temperature.faiman(poa, temp_c.to_numpy(dtype=float), wind_ms.to_numpy(dtype=float))
    dc = np.asarray(pvsystem.pvwatts_dc(poa, t_cell, site.pv.kwp, -0.004), dtype=float)
    ac = dc * (1.0 - site.pv.system_losses) * site.pv.inverter_efficiency
    ac = np.clip(np.nan_to_num(ac), 0.0, site.pv.kwp * site.pv.inverter_efficiency)
    ac[zen >= 90.0] = 0.0
    return pd.Series(ac, index=ghi.index, name="pv_kw")
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests_energy/test_weather.py tests_energy/test_pv.py -q && uv run ruff check ml tests_energy`
Expected: `5 passed`; ruff clean. If pvlib's `pvwatts_dc` rejects positional arguments in the installed version, open `uv run python -c "import pvlib, inspect; print(pvlib.__version__, inspect.signature(pvlib.pvsystem.pvwatts_dc))"` and pass the same four values by the names it prints.

- [ ] **Step 6: Commit**

```bash
git add ml/gridlens_ml/weather.py ml/gridlens_ml/pv.py tests_energy/test_weather.py tests_energy/test_pv.py
git commit -m "Add Open-Meteo archive client and pvlib PV model with energy-preserving quarter-hours

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Tenants, park series and synthetic series

**Files:**
- Create: `sim/gridlens_sim/tenants.py`, `sim/gridlens_sim/series.py`, `sim/gridlens_sim/testing.py`
- Test: `tests_energy/test_tenants.py`, `tests_energy/test_series.py`

**Interfaces:**
- Consumes: `Site`, `Tariff.price_at`, `Tariff.band_at` (Task 1).
- Produces: `Tenant(id, name, share, priority, flexible_share)`, `DEFAULT_TENANTS` (order: T1 critical, T2 essential, T3 essential, T4 flexible, T5 flexible), `PRIORITY_WEIGHT = {"critical": 10.0, "essential": 3.0, "flexible": 1.0}`, `validate(tenants)`, `split_load(load_kw, tenants) -> ndarray (T, n)`, `flexible_kw(tenant_kw, tenants) -> ndarray (T,)`, `shed_order(tenants, rotation) -> list[int]`, `allocate_shed(shed_kw, tenant_kw, tenants, rotation) -> ndarray`; `ParkSeries(index, load_kw, pv_kw, tenant_kw, flex_kw, price, band)` with `__len__`, `position(ts)`, `day_starts(start, end)`; `build_series(index, load_kw, pv_kw, site, tenants) -> ParkSeries`; `synthetic_series(site, tenants=DEFAULT_TENANTS, days=21, start="2018-11-01", seed=0) -> ParkSeries`.

- [ ] **Step 1: Write the failing tests**

`tests_energy/test_tenants.py`:
```python
import numpy as np
import pytest

from gridlens_sim.tenants import DEFAULT_TENANTS, allocate_shed, shed_order, split_load, validate


def test_default_tenants_are_valid():
    validate(DEFAULT_TENANTS)
    assert all(t.flexible_share == 0 for t in DEFAULT_TENANTS if t.priority == "critical")


def test_split_conserves_load():
    load = np.array([100.0, 50.0])
    np.testing.assert_allclose(split_load(load, DEFAULT_TENANTS).sum(axis=1), load)


def test_shed_order_is_by_class_and_rotates_within_class():
    o0, o1 = shed_order(DEFAULT_TENANTS, 0), shed_order(DEFAULT_TENANTS, 1)
    assert [DEFAULT_TENANTS[i].priority for i in o0] == [
        "flexible", "flexible", "essential", "essential", "critical"]
    assert o0[:2] == [3, 4] and o1[:2] == [4, 3]
    assert o0[2:4] == [1, 2] and o1[2:4] == [2, 1]


def test_allocate_shed_takes_flexible_first():
    kw = np.array([350.0, 250.0, 150.0, 150.0, 100.0])
    assert allocate_shed(200.0, kw, DEFAULT_TENANTS, rotation=0).tolist() == [0, 0, 0, 150, 50]


def test_allocate_shed_rejects_more_than_the_load():
    with pytest.raises(ValueError):
        allocate_shed(2000.0, np.full(5, 100.0), DEFAULT_TENANTS, rotation=0)
```

`tests_energy/test_series.py`:
```python
import numpy as np

from gridlens_sim.testing import synthetic_series


def test_synthetic_series_shapes_and_alignment(site):
    s = synthetic_series(site, days=3)
    assert len(s) == 288 and s.tenant_kw.shape == (288, 5)
    np.testing.assert_allclose(s.tenant_kw.sum(axis=1), s.load_kw)
    assert set(s.band) <= {"light", "mid", "peak"}
    assert (s.pv_kw >= 0).all() and (s.flex_kw <= s.load_kw).all()
    assert s.day_starts("2018-11-01", "2018-11-03") == [0, 96, 192]


def test_synthetic_series_is_deterministic(site):
    a, b = synthetic_series(site, days=2, seed=4), synthetic_series(site, days=2, seed=4)
    np.testing.assert_array_equal(a.load_kw, b.load_kw)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests_energy/test_tenants.py tests_energy/test_series.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `sim/gridlens_sim/tenants.py`**

```python
"""Tenant factories of the park (simulated; spec §4.1) and the published load-shed order (spec §9.2)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

PRIORITIES = ("critical", "essential", "flexible")
SHED_CLASS_ORDER = ("flexible", "essential", "critical")
PRIORITY_WEIGHT = {"critical": 10.0, "essential": 3.0, "flexible": 1.0}


@dataclass(frozen=True)
class Tenant:
    id: str
    name: str
    share: float              # share of the park's load
    priority: str             # critical | essential | flexible
    flexible_share: float     # share of this tenant's load that can be postponed


DEFAULT_TENANTS = (
    Tenant("T1", "Melt shop", 0.35, "critical", 0.0),
    Tenant("T2", "Rolling mill", 0.25, "essential", 0.10),
    Tenant("T3", "Plate finishing", 0.15, "essential", 0.20),
    Tenant("T4", "Coil packaging", 0.15, "flexible", 0.40),
    Tenant("T5", "Warehouse and offices", 0.10, "flexible", 0.30),
)


def validate(tenants) -> None:
    if abs(sum(t.share for t in tenants) - 1.0) > 1e-9:
        raise ValueError("tenant shares must sum to 1")
    for t in tenants:
        if t.priority not in PRIORITIES:
            raise ValueError(f"{t.id}: unknown priority {t.priority}")
        if not 0.0 <= t.flexible_share <= 1.0:
            raise ValueError(f"{t.id}: flexible_share must be in [0, 1]")
        if t.priority == "critical" and t.flexible_share > 0:
            raise ValueError(f"{t.id}: a critical tenant cannot have flexible load")


def split_load(load_kw: np.ndarray, tenants) -> np.ndarray:
    return np.outer(np.asarray(load_kw, dtype=float), [t.share for t in tenants])


def flexible_kw(tenant_kw: np.ndarray, tenants) -> np.ndarray:
    return tenant_kw @ np.array([t.flexible_share for t in tenants])


def shed_order(tenants, rotation: int) -> list[int]:
    """Indices in the order tenants lose power: flexible, then essential, then critical. Within a class the
    starting tenant rotates with `rotation`, so the same tenant is not always first."""
    order: list[int] = []
    for cls in SHED_CLASS_ORDER:
        idx = [i for i, t in enumerate(tenants) if t.priority == cls]
        if idx:
            r = rotation % len(idx)
            order += idx[r:] + idx[:r]
    return order


def allocate_shed(shed_kw: float, tenant_kw: np.ndarray, tenants, rotation: int) -> np.ndarray:
    out = np.zeros(len(tenants))
    remaining = float(shed_kw)
    for i in shed_order(tenants, rotation):
        if remaining <= 1e-9:
            break
        take = min(remaining, float(tenant_kw[i]))
        out[i] = take
        remaining -= take
    if remaining > 1e-6:
        raise ValueError(f"cannot shed {shed_kw:.3f} kW: only {float(np.sum(tenant_kw)):.3f} kW of tenant load")
    return out
```

- [ ] **Step 4: Write `sim/gridlens_sim/series.py`**

```python
"""Aligned 15-minute arrays for one park: load, PV, tenants, flexible load and tariff."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .tenants import flexible_kw, split_load, validate


@dataclass(frozen=True)
class ParkSeries:
    index: pd.DatetimeIndex     # interval starts, tz-aware
    load_kw: np.ndarray
    pv_kw: np.ndarray
    tenant_kw: np.ndarray       # (T, n_tenants)
    flex_kw: np.ndarray         # postponable part of load_kw
    price: np.ndarray           # currency per kWh
    band: np.ndarray            # tariff band name per step

    def __len__(self) -> int:
        return len(self.index)

    def position(self, ts) -> int:
        return int(self.index.get_loc(pd.Timestamp(ts)))

    def day_starts(self, start: str, end: str) -> list[int]:
        days = pd.date_range(start, end, freq="D", tz=self.index.tz)
        return [self.position(d) for d in days]


def build_series(index: pd.DatetimeIndex, load_kw: np.ndarray, pv_kw: np.ndarray, site, tenants) -> ParkSeries:
    validate(tenants)
    load = np.asarray(load_kw, dtype=float)
    tenant = split_load(load, tenants)
    return ParkSeries(
        index=index, load_kw=load, pv_kw=np.asarray(pv_kw, dtype=float), tenant_kw=tenant,
        flex_kw=flexible_kw(tenant, tenants),
        price=np.array([site.tariff.price_at(t) for t in index], dtype=float),
        band=np.array([site.tariff.band_at(t) for t in index], dtype=object))
```

- [ ] **Step 5: Write `sim/gridlens_sim/testing.py`**

```python
"""Synthetic park series for tests and offline demos (clearly simulated; never used for reported results)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .series import ParkSeries, build_series
from .tenants import DEFAULT_TENANTS


def synthetic_series(site, tenants=DEFAULT_TENANTS, days: int = 21, start: str = "2018-11-01",
                     seed: int = 0) -> ParkSeries:
    rng = np.random.default_rng(seed)
    index = pd.date_range(start, periods=days * 96, freq="15min", tz=site.timezone)
    hour = np.asarray(index.hour + index.minute / 60, dtype=float)
    weekday = np.asarray(index.dayofweek < 5)
    shift = (hour >= 8) & (hour < 20)
    base = 0.35 + 0.45 * shift * np.where(weekday, 1.0, 0.4)
    load = site.p_peak_kw * np.clip(base + rng.normal(0.0, 0.03, len(index)), 0.05, 1.0)
    sun = np.clip(np.sin(np.pi * (hour - 6.0) / 12.0), 0.0, None)
    pv = site.pv.kwp * 0.8 * sun * np.repeat(rng.uniform(0.6, 1.0, size=days), 96)
    return build_series(index, load, pv, site, tenants)
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests_energy/test_tenants.py tests_energy/test_series.py -q && uv run ruff check sim tests_energy`
Expected: `7 passed`; ruff clean.

- [ ] **Step 7: Commit**

```bash
git add sim/gridlens_sim/tenants.py sim/gridlens_sim/series.py sim/gridlens_sim/testing.py tests_energy/test_tenants.py tests_energy/test_series.py
git commit -m "Add tenants with rotating shed order, park series and synthetic series

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Battery, diesel state and the safety-layer dispatch

**Files:**
- Create: `sim/gridlens_sim/components.py`, `sim/gridlens_sim/dispatch.py`
- Test: `tests_energy/test_dispatch.py`

**Interfaces:**
- Consumes: `BatterySpec`, `DieselSpec`, `GridSpec` (Task 1).
- Produces: `battery_limits(spec, soc, dt_h) -> (max_charge_kw, max_discharge_kw)`, `battery_next_soc(spec, soc, power_kw, dt_h) -> float`, `DieselState(on=False, steps_in_state=10**6)`; `Dispatch` dataclass (fields `load_kw, pv_kw, pv_used_kw, curtailed_kw, battery_kw, grid_import_kw, grid_export_kw, diesel_kw: tuple, shed_kw, spill_kw, corrections: list[str]`, method `balance_error()`), `dispatch(load_kw, pv_kw, battery_request_kw, limits, diesels, diesel_on, grid, grid_available) -> Dispatch`.

- [ ] **Step 1: Write the failing tests**

`tests_energy/test_dispatch.py`:
```python
import numpy as np
import pytest

from gridlens_sim.components import battery_limits, battery_next_soc
from gridlens_sim.dispatch import dispatch

LIM = (500.0, 500.0)


def test_battery_limits_respect_soc(site):
    b = site.battery
    assert battery_limits(b, b.soc_min, 0.25) == (b.power_kw, 0.0)
    assert battery_limits(b, b.soc_max, 0.25) == (0.0, b.power_kw)


def test_full_discharge_reaches_soc_min_and_round_trip_loses(site):
    b = site.battery
    _, dis = battery_limits(b, 0.12, 0.25)
    assert battery_next_soc(b, 0.12, dis, 0.25) == pytest.approx(b.soc_min)
    up = battery_next_soc(b, 0.5, -200.0, 0.25)
    assert up > 0.5 and battery_next_soc(b, up, 200.0, 0.25) < 0.5


def test_grid_covers_shortfall(site):
    d = dispatch(800, 100, 0, LIM, site.diesels, [False, False], site.grid, True)
    assert d.grid_import_kw == pytest.approx(700) and d.shed_kw == 0 and d.balance_error() < 1e-6


def test_surplus_exports_up_to_limit_then_curtails(site):
    d = dispatch(100, 600, 0, LIM, site.diesels, [False, False], site.grid, True)
    assert d.grid_export_kw == pytest.approx(300) and d.curtailed_kw == pytest.approx(200)


def test_battery_request_is_clipped_and_logged(site):
    d = dispatch(500, 0, 900, (500, 400), site.diesels, [False, False], site.grid, True)
    assert d.battery_kw == pytest.approx(400) and d.corrections


def test_island_sheds_after_diesel_and_battery(site):
    d = dispatch(1500, 0, 0, LIM, site.diesels, [True, True], site.grid, False)
    assert sum(d.diesel_kw) == pytest.approx(600) and d.battery_kw == pytest.approx(500)
    assert d.shed_kw == pytest.approx(400) and d.grid_import_kw == 0 and d.balance_error() < 1e-6


def test_island_surplus_from_diesel_minimum_goes_into_battery(site):
    d = dispatch(50, 0, 0, LIM, site.diesels, [True, False], site.grid, False)
    assert d.diesel_kw[0] == pytest.approx(90) and d.battery_kw == pytest.approx(-40) and d.spill_kw == 0


def test_balance_holds_for_random_inputs(site):
    rng = np.random.default_rng(0)
    for _ in range(500):
        d = dispatch(rng.uniform(0, 1500), rng.uniform(0, 800), rng.uniform(-500, 500),
                     (rng.uniform(0, 500), rng.uniform(0, 500)), site.diesels,
                     [bool(x) for x in rng.random(2) < 0.5], site.grid, bool(rng.random() < 0.5))
        assert d.balance_error() < 1e-6
        assert d.shed_kw <= d.load_kw + 1e-9 and d.curtailed_kw <= d.pv_kw + 1e-9
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests_energy/test_dispatch.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `sim/gridlens_sim/components.py`**

```python
"""Battery and diesel unit state (spec §4.2, §5.2). Battery power: positive = discharge, negative = charge."""
from __future__ import annotations

from dataclasses import dataclass


def battery_limits(spec, soc: float, dt_h: float) -> tuple[float, float]:
    """(max charge kW, max discharge kW) at the battery terminals for one step."""
    max_dis = min(spec.power_kw, max(0.0, (soc - spec.soc_min) * spec.energy_kwh * spec.eta / dt_h))
    max_ch = min(spec.power_kw, max(0.0, (spec.soc_max - soc) * spec.energy_kwh / (spec.eta * dt_h)))
    return max_ch, max_dis


def battery_next_soc(spec, soc: float, power_kw: float, dt_h: float) -> float:
    if power_kw >= 0:
        stored = power_kw * dt_h / spec.eta        # delivering 1 kWh draws more than 1 kWh from the cells
    else:
        stored = power_kw * dt_h * spec.eta        # drawing 1 kWh stores less than 1 kWh
    return soc - stored / spec.energy_kwh


@dataclass
class DieselState:
    on: bool = False
    steps_in_state: int = 10**6
```

- [ ] **Step 4: Write `sim/gridlens_sim/dispatch.py`**

```python
"""Safety-layer dispatch for one step (spec §5.2).

The controller chooses a battery set-point. This layer clips it to SoC and power limits, then meets the residual in a
fixed order: grid import, committed diesel above minimum load, more battery discharge, and finally load shedding.
Surplus goes to export, then PV curtailment, then less battery discharge / more charge, then spill. Every change to
the controller's request is logged. The energy balance holds exactly.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Dispatch:
    load_kw: float
    pv_kw: float
    pv_used_kw: float
    curtailed_kw: float
    battery_kw: float
    grid_import_kw: float
    grid_export_kw: float
    diesel_kw: tuple[float, ...]
    shed_kw: float
    spill_kw: float
    corrections: list[str] = field(default_factory=list)

    def balance_error(self) -> float:
        supply = self.pv_used_kw + self.grid_import_kw + max(self.battery_kw, 0.0) + sum(self.diesel_kw)
        use = (self.load_kw - self.shed_kw) + max(-self.battery_kw, 0.0) + self.grid_export_kw + self.spill_kw
        return abs(supply - use)


def dispatch(load_kw: float, pv_kw: float, battery_request_kw: float, limits: tuple[float, float],
             diesels, diesel_on, grid, grid_available: bool) -> Dispatch:
    max_ch, max_dis = limits
    corrections: list[str] = []
    bat = float(np.clip(battery_request_kw, -max_ch, max_dis))
    if abs(bat - battery_request_kw) > 1e-6:
        corrections.append(f"battery {battery_request_kw:.1f} -> {bat:.1f} kW (SoC/power limit)")
    d_max = [d.p_max_kw if on else 0.0 for d, on in zip(diesels, diesel_on, strict=True)]
    diesel = [d.p_min_kw if on else 0.0 for d, on in zip(diesels, diesel_on, strict=True)]
    imp = exp = shed = spill = curt = 0.0
    residual = load_kw - pv_kw - bat - sum(diesel)          # > 0 shortfall, < 0 surplus
    if residual > 0:
        if grid_available:
            imp = min(residual, grid.import_limit_kw)
            residual -= imp
        for i in range(len(diesel)):
            add = min(residual, d_max[i] - diesel[i])
            diesel[i] += add
            residual -= add
        if residual > 1e-9 and bat < max_dis:
            add = min(residual, max_dis - bat)
            bat += add
            residual -= add
            corrections.append(f"battery raised by {add:.1f} kW to avoid shedding")
        if residual > 1e-9:
            shed = residual
            residual = 0.0
    elif residual < 0:
        surplus = -residual
        if grid_available:
            exp = min(surplus, grid.export_limit_kw)
            surplus -= exp
        curt = min(surplus, pv_kw)
        surplus -= curt
        if surplus > 1e-9:
            lower = min(surplus, bat + max_ch)
            bat -= lower
            surplus -= lower
            corrections.append(f"battery lowered by {lower:.1f} kW to absorb surplus")
        if surplus > 1e-9:
            spill = surplus
            corrections.append(f"spill {spill:.1f} kW (diesel minimum load)")
    return Dispatch(load_kw=float(load_kw), pv_kw=float(pv_kw), pv_used_kw=float(pv_kw - curt),
                    curtailed_kw=float(curt), battery_kw=float(bat), grid_import_kw=float(imp),
                    grid_export_kw=float(exp), diesel_kw=tuple(float(x) for x in diesel), shed_kw=float(shed),
                    spill_kw=float(spill), corrections=corrections)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests_energy/test_dispatch.py -q && uv run ruff check sim tests_energy`
Expected: `8 passed`; ruff clean.

- [ ] **Step 6: Commit**

```bash
git add sim/gridlens_sim/components.py sim/gridlens_sim/dispatch.py tests_energy/test_dispatch.py
git commit -m "Add battery model and safety-layer dispatch with exact energy balance

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Disruption scenarios

**Files:**
- Create: `sim/gridlens_sim/disruptions.py`
- Test: `tests_energy/test_disruptions.py`

**Interfaces:**
- Produces: `KINDS = ("blackout", "cloud_drop", "machine_start")`, `REGIMES = ("normal", "blackout", "cloud_drop", "machine_start", "combined")`, `Event(kind, start, duration, magnitude)` with `active(k)`, `Scenario(seed, regime, events=())` with `grid_available(k)`, `pv_factor(k)`, `extra_load_kw(k)`, `starting(k)`, `to_dict()`, `Scenario.from_dict(d)`, `NORMAL`, `generate(seed, regime, p_peak_kw, steps=96) -> Scenario`. Cloud-drop magnitude = remaining PV fraction (0.3); machine-start magnitude = extra kW.

- [ ] **Step 1: Write the failing tests**

`tests_energy/test_disruptions.py`:
```python
import json

import pytest

from gridlens_sim.disruptions import Scenario, generate


def test_normal_has_no_events():
    s = generate(1, "normal", 1000.0)
    assert s.events == () and s.grid_available(10) and s.pv_factor(10) == 1.0 and s.extra_load_kw(10) == 0


def test_same_seed_same_scenario():
    assert generate(7, "combined", 1000.0) == generate(7, "combined", 1000.0)
    assert len(generate(7, "combined", 1000.0).events) == 3


def test_blackout_window():
    s = generate(3, "blackout", 1000.0)
    e = s.events[0]
    assert 1 <= e.duration <= 16
    assert not s.grid_available(e.start) and s.grid_available(e.start + e.duration)
    assert s.starting(e.start) == (e,)


def test_cloud_and_machine_ranges():
    for seed in range(50):
        c = generate(seed, "cloud_drop", 1000.0).events[0]
        assert 2 <= c.duration <= 12 and c.start >= 36 and c.start + c.duration <= 64
        m = generate(seed, "machine_start", 1000.0).events[0]
        assert 150 <= m.magnitude <= 350


def test_json_round_trip():
    s = generate(5, "combined", 1000.0)
    assert Scenario.from_dict(json.loads(json.dumps(s.to_dict()))) == s


def test_unknown_regime_is_rejected():
    with pytest.raises(ValueError):
        generate(1, "earthquake", 1000.0)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests_energy/test_disruptions.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `sim/gridlens_sim/disruptions.py`**

```python
"""Seeded disruption scenarios (spec §5.4). A scenario is data: it can be stored as JSON and replayed exactly."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

KINDS = ("blackout", "cloud_drop", "machine_start")
REGIMES = ("normal", "blackout", "cloud_drop", "machine_start", "combined")


@dataclass(frozen=True)
class Event:
    kind: str
    start: int          # step within the day
    duration: int       # steps
    magnitude: float    # cloud_drop: remaining PV fraction; machine_start: extra kW; blackout: unused

    def active(self, k: int) -> bool:
        return self.start <= k < self.start + self.duration


@dataclass(frozen=True)
class Scenario:
    seed: int
    regime: str
    events: tuple[Event, ...] = ()

    def grid_available(self, k: int) -> bool:
        return not any(e.kind == "blackout" and e.active(k) for e in self.events)

    def pv_factor(self, k: int) -> float:
        return min([e.magnitude for e in self.events if e.kind == "cloud_drop" and e.active(k)], default=1.0)

    def extra_load_kw(self, k: int) -> float:
        return float(sum(e.magnitude for e in self.events if e.kind == "machine_start" and e.active(k)))

    def starting(self, k: int) -> tuple[Event, ...]:
        return tuple(e for e in self.events if e.start == k)

    def to_dict(self) -> dict:
        return {"seed": self.seed, "regime": self.regime, "events": [asdict(e) for e in self.events]}

    @classmethod
    def from_dict(cls, d: dict) -> Scenario:
        return cls(seed=int(d["seed"]), regime=d["regime"], events=tuple(Event(**e) for e in d["events"]))


NORMAL = Scenario(seed=0, regime="normal")


def generate(seed: int, regime: str, p_peak_kw: float, steps: int = 96) -> Scenario:
    if regime not in REGIMES:
        raise ValueError(f"unknown regime {regime!r}; expected one of {REGIMES}")
    if regime == "normal":
        return Scenario(seed, regime)
    rng = np.random.default_rng(seed)
    events = []
    for kind in (KINDS if regime == "combined" else (regime,)):
        if kind == "blackout":                                  # 15 min to 4 h, starting from 07:00
            dur = int(rng.integers(1, 17))
            events.append(Event(kind, int(rng.integers(28, steps - dur)), dur, 0.0))
        elif kind == "cloud_drop":                              # 30 min to 3 h inside 09:00-16:00
            dur = int(rng.integers(2, 13))
            events.append(Event(kind, int(rng.integers(36, 64 - dur)), dur, 0.3))
        else:                                                   # 0.15-0.35 x peak for 30 min to 2 h
            dur = int(rng.integers(2, 9))
            size = float(rng.uniform(0.15, 0.35)) * p_peak_kw
            events.append(Event(kind, int(rng.integers(28, steps - dur)), dur, size))
    return Scenario(seed, regime, tuple(events))
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests_energy/test_disruptions.py -q && uv run ruff check sim tests_energy`
Expected: `6 passed`; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add sim/gridlens_sim/disruptions.py tests_energy/test_disruptions.py
git commit -m "Add seeded disruption scenarios (blackout, cloud drop, machine start-up, combined)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Islanded frequency transient and UFLS

**Files:**
- Create: `sim/gridlens_sim/frequency.py`
- Test: `tests_energy/test_frequency.py`

**Interfaces:**
- Consumes: `FrequencySpec` (Task 1).
- Produces: `Transient(deficit_kw, nadir_hz, rocof_hz_s, final_hz, stages_tripped: tuple[int, ...], shed_kw)`, `simulate_transient(deficit_kw, *, spec, online_rating_kw, inertia_h_s, diesel_headroom_kw, battery_headroom_kw, stage_kw: tuple[float, ...], dt=0.01, t_end=20.0) -> Transient`. Stage `i` sheds `stage_kw[i]` when the deviation falls below `-spec.ufls_stages[i]` (per unit).

- [ ] **Step 1: Write the failing tests**

`tests_energy/test_frequency.py`:
```python
import pytest

from gridlens_sim.frequency import simulate_transient

STAGES = (100.0, 200.0, 300.0)


def run(site, deficit, **kw):
    args = dict(online_rating_kw=800.0, inertia_h_s=1.5, diesel_headroom_kw=300.0,
                battery_headroom_kw=500.0, stage_kw=STAGES)
    args.update(kw)
    return simulate_transient(deficit, spec=site.frequency, **args)


def test_no_deficit_stays_nominal(site):
    r = run(site, 0.0)
    assert r.nadir_hz == 60.0 and r.stages_tripped == () and r.shed_kw == 0


def test_bigger_deficit_gives_a_deeper_nadir(site):
    assert run(site, 400).nadir_hz < run(site, 100).nadir_hz < 60.0


def test_battery_headroom_raises_the_nadir(site):
    assert run(site, 400, battery_headroom_kw=500).nadir_hz > run(site, 400, battery_headroom_kw=50).nadir_hz


def test_stages_trip_in_order(site):
    r = run(site, 900, battery_headroom_kw=0.0, diesel_headroom_kw=0.0)
    assert r.stages_tripped == (0, 1, 2)
    assert r.shed_kw == pytest.approx(sum(STAGES))


def test_no_grid_forming_source_collapses(site):
    r = run(site, 100, online_rating_kw=0.0)
    assert r.nadir_hz == 0.0 and r.stages_tripped == (0, 1, 2)


def test_covered_deficit_recovers_without_overshoot(site):
    r = run(site, 200)
    assert 60.0 * (1 - site.frequency.ufls_stages[0]) < r.final_hz < 60.0 * 1.005
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests_energy/test_frequency.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `sim/gridlens_sim/frequency.py`**

```python
"""Single-bus frequency transient for an islanded park (spec §5.3).

Aggregate swing equation in per unit on the online rating S:  2H d(df)/dt = (P_response - deficit)/S - D*df.
The battery (grid-forming inverter) and diesel governors respond as first-order lags up to their headroom.
Under-frequency load shedding (UFLS) trips stage i when df <= -threshold_i. Parameters are representative and
labelled as assumed in the site configuration.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Transient:
    deficit_kw: float
    nadir_hz: float
    rocof_hz_s: float
    final_hz: float
    stages_tripped: tuple[int, ...]
    shed_kw: float


def simulate_transient(deficit_kw: float, *, spec, online_rating_kw: float, inertia_h_s: float,
                       diesel_headroom_kw: float, battery_headroom_kw: float, stage_kw: tuple[float, ...],
                       dt: float = 0.01, t_end: float = 20.0) -> Transient:
    f0 = spec.nominal_hz
    if deficit_kw <= 0:
        return Transient(deficit_kw, f0, 0.0, f0, (), 0.0)
    if online_rating_kw <= 0:
        return Transient(deficit_kw, 0.0, float("inf"), 0.0, tuple(range(len(stage_kw))), float(sum(stage_kw)))
    s, h = online_rating_kw, max(inertia_h_s, 0.1)
    df = nadir = rocof = 0.0
    p_bat = p_gov = shed = 0.0
    tripped: list[int] = []
    for step in range(int(t_end / dt)):
        need = max(deficit_kw - shed, 0.0)
        p_bat += (min(battery_headroom_kw, need) - p_bat) * dt / spec.battery_response_s
        # governors pick up only what the fast battery response has not covered (no double counting)
        p_gov += (min(diesel_headroom_kw, max(need - p_bat, 0.0)) - p_gov) * dt / spec.governor_response_s
        ddf = ((p_bat + p_gov + shed - deficit_kw) / s - spec.load_damping * df) / (2.0 * h)
        if step == 0:
            rocof = abs(ddf) * f0
        df += ddf * dt
        nadir = min(nadir, df)
        for i, threshold in enumerate(spec.ufls_stages[:len(stage_kw)]):
            if i not in tripped and df <= -threshold:
                tripped.append(i)
                shed += stage_kw[i]
    return Transient(deficit_kw, f0 * (1.0 + nadir), rocof, f0 * (1.0 + df), tuple(tripped), float(shed))
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests_energy/test_frequency.py -q && uv run ruff check sim tests_energy`
Expected: `6 passed`; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add sim/gridlens_sim/frequency.py tests_energy/test_frequency.py
git commit -m "Add islanded frequency transient with staged under-frequency load shedding

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Forecaster protocol, perfect and seasonal-naive forecasters

**Files:**
- Create: `sim/gridlens_sim/forecast.py`
- Test: `tests_energy/test_forecast.py`

**Interfaces:**
- Consumes: `ParkSeries` (Task 4), constants (Task 1).
- Produces: `Forecaster` protocol with `forecast(t: int) -> np.ndarray` of shape `(2, H, 5)` — axis 0 `[load, pv]`, axis 1 positions `t+1 … t+H`, axis 2 quantiles `QUANTILES`; `PerfectForecaster(series)`, `SeasonalNaiveForecaster(series, lookback_days=28)`.

- [ ] **Step 1: Write the failing tests**

`tests_energy/test_forecast.py`:
```python
import dataclasses

import numpy as np

from gridlens_sim.forecast import PerfectForecaster, SeasonalNaiveForecaster
from gridlens_sim.testing import synthetic_series


def test_perfect_forecast_is_the_future(site):
    s = synthetic_series(site, days=3)
    out = PerfectForecaster(s).forecast(10)
    assert out.shape == (2, 96, 5)
    np.testing.assert_allclose(out[0, :, 2], s.load_kw[11:107])
    np.testing.assert_allclose(out[1, :, 0], s.pv_kw[11:107])


def test_perfect_forecast_pads_at_the_end(site):
    s = synthetic_series(site, days=2)
    out = PerfectForecaster(s).forecast(len(s) - 2)
    assert out.shape == (2, 96, 5) and np.all(out[0, :, 2] == s.load_kw[-1])


def test_seasonal_naive_uses_only_the_past(site):
    s = synthetic_series(site, days=21)
    t = 14 * 96 + 40
    a = SeasonalNaiveForecaster(s).forecast(t)
    load, pv = s.load_kw.copy(), s.pv_kw.copy()
    load[t + 1:], pv[t + 1:] = 0.0, 0.0
    b = SeasonalNaiveForecaster(dataclasses.replace(s, load_kw=load, pv_kw=pv)).forecast(t)
    np.testing.assert_allclose(a, b)


def test_seasonal_naive_quantiles_ordered_and_pv_nonnegative(site):
    out = SeasonalNaiveForecaster(synthetic_series(site, days=21)).forecast(15 * 96)
    assert np.all(np.diff(out, axis=2) >= -1e-9) and out[1].min() >= 0
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests_energy/test_forecast.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `sim/gridlens_sim/forecast.py`**

```python
"""Forecast providers for the simulator and controllers (spec §4.3).

A forecast issued at position t covers positions t+1 ... t+H for load and PV at the five quantiles. Forecasts know
nothing about injected disruptions.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np

from .constants import DAY, H, QUANTILES, WEEK
from .series import ParkSeries


class Forecaster(Protocol):
    def forecast(self, t: int) -> np.ndarray: ...


def _ahead(n: int, t: int) -> np.ndarray:
    return np.minimum(np.arange(t + 1, t + H + 1), n - 1)


class PerfectForecaster:
    """Oracle forecasts (all quantiles equal the truth). For the perfect-foresight bound and tests only."""

    def __init__(self, series: ParkSeries):
        self.load, self.pv = series.load_kw, series.pv_kw

    def forecast(self, t: int) -> np.ndarray:
        idx = _ahead(len(self.load), t)
        out = np.empty((2, H, len(QUANTILES)))
        out[0] = self.load[idx][:, None]
        out[1] = self.pv[idx][:, None]
        return out


class SeasonalNaiveForecaster:
    """Load: same quarter-hour one week earlier. PV: same quarter-hour one day earlier. The spread is the empirical
    quantiles of the seasonal error over the last `lookback_days`, all measured before t."""

    def __init__(self, series: ParkSeries, lookback_days: int = 28):
        self.ys = (series.load_kw, series.pv_kw)
        self.seasons = (WEEK, DAY)
        self.lookback = lookback_days * DAY

    def forecast(self, t: int) -> np.ndarray:
        out = np.empty((2, H, len(QUANTILES)))
        idx = np.arange(t + 1, t + H + 1)
        for j, (y, season) in enumerate(zip(self.ys, self.seasons, strict=True)):
            src = np.clip(np.minimum(idx - season, t), 0, None)
            point = y[src]
            lo = max(season, t - self.lookback + 1)
            if t - lo >= DAY:
                qs = np.quantile(y[lo:t + 1] - y[lo - season:t + 1 - season], QUANTILES)
            else:
                qs = np.zeros(len(QUANTILES))
            vals = point[:, None] + qs[None, :]
            if j == 1:
                vals = np.where(point[:, None] > 0, np.clip(vals, 0.0, None), 0.0)
            out[j] = np.sort(vals, axis=1)
        return out
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests_energy/test_forecast.py -q && uv run ruff check sim tests_energy`
Expected: `4 passed`; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add sim/gridlens_sim/forecast.py tests_energy/test_forecast.py
git commit -m "Add forecaster protocol with perfect and seasonal-naive quantile forecasters

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: `MicrogridEnv`

**Files:**
- Create: `sim/gridlens_sim/env.py`
- Test: `tests_energy/test_env.py`

**Interfaces:**
- Consumes: everything from Tasks 1–8.
- Produces: `Action(battery: float, defer: float)`; `Observation(k, timestamp, soc, load_kw, pv_kw, band, price, grid_available, backlog_kwh, due_kwh, peak_import_kw, diesel_on, forecast, price_ahead, band_ahead)`; `StepRecord` (fields listed in the code); `OBS_DIM = 53`; `obs_vector(obs, site, price_scale) -> np.ndarray[float32]`; `MicrogridEnv(site, series, forecaster, tenants=DEFAULT_TENANTS, day_starts=None, scenario_sampler=None, steps=96, defer_deadline=16)` with Gymnasium `reset(seed=None, options=None)` (options: `day_start`, `scenario`, `soc`, `commitment` bool array `(steps, n_diesels)`), `step(np.ndarray)`, `step_action(Action)`, attributes `reward_scale`, `price_scale`, `series`, `site`, `tenants`. `info` holds `"record": StepRecord` and `"observation": Observation`.

- [ ] **Step 1: Write the failing tests**

`tests_energy/test_env.py`:
```python
import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env

from gridlens_sim.disruptions import Event, Scenario
from gridlens_sim.env import OBS_DIM, MicrogridEnv
from gridlens_sim.forecast import PerfectForecaster
from gridlens_sim.testing import synthetic_series

ZERO = np.array([0.0, 0.0], dtype=np.float32)


def make_env(site, days=7):
    s = synthetic_series(site, days=days)
    return MicrogridEnv(site, s, PerfectForecaster(s))


def test_gymnasium_api(site):
    env = make_env(site)
    check_env(env, skip_render_check=True)
    obs, _ = env.reset(seed=0)
    assert obs.shape == (OBS_DIM,) and obs.dtype == np.float32


def test_energy_balance_and_soc_bounds_under_random_actions(site):
    env = make_env(site)
    env.reset(seed=1, options={"day_start": 96})
    rng = np.random.default_rng(0)
    steps = 0
    while True:
        _, _, term, _, info = env.step(rng.uniform([-1, 0], [1, 1]).astype(np.float32))
        r = info["record"]
        steps += 1
        assert site.battery.soc_min - 1e-9 <= r.soc <= site.battery.soc_max + 1e-9
        supply = r.pv_used_kw + r.grid_import_kw + max(r.battery_kw, 0) + r.diesel_kw
        use = r.load_kw - r.shed_kw + max(-r.battery_kw, 0) + r.grid_export_kw + r.spill_kw
        assert abs(supply - use) < 1e-6
        if term:
            break
    assert steps == 96


def test_deferred_energy_is_all_served_by_the_end_of_the_day(site):
    env = make_env(site)
    env.reset(options={"day_start": 96})
    served = 0.0
    for _ in range(96):
        served += env.step(np.array([0.0, 1.0], dtype=np.float32))[4]["record"].served_flex_kwh
    assert served == pytest.approx(env.series.flex_kw[96:192].sum() * 0.25)


def test_evening_blackout_islands_starts_diesel_and_records_frequency(site):
    env = make_env(site)
    sc = Scenario(seed=0, regime="blackout", events=(Event("blackout", 72, 16, 0.0),))
    env.reset(options={"day_start": 96, "scenario": sc, "soc": 0.5})
    recs = [env.step(ZERO)[4]["record"] for _ in range(96)]
    assert all(r.grid_import_kw == 0 and r.grid_export_kw == 0 for r in recs[72:88])
    assert any(r.diesel_on > 0 for r in recs[72:88])
    assert recs[72].nadir_hz is not None and recs[72].nadir_hz < 60.0
    assert recs[71].nadir_hz is None


def test_reward_is_minus_scaled_total_cost(site):
    env = make_env(site)
    env.reset(options={"day_start": 96})
    _, reward, _, _, info = env.step(ZERO)
    assert reward == pytest.approx(-info["record"].total_cost / env.reward_scale)


def test_step_after_the_end_is_an_error(site):
    env = make_env(site)
    env.reset(options={"day_start": 96})
    for _ in range(96):
        env.step(ZERO)
    with pytest.raises(RuntimeError):
        env.step(ZERO)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests_energy/test_env.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'gridlens_sim.env'`.

- [ ] **Step 3: Write `sim/gridlens_sim/env.py`**

```python
"""MicrogridEnv: one industrial-park day in 15-minute steps (spec §5).

Action: [battery set-point in -1..1 of rated power (positive = discharge), share of deferrable flexible demand to
postpone in 0..1]. Each step: flexible demand is postponed or served (postponed energy must be served within
`defer_deadline` steps and by the end of the day); if an event starts while islanded, a frequency transient is
simulated and UFLS stages shed tenants; diesel units follow the commitment, with emergency starts when islanded;
the safety layer dispatches the step with an exact energy balance; costs, emissions and the reward are recorded.
"""
from __future__ import annotations

from dataclasses import dataclass

import gymnasium as gym
import numpy as np
import pandas as pd
from gymnasium import spaces

from .components import DieselState, battery_limits, battery_next_soc
from .constants import DAY, DT_H, H
from .disruptions import NORMAL
from .dispatch import dispatch
from .frequency import Transient, simulate_transient
from .tenants import DEFAULT_TENANTS, PRIORITY_WEIGHT, SHED_CLASS_ORDER, allocate_shed


@dataclass(frozen=True)
class Action:
    battery: float
    defer: float


@dataclass(frozen=True)
class Observation:
    k: int
    timestamp: pd.Timestamp
    soc: float
    load_kw: float
    pv_kw: float
    band: str
    price: float
    grid_available: bool
    backlog_kwh: float
    due_kwh: float
    peak_import_kw: float
    diesel_on: tuple[bool, ...]
    forecast: np.ndarray            # (2, H, 5)
    price_ahead: np.ndarray         # (H,)
    band_ahead: tuple[str, ...]


@dataclass(frozen=True)
class StepRecord:
    k: int
    timestamp: str
    band: str
    price: float
    grid_available: bool
    soc: float                      # after the step
    load_kw: float                  # demand to serve this step, after flexible shifting, before shedding
    pv_kw: float
    pv_used_kw: float
    curtailed_kw: float
    battery_kw: float
    battery_request_kw: float
    grid_import_kw: float
    grid_export_kw: float
    diesel_kw: float
    diesel_on: int
    spill_kw: float
    shed_kw: float
    tenant_demand_kw: tuple[float, ...]
    shed_by_tenant: tuple[float, ...]
    deferred_kwh: float
    served_flex_kwh: float
    energy_cost: float
    demand_cost: float
    fuel_cost: float
    startup_cost: float
    degradation_cost: float
    carbon_cost: float
    unserved_cost: float
    safety_penalty: float
    total_cost: float
    co2_kg: float
    nox_g: float
    pm_g: float
    fuel_l: float
    nadir_hz: float | None
    stages_tripped: tuple[int, ...]
    corrections: tuple[str, ...]
    reward: float


OBS_DIM = 13 + 5 * 8


def _blocks(a: np.ndarray) -> np.ndarray:
    return a.reshape(8, H // 8).mean(axis=1)


def obs_vector(obs: Observation, site, price_scale: float) -> np.ndarray:
    p = site.p_peak_kw
    ts = obs.timestamp
    hour = ts.hour + ts.minute / 60
    fc = obs.forecast / p
    head = [np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24),
            np.sin(2 * np.pi * ts.dayofweek / 7), np.cos(2 * np.pi * ts.dayofweek / 7),
            obs.soc, obs.load_kw / p, obs.pv_kw / p, obs.price / price_scale, float(obs.grid_available),
            obs.backlog_kwh / p, obs.due_kwh / p, obs.peak_import_kw / p,
            sum(obs.diesel_on) / max(1, len(obs.diesel_on))]
    tail = [_blocks(fc[0, :, 2]), _blocks(fc[1, :, 2]), _blocks(fc[0, :, 4] - fc[1, :, 0]),
            _blocks(fc[0, :, 0] - fc[1, :, 4]), _blocks(obs.price_ahead / price_scale)]
    return np.concatenate([np.asarray(head, dtype=float), *tail]).astype(np.float32)


class MicrogridEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, site, series, forecaster, tenants=DEFAULT_TENANTS, day_starts=None,
                 scenario_sampler=None, steps: int = DAY, defer_deadline: int = 16):
        super().__init__()
        self.site, self.series, self.forecaster = site, series, forecaster
        self.tenants = tuple(tenants)
        self.steps, self.deadline = steps, defer_deadline
        self.day_starts = (list(day_starts) if day_starts is not None
                           else list(range(0, len(series) - steps + 1, steps)))
        self.scenario_sampler = scenario_sampler
        self.price_scale = float(np.max(series.price))
        self.reward_scale = site.p_peak_kw * DT_H * self.price_scale
        self._weights = np.array([PRIORITY_WEIGHT[t.priority] for t in self.tenants])
        self._groups = [np.array([t.priority == g for t in self.tenants]) for g in SHED_CLASS_ORDER]
        self.observation_space = spaces.Box(-np.inf, np.inf, shape=(OBS_DIM,), dtype=np.float32)
        self.action_space = spaces.Box(np.array([-1.0, 0.0], dtype=np.float32),
                                       np.array([1.0, 1.0], dtype=np.float32))
        self.k = steps     # no episode until reset()

    # ------------------------------------------------------------------ Gymnasium API

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        opts = options or {}
        self.start = (int(opts["day_start"]) if "day_start" in opts
                      else int(self.np_random.choice(self.day_starts)))
        if "scenario" in opts:
            self.scenario = opts["scenario"]
        elif self.scenario_sampler is not None:
            self.scenario = self.scenario_sampler(self.np_random)
        else:
            self.scenario = NORMAL
        n = len(self.site.diesels)
        commitment = opts.get("commitment")
        self.commitment = (np.zeros((self.steps, n), dtype=bool) if commitment is None
                           else np.asarray(commitment, dtype=bool))
        if self.commitment.shape != (self.steps, n):
            raise ValueError(f"commitment must have shape {(self.steps, n)}, got {self.commitment.shape}")
        self.k = 0
        self.soc = float(opts.get("soc", 0.5))
        self.backlog: list[list[float]] = []          # [energy kWh, due step]
        self.diesel = [DieselState() for _ in range(n)]
        self.peak_import = 0.0
        self.rotation = 0
        self.prev = {"import": 0.0, "pv": 0.0, "battery": 0.0, "diesel": [0.0] * n}
        self._obs = self.observe()
        return obs_vector(self._obs, self.site, self.price_scale), {"observation": self._obs}

    def step(self, action):
        a = np.asarray(action, dtype=float).reshape(-1)
        return self.step_action(Action(battery=float(np.clip(a[0], -1.0, 1.0)),
                                       defer=float(np.clip(a[1], 0.0, 1.0))))

    # ------------------------------------------------------------------ simulation

    def observe(self) -> Observation:
        s, k = self.series, self.k
        t = self.start + k
        ahead = np.minimum(np.arange(t + 1, t + H + 1), len(s) - 1)
        return Observation(
            k=k, timestamp=s.index[t], soc=self.soc,
            load_kw=float(s.load_kw[t] + self.scenario.extra_load_kw(k)),
            pv_kw=float(s.pv_kw[t] * self.scenario.pv_factor(k)),
            band=str(s.band[t]), price=float(s.price[t]), grid_available=self.scenario.grid_available(k),
            backlog_kwh=float(sum(c[0] for c in self.backlog)),
            due_kwh=float(sum(c[0] for c in self.backlog if c[1] <= k)),
            peak_import_kw=self.peak_import, diesel_on=tuple(d.on for d in self.diesel),
            forecast=self.forecaster.forecast(t), price_ahead=s.price[ahead], band_ahead=tuple(s.band[ahead]))

    def step_action(self, act: Action):
        if self.k >= self.steps:
            raise RuntimeError("episode finished; call reset()")
        site, s, o, k = self.site, self.series, self._obs, self.k
        t = self.start + k
        corrections: list[str] = []

        # 1. flexible demand
        last = k == self.steps - 1
        new_flex = float(s.flex_kw[t])
        due = [c for c in self.backlog if c[1] <= k or last]
        open_ = [c for c in self.backlog if not (c[1] <= k or last)]
        defer = 0.0 if last else act.defer
        deferrable = new_flex * DT_H + sum(c[0] for c in open_)
        postponed = defer * deferrable
        served_flex = sum(c[0] for c in due) + deferrable - postponed
        self.backlog = [[c[0] * defer, c[1]] for c in open_ if c[0] * defer > 1e-12]
        if defer * new_flex * DT_H > 1e-12:
            self.backlog.append([defer * new_flex * DT_H, k + self.deadline])
        load = o.load_kw - new_flex + served_flex / DT_H
        tenant_demand = self._tenant_kw(t, load)

        # 2. frequency transient for events starting while islanded (units online before the event)
        max_ch, max_dis = battery_limits(site.battery, self.soc, DT_H)
        transient = self._transient(k, o, max_dis, tenant_demand)
        ufls = np.zeros(len(self.tenants))
        if transient is not None and transient.stages_tripped:
            for i in transient.stages_tripped:
                ufls[self._groups[i]] = tenant_demand[self._groups[i]]
            corrections.append(f"UFLS stages {list(transient.stages_tripped)} tripped")

        # 3. diesel commitment and emergency starts
        started = self._commit_diesel(k, load - ufls.sum(), o.pv_kw, max_dis, o.grid_available, corrections)

        # 4. dispatch through the safety layer
        request = act.battery * site.battery.power_kw
        d = dispatch(load - ufls.sum(), o.pv_kw, request, (max_ch, max_dis), site.diesels,
                     [st.on for st in self.diesel], site.grid, o.grid_available)
        if d.balance_error() > 1e-6:
            raise RuntimeError(f"energy balance broken at step {k}: {d}")
        corrections += d.corrections
        shed = ufls + allocate_shed(d.shed_kw, tenant_demand - ufls, self.tenants, self.rotation)
        if shed.sum() > 1e-9:
            self.rotation += 1
        b = site.battery
        self.soc = float(np.clip(battery_next_soc(b, self.soc, d.battery_kw, DT_H), b.soc_min, b.soc_max))

        # 5. costs and emissions
        tariff = site.tariff
        energy_cost = (d.grid_import_kw * o.price - d.grid_export_kw * tariff.export_price) * DT_H
        new_peak = max(self.peak_import, d.grid_import_kw)
        demand_cost = (new_peak - self.peak_import) * tariff.demand_charge_per_kw_month / 30.0
        self.peak_import = new_peak
        fuel_l = fuel_cost = co2_diesel = nox = pm = 0.0
        for spec, p, st in zip(site.diesels, d.diesel_kw, self.diesel, strict=True):
            if st.on:
                litres = spec.fuel_l(p, DT_H)
                fuel_l += litres
                fuel_cost += litres * spec.fuel_price_per_l
                co2_diesel += litres * spec.co2_kg_per_l
                nox += p * DT_H * spec.nox_g_per_kwh
                pm += p * DT_H * spec.pm_g_per_kwh
        startup_cost = float(sum(spec.startup_cost for spec, st in zip(site.diesels, started, strict=True) if st))
        degradation = abs(d.battery_kw) * DT_H * b.degradation_cost_per_kwh
        co2 = d.grid_import_kw * DT_H * site.grid.co2_kg_per_kwh + co2_diesel
        carbon_cost = co2 * site.carbon_price_per_kg
        unserved_cost = float((shed * self._weights).sum()) * DT_H * site.voll_per_kwh
        safety_penalty = abs(d.battery_kw - request) * DT_H * self.price_scale * 0.5
        total = (energy_cost + demand_cost + fuel_cost + startup_cost + degradation + carbon_cost
                 + unserved_cost + safety_penalty)
        reward = -total / self.reward_scale

        rec = StepRecord(
            k=k, timestamp=o.timestamp.isoformat(), band=o.band, price=o.price, grid_available=o.grid_available,
            soc=self.soc, load_kw=load, pv_kw=o.pv_kw, pv_used_kw=d.pv_used_kw, curtailed_kw=d.curtailed_kw,
            battery_kw=d.battery_kw, battery_request_kw=request, grid_import_kw=d.grid_import_kw,
            grid_export_kw=d.grid_export_kw, diesel_kw=float(sum(d.diesel_kw)),
            diesel_on=int(sum(st.on for st in self.diesel)), spill_kw=d.spill_kw, shed_kw=float(shed.sum()),
            tenant_demand_kw=tuple(float(x) for x in tenant_demand),
            shed_by_tenant=tuple(float(x) for x in shed), deferred_kwh=postponed, served_flex_kwh=served_flex,
            energy_cost=energy_cost, demand_cost=demand_cost, fuel_cost=fuel_cost, startup_cost=startup_cost,
            degradation_cost=degradation, carbon_cost=carbon_cost, unserved_cost=unserved_cost,
            safety_penalty=safety_penalty, total_cost=total, co2_kg=co2, nox_g=nox, pm_g=pm, fuel_l=fuel_l,
            nadir_hz=None if transient is None else transient.nadir_hz,
            stages_tripped=() if transient is None else transient.stages_tripped,
            corrections=tuple(corrections), reward=reward)

        self.prev = {"import": d.grid_import_kw, "pv": d.pv_used_kw, "battery": d.battery_kw,
                     "diesel": list(d.diesel_kw)}
        self.k += 1
        terminated = self.k >= self.steps
        if not terminated:
            self._obs = self.observe()
        return (obs_vector(self._obs, site, self.price_scale), reward, terminated, False,
                {"record": rec, "observation": self._obs})

    # ------------------------------------------------------------------ helpers

    def _tenant_kw(self, t: int, load: float) -> np.ndarray:
        base = self.series.tenant_kw[t]
        total = float(base.sum())
        if total <= 1e-9:
            return np.array([tn.share for tn in self.tenants]) * load
        return base * (load / total)

    def _transient(self, k: int, o: Observation, max_dis: float, tenant_demand: np.ndarray) -> Transient | None:
        starting = self.scenario.starting(k)
        if not starting or o.grid_available:
            return None
        deficit = 0.0
        for e in starting:
            if e.kind == "blackout":
                deficit += self.prev["import"]
            elif e.kind == "cloud_drop":
                deficit += self.prev["pv"] * (1.0 - e.magnitude)
            elif e.kind == "machine_start":
                deficit += e.magnitude
        site = self.site
        online = [(spec, p) for spec, st, p in zip(site.diesels, self.diesel, self.prev["diesel"], strict=True) if st.on]
        rating = sum(spec.p_max_kw for spec, _ in online) + site.battery.power_kw
        inertia = (sum(spec.inertia_h_s * spec.p_max_kw for spec, _ in online)
                   + site.frequency.battery_inertia_h_s * site.battery.power_kw) / rating
        return simulate_transient(
            deficit, spec=site.frequency, online_rating_kw=rating, inertia_h_s=inertia,
            diesel_headroom_kw=sum(spec.p_max_kw - p for spec, p in online),
            battery_headroom_kw=max(0.0, max_dis - self.prev["battery"]),
            stage_kw=tuple(float(tenant_demand[g].sum()) for g in self._groups))

    def _commit_diesel(self, k: int, load: float, pv: float, max_dis: float, grid_ok: bool,
                       corrections: list[str]) -> list[bool]:
        diesels = self.site.diesels
        want = [bool(x) for x in self.commitment[k]]
        emergency = [False] * len(want)
        if not grid_ok:
            shortfall = load - pv - max_dis - sum(spec.p_max_kw for spec, w in zip(diesels, want, strict=True) if w)
            for i, spec in enumerate(diesels):
                if shortfall <= 1e-9:
                    break
                if not want[i]:
                    want[i] = emergency[i] = True
                    shortfall -= spec.p_max_kw
        started = []
        for i, (spec, st) in enumerate(zip(diesels, self.diesel, strict=True)):
            target = want[i]
            if st.on and not target and st.steps_in_state < spec.min_up_steps:
                target = True
            if not st.on and target and st.steps_in_state < spec.min_down_steps and not emergency[i]:
                target = False
            if emergency[i] and not st.on:
                corrections.append(f"emergency start {spec.name}")
            started.append(target and not st.on)
            if target != st.on:
                st.on, st.steps_in_state = target, 0
            else:
                st.steps_in_state += 1
        return started
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests_energy/test_env.py -q && uv run ruff check sim tests_energy`
Expected: `6 passed` (Gymnasium may print a warning that the action space is not symmetric; that is expected). Ruff clean.

- [ ] **Step 5: Run the whole energy suite**

Run: `uv run pytest tests_energy -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add sim/gridlens_sim/env.py tests_energy/test_env.py
git commit -m "Add MicrogridEnv with flexible demand, islanding, UFLS, emergency diesel and costed reward

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Controller protocol, baselines and episode runner

**Files:**
- Create: `control/gridlens_control/base.py`, `control/gridlens_control/baselines.py`, `control/gridlens_control/runner.py`
- Test: `tests_energy/test_baselines.py`

**Interfaces:**
- Consumes: `MicrogridEnv`, `Action`, `Observation`, `StepRecord` (Task 9), `Scenario`, `NORMAL`, `generate` (Task 6).
- Produces: `Controller` protocol (`name: str`, `reset()`, `act(obs) -> Action`); `NoBattery()`, `RuleTOU(site)`, `GreedySelf(site)`; `EpisodeResult(controller, day, scenario, records, priorities, battery_energy_kwh, nominal_hz, decision_ms)` with `kpis() -> dict[str, float]` (keys: `operating_cost, total_cost, energy_cost, demand_cost, fuel_cost, peak_import_kw, import_kwh, export_kwh, curtailed_kwh, co2_kg, nox_g, pm_g, diesel_unit_hours, unserved_kwh, critical_served_pct, shed_events, battery_cycles, min_nadir_hz, safety_corrections, decision_ms_mean`); `run_episode(env, controller, day_start, scenario=NORMAL, *, commitment=None, soc0=0.5) -> EpisodeResult`; `summarise(env, controllers, day_starts, regimes, seeds) -> pd.DataFrame`.

- [ ] **Step 1: Write the failing tests**

`tests_energy/test_baselines.py`:
```python
import numpy as np
import pandas as pd
import pytest

from gridlens_control.baselines import GreedySelf, NoBattery, RuleTOU
from gridlens_control.runner import run_episode, summarise
from gridlens_sim.env import MicrogridEnv, Observation
from gridlens_sim.forecast import PerfectForecaster
from gridlens_sim.testing import synthetic_series


def fake_obs(site, band="mid", soc=0.5, load=400.0, pv=0.0, grid=True):
    return Observation(k=0, timestamp=pd.Timestamp("2018-11-05 12:00", tz=site.timezone), soc=soc, load_kw=load,
                       pv_kw=pv, band=band, price=100.0, grid_available=grid, backlog_kwh=0.0, due_kwh=0.0,
                       peak_import_kw=0.0, diesel_on=(False, False), forecast=np.zeros((2, 96, 5)),
                       price_ahead=np.zeros(96), band_ahead=("mid",) * 96)


def test_rule_tou_charges_in_light_band(site):
    assert RuleTOU(site).act(fake_obs(site, band="light")).battery == -1.0
    assert RuleTOU(site).act(fake_obs(site, band="light", soc=site.battery.soc_max)).battery == 0.0


def test_rule_tou_discharges_in_peak_to_cover_net_load(site):
    assert RuleTOU(site).act(fake_obs(site, band="peak", load=400, pv=100)).battery == pytest.approx(0.6)
    assert RuleTOU(site).act(fake_obs(site, band="mid")).battery == 0.0


def test_greedy_follows_net_load_and_never_charges_from_grid(site):
    g = GreedySelf(site)
    assert g.act(fake_obs(site, band="light", load=400, pv=100)).battery == pytest.approx(0.6)
    assert g.act(fake_obs(site, load=100, pv=400)).battery == pytest.approx(-0.6)


def test_rule_tou_is_cheaper_than_no_battery_on_a_weekday(site):
    s = synthetic_series(site, days=7)
    env = MicrogridEnv(site, s, PerfectForecaster(s))
    base = run_episode(env, NoBattery(), day_start=96).kpis()
    tou = run_episode(env, RuleTOU(site), day_start=96).kpis()
    assert tou["operating_cost"] < base["operating_cost"]
    assert base["battery_cycles"] == 0.0 and base["critical_served_pct"] == 100.0


def test_summarise_covers_every_controller_and_regime(site):
    s = synthetic_series(site, days=7)
    env = MicrogridEnv(site, s, PerfectForecaster(s))
    df = summarise(env, [NoBattery(), GreedySelf(site)], day_starts=[96, 192],
                   regimes=["normal", "blackout"], seeds=[0, 1])
    assert len(df) == 2 * (1 + 2) * 2
    assert {"controller", "regime", "day_start", "seed", "operating_cost", "unserved_kwh"} <= set(df.columns)
```
(normal runs once per day; each disrupted regime once per seed: rows = days × (1 + seeds) × controllers.)

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests_energy/test_baselines.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `control/gridlens_control/base.py`**

```python
"""Every controller (baselines, MPC, PPO, SAC) implements this protocol and passes through the same safety layer."""
from __future__ import annotations

from typing import Protocol

from gridlens_sim.env import Action, Observation


class Controller(Protocol):
    name: str

    def reset(self) -> None: ...

    def act(self, obs: Observation) -> Action: ...
```

- [ ] **Step 4: Write `control/gridlens_control/baselines.py`**

```python
"""Classical baselines (spec §6.4). None of them postpones flexible demand."""
from __future__ import annotations

import numpy as np

from gridlens_sim.env import Action, Observation


class NoBattery:
    """Reference for savings: battery idle (the safety layer may still use it to avoid shedding)."""
    name = "no_battery"

    def reset(self) -> None:
        pass

    def act(self, obs: Observation) -> Action:
        return Action(0.0, 0.0)


class RuleTOU:
    """Baseline 1: charge from the grid in the cheapest (light) band, discharge in the peak band to cover net load.
    Islanded: cover any deficit and absorb any surplus."""
    name = "rule_tou"

    def __init__(self, site):
        self.site = site

    def reset(self) -> None:
        pass

    def act(self, obs: Observation) -> Action:
        b = self.site.battery
        net = obs.load_kw - obs.pv_kw
        if not obs.grid_available:
            return Action(float(np.clip(net / b.power_kw, -1.0, 1.0)), 0.0)
        if obs.band == "light":
            return Action(-1.0 if obs.soc < b.soc_max else 0.0, 0.0)
        if obs.band == "peak":
            return Action(float(np.clip(net / b.power_kw, 0.0, 1.0)), 0.0)
        return Action(0.0, 0.0)


class GreedySelf:
    """Baseline 2: greedy self-consumption. Charge only from PV surplus, discharge to cover any deficit."""
    name = "greedy_self"

    def __init__(self, site):
        self.site = site

    def reset(self) -> None:
        pass

    def act(self, obs: Observation) -> Action:
        net = obs.load_kw - obs.pv_kw
        return Action(float(np.clip(net / self.site.battery.power_kw, -1.0, 1.0)), 0.0)
```

- [ ] **Step 5: Write `control/gridlens_control/runner.py`**

```python
"""Run one controller over one day and summarise it (spec §7 metrics)."""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from gridlens_sim.constants import DT_H
from gridlens_sim.disruptions import NORMAL, Scenario, generate
from gridlens_sim.env import StepRecord


@dataclass(frozen=True)
class EpisodeResult:
    controller: str
    day: str
    scenario: dict
    records: tuple[StepRecord, ...]
    priorities: tuple[str, ...]
    battery_energy_kwh: float
    nominal_hz: float
    decision_ms: tuple[float, ...]

    def kpis(self) -> dict[str, float]:
        r = self.records
        crit = [i for i, p in enumerate(self.priorities) if p == "critical"]
        crit_demand = sum(sum(x.tenant_demand_kw[i] for i in crit) for x in r) * DT_H
        crit_shed = sum(sum(x.shed_by_tenant[i] for i in crit) for x in r) * DT_H
        shed_steps = [x.shed_kw > 1e-6 for x in r]
        events = sum(1 for i, on in enumerate(shed_steps) if on and (i == 0 or not shed_steps[i - 1]))
        nadirs = [x.nadir_hz for x in r if x.nadir_hz is not None]

        def total(field: str) -> float:
            return float(sum(getattr(x, field) for x in r))

        return {
            "operating_cost": total("energy_cost") + total("demand_cost") + total("fuel_cost")
            + total("startup_cost") + total("degradation_cost"),
            "total_cost": total("total_cost"),
            "energy_cost": total("energy_cost"),
            "demand_cost": total("demand_cost"),
            "fuel_cost": total("fuel_cost"),
            "peak_import_kw": float(max(x.grid_import_kw for x in r)),
            "import_kwh": total("grid_import_kw") * DT_H,
            "export_kwh": total("grid_export_kw") * DT_H,
            "curtailed_kwh": total("curtailed_kw") * DT_H,
            "co2_kg": total("co2_kg"),
            "nox_g": total("nox_g"),
            "pm_g": total("pm_g"),
            "diesel_unit_hours": total("diesel_on") * DT_H,
            "unserved_kwh": total("shed_kw") * DT_H,
            "critical_served_pct": 100.0 if crit_demand <= 0 else 100.0 * (1.0 - crit_shed / crit_demand),
            "shed_events": float(events),
            "battery_cycles": sum(abs(x.battery_kw) for x in r) * DT_H / (2.0 * self.battery_energy_kwh),
            "min_nadir_hz": float(min(nadirs)) if nadirs else float(self.nominal_hz),
            "safety_corrections": float(sum(len(x.corrections) for x in r)),
            "decision_ms_mean": float(np.mean(self.decision_ms)),
        }


def run_episode(env, controller, day_start: int, scenario: Scenario = NORMAL, *, commitment=None,
                soc0: float = 0.5) -> EpisodeResult:
    controller.reset()
    options = {"day_start": day_start, "scenario": scenario, "soc": soc0}
    if commitment is not None:
        options["commitment"] = commitment
    _, info = env.reset(options=options)
    obs = info["observation"]
    records, ms = [], []
    while True:
        t0 = time.perf_counter()
        act = controller.act(obs)
        ms.append((time.perf_counter() - t0) * 1000.0)
        _, _, terminated, _, info = env.step_action(act)
        records.append(info["record"])
        obs = info["observation"]
        if terminated:
            break
    return EpisodeResult(controller=controller.name, day=str(env.series.index[day_start].date()),
                         scenario=scenario.to_dict(), records=tuple(records),
                         priorities=tuple(t.priority for t in env.tenants),
                         battery_energy_kwh=env.site.battery.energy_kwh,
                         nominal_hz=env.site.frequency.nominal_hz, decision_ms=tuple(ms))


def summarise(env, controllers, day_starts, regimes, seeds) -> pd.DataFrame:
    """One row per (day, regime, seed, controller). The normal regime runs once per day; each disrupted regime runs
    once per seed with a scenario seeded from the seed and the day, identical for every controller."""
    rows = []
    for ds in day_starts:
        for regime in regimes:
            for seed in ([0] if regime == "normal" else seeds):
                scenario = generate(seed * 100_003 + ds, regime, env.site.p_peak_kw, env.steps)
                for c in controllers:
                    k = run_episode(env, c, ds, scenario).kpis()
                    rows.append({"controller": c.name, "regime": regime, "day_start": ds, "seed": seed, **k})
    return pd.DataFrame(rows)
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests_energy/test_baselines.py -q && uv run ruff check control tests_energy`
Expected: `6 passed`; ruff clean.

- [ ] **Step 7: Commit**

```bash
git add control tests_energy/test_baselines.py
git commit -m "Add controller protocol, rule-based TOU and greedy baselines, episode runner with KPIs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Real data — download script and park factory

**Files:**
- Create: `scripts/fetch_energy_data.py`, `sim/gridlens_sim/factory.py`
- Test: `tests_energy/test_factory.py`
- Modify: `data/README_DATASETS.md` (add the two sources)

**Interfaces:**
- Consumes: `read_steel`, `peak_kw`, `URL` (Task 2); `fetch_hourly`, `interpolate_to`, `ARCHIVE_URL` (Task 3); `ghi_quarter_hour`, `pv_output_kw` (Task 3); `load_site` (Task 1); `build_series`, `DEFAULT_TENANTS` (Task 4).
- Produces: `ParkData(site, series, weather)` where `weather` has columns `ghi, temperature_2m, cloud_cover, wind_speed_10m` on the series index; `load_park(site_id, tenants=DEFAULT_TENANTS, raw_dir=RAW_DIR) -> ParkData`; raw files `data/raw/energy/steel/steel_industry_energy_consumption.zip`, `data/raw/energy/weather/<site_id>_2018.csv`, `data/raw/energy/manifest.json` (all git-ignored by `data/raw/**`).

- [ ] **Step 1: Write the failing test**

`tests_energy/test_factory.py`:
```python
import pandas as pd
import pytest
from steel_fixture import steel_csv

from gridlens_sim.factory import load_park


def test_load_park_from_raw_files(tmp_path):
    (tmp_path / "steel").mkdir()
    stamps = pd.date_range("2018-01-01 00:15", periods=192, freq="15min")
    values = [10 + (i % 96) / 10 for i in range(192)]
    (tmp_path / "steel" / "Steel_industry_data.csv").write_text(
        steel_csv([f"{t:%d/%m/%Y %H:%M}" for t in stamps], values))
    (tmp_path / "weather").mkdir()
    hours = pd.date_range("2017-12-31 00:00", "2018-01-04 00:00", freq="h", tz="Asia/Seoul")
    pd.DataFrame({"shortwave_radiation": 300.0, "temperature_2m": 5.0, "cloud_cover": 20.0,
                  "wind_speed_10m": 3.0}, index=hours).to_csv(tmp_path / "weather" / "kr_gwangyang_2018.csv")

    park = load_park("kr_gwangyang", raw_dir=tmp_path)

    s = park.series
    assert len(s) == 192 and s.index[0] == pd.Timestamp("2018-01-01 00:00", tz="Asia/Seoul")
    assert park.site.p_peak_kw == pytest.approx(19.5 * 4)
    assert s.pv_kw.min() >= 0 and s.pv_kw.max() > 0
    assert set(park.weather.columns) == {"ghi", "temperature_2m", "cloud_cover", "wind_speed_10m"}
    assert park.weather.index.equals(s.index)


def test_missing_raw_data_says_how_to_fetch_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="fetch_energy_data"):
        load_park("kr_gwangyang", raw_dir=tmp_path)
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests_energy/test_factory.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'gridlens_sim.factory'`.

- [ ] **Step 3: Write `sim/gridlens_sim/factory.py`**

```python
"""Build a park from raw files: observed steel load, observed weather, simulated PV (spec §4.1)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from gridlens_ml.pv import ghi_quarter_hour, pv_output_kw
from gridlens_ml.steel import peak_kw, read_steel
from gridlens_ml.weather import interpolate_to

from .config import Site, load_site
from .series import ParkSeries, build_series
from .tenants import DEFAULT_TENANTS

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw" / "energy"
STEEL_FILES = ("steel_industry_energy_consumption.zip", "Steel_industry_data.csv")
MET = ("temperature_2m", "cloud_cover", "wind_speed_10m")


@dataclass(frozen=True)
class ParkData:
    site: Site
    series: ParkSeries
    weather: pd.DataFrame


def _steel_path(raw_dir: Path) -> Path:
    for name in STEEL_FILES:
        p = raw_dir / "steel" / name
        if p.exists():
            return p
    raise FileNotFoundError(f"no steel load file in {raw_dir / 'steel'}; run "
                            "`uv run python scripts/fetch_energy_data.py` first")


def read_weather(path: Path, tz: str) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert(tz)
    return df


def load_park(site_id: str, tenants=DEFAULT_TENANTS, raw_dir: Path = RAW_DIR) -> ParkData:
    raw_dir = Path(raw_dir)
    steel = read_steel(_steel_path(raw_dir))
    site = load_site(site_id, p_peak_kw=peak_kw(steel))
    if site.timezone == str(steel.index.tz):
        index = steel.index
    else:   # what-if: reuse the load profile on the site's local wall clock
        index = pd.DatetimeIndex(steel.index.tz_localize(None)).tz_localize(site.timezone)
    hourly = read_weather(raw_dir / "weather" / f"{site.id}_2018.csv", site.timezone)
    ghi = ghi_quarter_hour(hourly["shortwave_radiation"], site.latitude, site.longitude, site.timezone)
    ghi = ghi.reindex(index).fillna(0.0)
    met = {c: interpolate_to(hourly[c], index) for c in MET}
    pv = pv_output_kw(ghi, met["temperature_2m"], met["wind_speed_10m"], site)
    series = build_series(index, steel["load_kw"].to_numpy(dtype=float), pv.to_numpy(), site, tenants)
    weather = pd.DataFrame({"ghi": ghi.to_numpy(), **{c: v.to_numpy() for c, v in met.items()}}, index=index)
    return ParkData(site=site, series=series, weather=weather)
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests_energy/test_factory.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Write `scripts/fetch_energy_data.py`**

```python
"""Download GridLens raw data into data/raw/energy (git-ignored):
UCI Steel Industry Energy Consumption (CC BY 4.0) and Open-Meteo 2018 hourly weather (CC BY 4.0) for every site in
config/sites. Writes data/raw/energy/manifest.json with SHA-256 hashes.

    uv run python scripts/fetch_energy_data.py [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import httpx
import yaml

from gridlens_ml.steel import URL as STEEL_URL
from gridlens_ml.weather import ARCHIVE_URL, fetch_hourly

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "energy"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="download again even if files exist")
    args = parser.parse_args()
    (RAW / "steel").mkdir(parents=True, exist_ok=True)
    (RAW / "weather").mkdir(parents=True, exist_ok=True)
    manifest = {}
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        z = RAW / "steel" / "steel_industry_energy_consumption.zip"
        if args.force or not z.exists():
            r = client.get(STEEL_URL)
            r.raise_for_status()
            z.write_bytes(r.content)
        manifest["steel"] = {"url": STEEL_URL, "licence": "CC BY 4.0", "doi": "10.24432/C52G8C",
                             "sha256": sha256(z)}
        for cfg in sorted((ROOT / "config" / "sites").glob("*.yaml")):
            site = yaml.safe_load(cfg.read_text())
            out = RAW / "weather" / f"{site['id']}_2018.csv"
            if args.force or not out.exists():
                df = fetch_hourly(site["latitude"], site["longitude"], "2017-12-31", "2019-01-01",
                                  site["timezone"], client=client)
                df.to_csv(out)
            manifest[f"weather:{site['id']}"] = {"url": ARCHIVE_URL, "licence": "CC BY 4.0", "sha256": sha256(out)}
    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Download the real data and check it (needs network and the owner's approval to download)**

Ask the owner before running: it downloads about 2.6 MB from archive.ics.uci.edu and two yearly hourly weather files from archive-api.open-meteo.com.
```bash
uv run python scripts/fetch_energy_data.py
uv run python - <<'PY'
from gridlens_sim.factory import load_park
for sid in ("kr_gwangyang", "ae_industrial"):
    p = load_park(sid)
    s = p.series
    print(sid, len(s), s.index[0], s.index[-1], "P_peak kW", round(p.site.p_peak_kw, 1),
          "load MWh", round(s.load_kw.sum() * 0.25 / 1000, 1), "PV MWh", round(s.pv_kw.sum() * 0.25 / 1000, 1))
PY
```
Expected: both sites print `35040` rows from `2018-01-01 00:00` to `2018-12-31 23:45`, P_peak about 629 kW (largest usage ≈157 kWh per 15 minutes), PV energy larger for the UAE site than for Korea. If `read_steel` raises, print the first and last five `date` values of the CSV, adapt `_parse_times` to the convention found, add a test case for it in `tests_energy/test_steel.py`, and note the finding in `data/README_DATASETS.md`.

- [ ] **Step 7: Document the sources**

Append to `data/README_DATASETS.md`:
```markdown
## GridLens energy data (fetched by `scripts/fetch_energy_data.py`, stored in `data/raw/energy/`, git-ignored)

| Dataset | Use | Licence | Label |
|---|---|---|---|
| UCI Steel Industry Energy Consumption (id 851, doi:10.24432/C52G8C) — 15-minute kWh, DAEWOO Steel, Gwangyang, 2018 | park load | CC BY 4.0 | Observed |
| Open-Meteo historical archive, hourly shortwave radiation, temperature, cloud cover, wind, 2018, per site | weather; PV via pvlib | CC BY 4.0 | Observed (PV output simulated) |

The UAE what-if reuses the Korean load profile on its local wall clock; this is stated wherever its results appear.
```

- [ ] **Step 8: Run checks and commit**

```bash
uv run pytest tests_energy -q && uv run ruff check .
git add sim/gridlens_sim/factory.py scripts/fetch_energy_data.py tests_energy/test_factory.py data/README_DATASETS.md
git commit -m "Add raw energy data download and park factory (UCI steel load, Open-Meteo weather, pvlib PV)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: LightGBM quantile forecaster and study GF1

**Files:**
- Create: `ml/gridlens_ml/energy_forecast.py`, `evaluations/gf1_forecast_study.py`
- Test: `tests_energy/test_energy_forecast.py`
- Modify: `evaluations/study_registry.json`, `scripts/course_metrics.py`

**Interfaces:**
- Consumes: `ParkData` (Task 11), `SeasonalNaiveForecaster` (Task 8), `gridlens_ml.metrics.mae, wape, pinball, coverage` (existing).
- Produces: `features(y, index, exog, t, horizons=HORIZONS) -> ndarray`, `train_quantile_models(y, index, exog, issues, *, seed=0, rounds=300) -> dict[float, LGBMRegressor]`, `predict_quantiles(models, y, index, exog, t) -> ndarray (H, 5)`, `LGBMForecaster(load_models, pv_models, load, pv, index, load_exog, pv_exog, daylight=None)` implementing `forecast(t) -> (2, H, 5)`; constants `H, DAY, WEEK, HORIZONS, QUANTILES` (same values as `gridlens_sim.constants`; `gridlens_ml` does not import `gridlens_sim`).

- [ ] **Step 1: Write the failing tests**

`tests_energy/test_energy_forecast.py`:
```python
import numpy as np
import pandas as pd

from gridlens_ml.energy_forecast import H, WEEK, LGBMForecaster, features, predict_quantiles, train_quantile_models
from gridlens_sim.testing import synthetic_series


def test_features_use_only_the_past():
    rng = np.random.default_rng(0)
    y = rng.random(2000)
    idx = pd.date_range("2018-01-01", periods=2000, freq="15min", tz="Asia/Seoul")
    exog = rng.random((2000, 2))
    t = 1000
    a = features(y, idx, exog, t)
    y2 = y.copy()
    y2[t + 1:] = -1.0
    np.testing.assert_array_equal(a, features(y2, idx, exog, t))
    assert a.shape == (H, 9 + 2)


def test_models_give_ordered_nonnegative_quantiles(site):
    s = synthetic_series(site, days=14)
    issues = list(range(WEEK, len(s) - H - 1, 16))
    lm = train_quantile_models(s.load_kw, s.index, None, issues, rounds=20)
    pm = train_quantile_models(s.pv_kw, s.index, None, issues, rounds=20)
    t = len(s) - H - 2
    out = predict_quantiles(lm, s.load_kw, s.index, None, t)
    assert out.shape == (H, 5) and np.all(np.diff(out, axis=1) >= 0) and out.min() >= 0
    f = LGBMForecaster(lm, pm, s.load_kw, s.pv_kw, s.index, None, None, daylight=s.pv_kw > 0)
    fc = f.forecast(t)
    assert fc.shape == (2, H, 5)
    night = ~(s.pv_kw[t + 1:t + H + 1] > 0)
    assert np.all(fc[1][night] == 0)
    assert f.forecast(t) is fc        # cached
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests_energy/test_energy_forecast.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `ml/gridlens_ml/energy_forecast.py`**

```python
"""Direct multi-horizon quantile forecasts of 15-minute park load and PV with LightGBM (study GF1, spec §4.3).

One model per quantile and target; the horizon is a feature. Features at issue time t use the target only up to t
(last value, last-hour mean, same quarter-hour one day and one week before the target time), plus the target time's
calendar and exogenous weather. Observed weather stands in for a weather forecast: an optimistic assumption stated
in every result.
"""
from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd

QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)
H = 96
DAY = 96
WEEK = 7 * DAY
HORIZONS = np.arange(1, H + 1)


def features(y: np.ndarray, index: pd.DatetimeIndex, exog: np.ndarray | None, t: int,
             horizons: np.ndarray = HORIZONS) -> np.ndarray:
    tgt = t + horizons
    tgt_c = np.minimum(tgt, len(index) - 1)
    ts = index[tgt_c]
    n = len(horizons)
    cols = [horizons.astype(float), np.full(n, y[t]), np.full(n, float(np.mean(y[max(0, t - 3):t + 1]))),
            y[np.clip(tgt - DAY, 0, t)], y[np.clip(tgt - WEEK, 0, t)],
            np.asarray(ts.hour + ts.minute / 60, dtype=float), np.asarray(ts.dayofweek, dtype=float),
            np.asarray(ts.dayofweek >= 5, dtype=float), np.asarray(ts.month, dtype=float)]
    if exog is not None:
        cols += [exog[tgt_c, j] for j in range(exog.shape[1])]
    return np.column_stack(cols).astype(float)


def train_quantile_models(y: np.ndarray, index: pd.DatetimeIndex, exog: np.ndarray | None, issues, *,
                          seed: int = 0, rounds: int = 300) -> dict[float, lgb.LGBMRegressor]:
    x = np.vstack([features(y, index, exog, t) for t in issues])
    target = np.concatenate([y[t + HORIZONS] for t in issues])
    models = {}
    for q in QUANTILES:
        m = lgb.LGBMRegressor(objective="quantile", alpha=q, n_estimators=rounds, learning_rate=0.05,
                              num_leaves=63, min_child_samples=50, subsample=0.8, subsample_freq=1,
                              colsample_bytree=0.9, random_state=seed, verbose=-1)
        models[q] = m.fit(x, target)
    return models


def predict_quantiles(models, y: np.ndarray, index: pd.DatetimeIndex, exog: np.ndarray | None,
                      t: int) -> np.ndarray:
    x = features(y, index, exog, t)
    out = np.column_stack([models[q].predict(x) for q in QUANTILES])
    return np.clip(np.sort(out, axis=1), 0.0, None)


class LGBMForecaster:
    """Implements the simulator's Forecaster protocol: forecast(t) -> (2, H, 5) for [load, pv]."""

    def __init__(self, load_models, pv_models, load, pv, index, load_exog=None, pv_exog=None, daylight=None):
        self.load_models, self.pv_models = load_models, pv_models
        self.load, self.pv, self.index = np.asarray(load), np.asarray(pv), index
        self.load_exog, self.pv_exog = load_exog, pv_exog
        self.daylight = None if daylight is None else np.asarray(daylight, dtype=bool)
        self._cache: dict[int, np.ndarray] = {}

    def forecast(self, t: int) -> np.ndarray:
        if t in self._cache:
            return self._cache[t]
        out = np.empty((2, H, len(QUANTILES)))
        out[0] = predict_quantiles(self.load_models, self.load, self.index, self.load_exog, t)
        out[1] = predict_quantiles(self.pv_models, self.pv, self.index, self.pv_exog, t)
        if self.daylight is not None:
            out[1][~self.daylight[np.minimum(t + HORIZONS, len(self.daylight) - 1)]] = 0.0
        self._cache[t] = out
        return out
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests_energy/test_energy_forecast.py -q && uv run ruff check ml tests_energy`
Expected: `2 passed`; ruff clean.

- [ ] **Step 5: Write `evaluations/gf1_forecast_study.py`**

```python
"""GF1: 15-minute multi-horizon quantile forecasts of park load and PV (spec §4.3).

Train 2018-01-08..09-30 (issues every 2 h), validation October and test 2018-11-01..12-30 (issues every hour).
Seasonal naive vs LightGBM quantile; MAE, WAPE, mean pinball loss and 80 % interval coverage by horizon band.
Load is observed (UCI steel); PV is simulated from observed weather; observed weather stands in for forecasts.

    uv run python evaluations/gf1_forecast_study.py [--site kr_gwangyang] [--rounds 300]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from gridlens_ml.energy_forecast import H, HORIZONS, QUANTILES, WEEK, LGBMForecaster, train_quantile_models
from gridlens_ml.metrics import coverage, mae, pinball, wape
from gridlens_sim.factory import load_park
from gridlens_sim.forecast import SeasonalNaiveForecaster

ROOT = Path(__file__).resolve().parents[1]
BANDS = {"1h": (1, 4), "6h": (5, 24), "24h": (25, 96)}


def positions(series, start: str, end: str, every: int) -> list[int]:
    a = series.day_starts(start, start)[0]
    b = series.day_starts(end, end)[0] + 95
    return [t for t in range(max(a, WEEK), b + 1, every) if t + H < len(series)]


def evaluate(forecaster, series, issues) -> dict:
    out = {}
    for j, (name, y) in enumerate((("load", series.load_kw), ("pv", series.pv_kw))):
        pred = np.stack([forecaster.forecast(t)[j] for t in issues])          # (n, H, 5)
        truth = np.stack([y[t + HORIZONS] for t in issues])                 # (n, H)
        out[name] = {}
        for band, (lo, hi) in BANDS.items():
            p, yy = pred[:, lo - 1:hi], truth[:, lo - 1:hi].ravel()
            out[name][band] = {
                "mae": mae(yy, p[..., 2].ravel()),
                "wape": wape(yy, p[..., 2].ravel()),
                "pinball": float(np.mean([pinball(yy, p[..., i].ravel(), q) for i, q in enumerate(QUANTILES)])),
                "coverage80": coverage(yy, p[..., 0].ravel(), p[..., 4].ravel()),
            }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", default="kr_gwangyang")
    ap.add_argument("--rounds", type=int, default=300)
    args = ap.parse_args()
    park = load_park(args.site)
    s, w = park.series, park.weather
    load_exog = w[["temperature_2m"]].to_numpy()
    pv_exog = w[["ghi", "temperature_2m", "cloud_cover"]].to_numpy()
    train = positions(s, "2018-01-08", "2018-09-30", 8)
    val = positions(s, "2018-10-01", "2018-10-31", 4)
    test = positions(s, "2018-11-01", "2018-12-30", 4)
    lgbm = LGBMForecaster(train_quantile_models(s.load_kw, s.index, load_exog, train, rounds=args.rounds),
                          train_quantile_models(s.pv_kw, s.index, pv_exog, train, rounds=args.rounds),
                          s.load_kw, s.pv_kw, s.index, load_exog, pv_exog, daylight=w["ghi"].to_numpy() > 0)
    naive = SeasonalNaiveForecaster(s)
    results = {split: {"seasonal_naive": evaluate(naive, s, iss), "lightgbm": evaluate(lgbm, s, iss)}
               for split, iss in (("validation", val), ("test", test))}
    run = f"GF1-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    out = ROOT / "artifacts" / "experiments" / run
    out.mkdir(parents=True)
    metrics = {"study": "GF1", "site": args.site, "results": results,
               "train": {"issues": len(train)}, "validation": {"issues": len(val)}, "test": {"issues": len(test)},
               "data": {"load": "observed (UCI steel 851)", "pv": "simulated by pvlib from observed weather",
                        "weather_as_forecast": "observed weather stands in for forecasts (optimistic)"}}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    (out / "config.json").write_text(json.dumps({"rounds": args.rounds, "quantiles": QUANTILES,
                                                 "bands": BANDS, "seed": 0}, indent=2) + "\n")
    print(run)
    for target in ("load", "pv"):
        for model in ("seasonal_naive", "lightgbm"):
            row = results["test"][model][target]
            print(f"{target:5s} {model:15s} " + "  ".join(
                f"{b}: MAE {row[b]['mae']:.1f} cov80 {row[b]['coverage80']:.2f}" for b in BANDS))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the study on real data**

Run: `uv run python evaluations/gf1_forecast_study.py`
Expected: prints `GF1-<timestamp>` and a table; `artifacts/experiments/GF1-<timestamp>/metrics.json` exists. Read the table before writing anything about it.

- [ ] **Step 7: Register the study**

Add an entry to `evaluations/study_registry.json` → `experiments`, keyed by the printed run ID, with the same shape as the `FA1-…` entry: `"status": "current"`, a `"headline"` written from `metrics.json` (test split, LightGBM vs seasonal naive MAE at the 1 h and 24 h bands for load and PV, and 80 % coverage), and `"notes"` stating that load is observed, PV simulated and weather used as a perfect forecast. In `scripts/course_metrics.py` add `"GF1": "historical backtest (UCI steel load; PV simulated from Open-Meteo weather; weather as perfect forecast)"` to `DATA_KIND`, and add GF1 rows to each other per-study table by copying the shape of the `FA1` rows (size field `("test issue times", "test.issues")`). Then:
```bash
uv run python scripts/course_metrics.py && uv run python scripts/course_metrics.py --check && echo fresh
```
Expected: `fresh`.

- [ ] **Step 8: Run checks and commit**

```bash
uv run pytest tests_energy -q && uv run ruff check .
git add ml/gridlens_ml/energy_forecast.py evaluations/gf1_forecast_study.py tests_energy/test_energy_forecast.py \
  evaluations/study_registry.json scripts/course_metrics.py docs/course/metrics.md docs/course/metrics.json \
  artifacts/experiments/GF1-*/metrics.json artifacts/experiments/GF1-*/config.json
git commit -m "Add LightGBM quantile load/PV forecaster and study GF1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Baseline comparison on real data

**Files:**
- Create: `scripts/run_baselines.py`
- Modify: `PROJECT_STATUS.md` (Plan 2 row)

**Interfaces:**
- Consumes: `load_park` (Task 11), `SeasonalNaiveForecaster` (Task 8), `MicrogridEnv` (Task 9), baselines and `summarise` (Task 10).

- [ ] **Step 1: Write `scripts/run_baselines.py`**

```python
"""Quick comparison of the classical baselines on real data (not the formal benchmark MB1, which is Plan 5).

    uv run python scripts/run_baselines.py [--site kr_gwangyang] [--seeds 2] [--days 61]
"""
from __future__ import annotations

import argparse

from gridlens_control.baselines import GreedySelf, NoBattery, RuleTOU
from gridlens_control.runner import summarise
from gridlens_sim.env import MicrogridEnv
from gridlens_sim.factory import load_park
from gridlens_sim.forecast import SeasonalNaiveForecaster

COLUMNS = ["operating_cost", "peak_import_kw", "co2_kg", "unserved_kwh", "critical_served_pct",
           "min_nadir_hz", "diesel_unit_hours", "battery_cycles"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", default="kr_gwangyang")
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--days", type=int, default=61)
    args = ap.parse_args()
    park = load_park(args.site)
    s = park.series
    env = MicrogridEnv(park.site, s, SeasonalNaiveForecaster(s))
    days = s.day_starts("2018-11-01", "2018-12-31")[: args.days]
    df = summarise(env, [NoBattery(), RuleTOU(park.site), GreedySelf(park.site)], days,
                   ["normal", "blackout", "cloud_drop", "machine_start", "combined"], list(range(args.seeds)))
    print(f"{park.site.name}: {len(days)} days, currency {park.site.currency}; simulated (assumed assets)")
    print(df.groupby(["regime", "controller"])[COLUMNS].mean().round(2).to_string())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-run on a few days, then the full test period**

```bash
uv run python scripts/run_baselines.py --days 3 --seeds 1
uv run python scripts/run_baselines.py
```
Expected: a table with 5 regimes × 3 controllers. Check that it makes physical sense before moving on: `no_battery` has `battery_cycles` near 0 in the normal regime; `rule_tou` has lower `operating_cost` than `no_battery` in the normal regime; blackout regimes show `min_nadir_hz` below nominal and `diesel_unit_hours` > 0. If one of these fails, use superpowers:systematic-debugging before changing code.

- [ ] **Step 3: Update `PROJECT_STATUS.md` and commit**

Change the Plan 2 row's state to `done` with the date, and add one line under the table: "Energy core: data adapters, MicrogridEnv, baselines and GF1 (see `evaluations/study_registry.json`)."
```bash
uv run pytest tests_energy -q && uv run ruff check .
git add scripts/run_baselines.py PROJECT_STATUS.md
git commit -m "Add baseline comparison script on real data; mark Plan 2 done

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Done when

- `uv run pytest tests_energy -q` passes with no database and no network.
- `uv run ruff check .` is clean.
- `scripts/run_baselines.py` runs on the real Korea data and the UAE what-if.
- GF1 is registered with a headline written from its `metrics.json`.
