"""Lead-time-demand model: closed forms, limits, dependence estimation, calibration on simulated demand, and wiring."""
import math
from datetime import date, timedelta

import numpy as np
import pytest

from supplylens_opt.demand_sim import WEEKDAY, marginal_quantiles, simulate
from supplylens_opt.leadtime_demand import (
    DEFAULT_RHO,
    MAX_LAG,
    MIN_OBS_FOR_ACF,
    ar1_acf,
    daily_moments,
    estimate_dependence,
    gamma_quantile,
    pooled_dependence,
    window_demand,
    window_variance,
)
from supplylens_opt.replenishment import Position, assess


def flat_path(n=28, q10=2.0, q50=5.0, q90=9.0, start=date(2011, 12, 9)):
    return [{"day": start + timedelta(days=i), "q10": q10, "q50": q50, "q90": q90} for i in range(n)]


# --- exact pieces -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("p", [0.1, 0.5, 0.9, 0.99])
def test_gamma_quantile_matches_exponential_closed_form(p):
    assert gamma_quantile(3.0, 9.0, p) == pytest.approx(-3.0 * math.log(1 - p), rel=1e-6)   # shape 1, scale 3


@pytest.mark.parametrize("mean,var,p", [(2.0, 2.0, 0.9), (150.0, 400.0, 0.95), (0.7, 3.0, 0.9), (40.0, 40.0, 0.5)])
def test_gamma_quantile_matches_scipy(mean, var, p):
    stats = pytest.importorskip("scipy.stats")
    assert gamma_quantile(mean, var, p) == pytest.approx(stats.gamma.ppf(p, mean * mean / var, scale=var / mean), rel=1e-6)


def test_gamma_quantile_edges():
    assert gamma_quantile(0.0, 1.0, 0.9) == 0.0
    assert gamma_quantile(10.0, 0.0, 0.9) == 10.0
    with pytest.raises(ValueError):
        gamma_quantile(1.0, 1.0, 1.0)


def test_daily_moments_recover_a_normal():
    mu, sd = 20.0, 4.0
    m, s = daily_moments(mu - 1.2816 * sd, mu, mu + 1.2816 * sd)
    assert m == pytest.approx(mu, rel=1e-3) and s == pytest.approx(sd, rel=1e-3)


def test_daily_moments_never_negative_and_order_insensitive():
    assert daily_moments(0, 0, 0) == (0.0, 0.0)
    assert daily_moments(9, 2, 5) == daily_moments(2, 5, 9)


def test_window_variance_limits_and_brute_force_agreement():
    sds = [1.0, 2.0, 3.0, 4.0]
    assert window_variance(sds, [0.0] * MAX_LAG) == pytest.approx(sum(s * s for s in sds))     # independent days
    acf = [0.5, 0.3, 0.1]
    brute = sum(s * s for s in sds) + 2 * sum(sds[i] * sds[j] * acf[j - i - 1] for i in range(4) for j in range(i + 1, 4) if j - i <= 3)
    assert window_variance(sds, acf) == pytest.approx(brute)
    assert window_variance(sds, [-0.9] * 5) == pytest.approx(sum(s * s for s in sds))          # negative lags never lower it
    assert window_variance(sds, ar1_acf(0.9)) > window_variance(sds, ar1_acf(0.3)) > window_variance(sds, ar1_acf(0.0))


# --- the window distribution ------------------------------------------------------------------------------------

def test_quantile_sits_between_the_two_old_heuristics_for_ordinary_dependence():
    w = window_demand(flat_path(), 28, 0.9, acf=ar1_acf(0.3), dependence_basis="history")
    q50_sum, q90_sum = 5.0 * 28, 9.0 * 28
    assert q50_sum < w.quantile < q90_sum
    assert w.dependence_basis == "history" and w.extrapolated_days == 0 and w.variance_inflation > 1.0


def test_quantile_rises_with_service_level_and_with_dependence():
    qs = [window_demand(flat_path(), 21, sl, ar1_acf(0.3)).quantile for sl in (0.5, 0.8, 0.9, 0.99)]
    assert qs == sorted(qs) and len(set(qs)) == 4
    by_rho = [window_demand(flat_path(), 21, 0.9, ar1_acf(r)).quantile for r in (0.0, 0.3, 0.6, 0.9)]
    assert by_rho == sorted(by_rho) and len(set(by_rho)) == 4


def test_quantile_grows_with_the_protection_interval_and_with_lead_time_variability():
    assert window_demand(flat_path(), 14).quantile < window_demand(flat_path(), 28).quantile
    assert window_demand(flat_path(), 21, lead_time_sd_days=0.0).quantile < window_demand(flat_path(), 21, lead_time_sd_days=4.0).quantile


def test_horizon_shorter_than_protection_is_extended_and_flagged():
    w = window_demand(flat_path(28), 40, 0.9, ar1_acf(0.3))
    assert w.extrapolated_days == 12 and w.protection_days == 40
    assert w.mean == pytest.approx(40 * daily_moments(2.0, 5.0, 9.0)[0])


def test_zero_demand_gives_zero_and_bad_inputs_are_rejected():
    z = window_demand(flat_path(q10=0, q50=0, q90=0), 21)
    assert z.quantile == 0.0 and z.mean == 0.0
    for bad in (dict(protection_days=0), dict(protection_days=7, service_level=0.2), dict(protection_days=7, service_level=1.0)):
        with pytest.raises(ValueError):
            window_demand(flat_path(), **bad)
    with pytest.raises(ValueError):
        window_demand([], 7)


def test_missing_dependence_uses_the_declared_default_and_says_so():
    w = window_demand(flat_path(), 21)
    assert w.dependence_basis == "assumed default" and w.lag1 == pytest.approx(DEFAULT_RHO)
    assert w.quantile == window_demand(flat_path(), 21, 0.9, ar1_acf(DEFAULT_RHO)).quantile


# --- dependence estimation --------------------------------------------------------------------------------------

def _ar1_series(rho, n, seed):
    rng = np.random.default_rng(seed)
    e = rng.normal(0, 1, n)
    x = np.empty(n)
    x[0] = e[0]
    for t in range(1, n):
        x[t] = rho * x[t - 1] + np.sqrt(1 - rho ** 2) * e[t]
    return x


def test_estimate_dependence_recovers_persistence_and_returns_a_whole_curve():
    n = 600
    dow = [(i % 7) for i in range(n)]
    weekly = np.array([WEEKDAY[d] for d in dow])
    est = {}
    for rho in (0.0, 0.6):
        vals = (50 + 5 * _ar1_series(rho, n, seed=3 + int(rho * 10))) * weekly
        acf, used = estimate_dependence(list(vals), dow)
        assert len(acf) == MAX_LAG and used > 400
        est[rho] = acf
    # Residuals are measured around a trailing 56-day level, which biases autocorrelation downward a little.
    assert est[0.0][0] < 0.15
    assert 0.3 < est[0.6][0] < 0.75
    assert est[0.6][0] > est[0.0][0] + 0.3
    assert est[0.6][3] > est[0.0][3] + 0.1                   # the curve, not just lag 1, carries the persistence


def test_estimate_dependence_drops_the_noisy_tail_of_an_independent_series():
    """Initial positive sequence: once a pair of lags sums to <= 0 everything after it is zero, so white noise does not
    pile positive sampling noise from 14 lags onto the variance."""
    n = 400
    dow = [(i % 7) for i in range(n)]
    rng = np.random.default_rng(5)
    noisy = []
    for _ in range(20):
        vals = 50 + 5 * rng.standard_normal(n)
        acf, _ = estimate_dependence(list(vals), dow)
        noisy.append(sum(a for a in acf if a > 0))
    persistent = estimate_dependence(list(50 + 5 * _ar1_series(0.9, n, seed=2)), dow)[0]
    assert float(np.mean(noisy)) < 0.35                       # white noise adds little
    assert sum(persistent) > 1.0                              # persistence survives the truncation
    acf0 = estimate_dependence(list(50 + 5 * rng.standard_normal(n)), dow)[0]
    first_zero_pair = next((i for i in range(0, MAX_LAG - 1, 2) if acf0[i] == 0.0 and acf0[i + 1] == 0.0), MAX_LAG)
    assert all(a == 0.0 for a in acf0[first_zero_pair:])      # nothing non-zero after the cut


def test_estimate_dependence_refuses_thin_or_flat_history():
    thin = MIN_OBS_FOR_ACF - 1
    assert estimate_dependence([5.0] * thin, [0] * thin) is None
    assert estimate_dependence([0.0] * 100, [i % 7 for i in range(100)]) is None
    assert estimate_dependence([4.0] * 100, [i % 7 for i in range(100)]) is None         # no variation
    assert pooled_dependence([]) is None
    assert pooled_dependence([(0.1, 0.0), (0.5, 0.4), (0.2, 0.1)]) == (0.2, 0.1)        # lag-wise median


# --- calibration on simulated demand with known dependence -------------------------------------------------------

def _coverage(phi, tau=0.9, L=21, n_series=60, seed=11):
    """Share of held-out L-day windows whose actual total is at or below each method's prediction."""
    rng = np.random.default_rng(seed)
    hits = {"ltd": 0, "q90_sum": 0, "q50_sum": 0}
    total = 0
    for _ in range(n_series):
        base, s, r = float(rng.uniform(5, 30)), 0.35, 4.0
        q = marginal_quantiles(base, s, r, rng, n=8000)
        x = simulate(420, base, phi, s, r, rng)
        hist, test = x[:180], x[180:]
        dow = [i % 7 for i in range(len(hist))]
        est = estimate_dependence(list(hist), dow)
        acf, basis = (est[0], "history") if est else (None, "assumed default")
        for origin in range(0, len(test) - L, 7):
            path = [{"q10": q[(180 + origin + i) % 7][0], "q50": q[(180 + origin + i) % 7][1], "q90": q[(180 + origin + i) % 7][2]}
                    for i in range(L)]
            actual = test[origin:origin + L].sum()
            hits["ltd"] += actual <= window_demand(path, L, tau, acf, basis).quantile
            hits["q90_sum"] += actual <= sum(p["q90"] for p in path)
            hits["q50_sum"] += actual <= sum(p["q50"] for p in path)
            total += 1
    return {k: v / total for k, v in hits.items()}


@pytest.mark.parametrize("phi", [0.0, 0.5, 0.9])
def test_calibration_on_simulated_demand(phi):
    c = _coverage(phi)
    assert abs(c["ltd"] - 0.9) < 0.06, c                 # near the requested service level (see the study for the residual shortfall)
    assert c["q90_sum"] > 0.95, c                        # the old heuristic over-covers (over-stocks)
    assert c["q50_sum"] < 0.62, c                        # and summed medians under-cover


# --- wiring into the replenishment need -------------------------------------------------------------------------

def _pos(on_hand=40):
    return Position(sku_id="S1", on_hand=on_hand, allocated=0, on_order=0, capacity=None)


def test_assess_uses_lead_time_demand_by_default_and_reports_its_inputs():
    a = assess(_pos(), flat_path(), date(2011, 12, 8), 21, 5, lead_time_days=7, service_level=0.9, acf=ar1_acf(0.3), dependence_basis="history")
    assert a.basis == "leadtime_demand" and a.protection_days == 28 and a.lead_time_days == 7
    assert a.dependence_basis == "history" and a.dependence_lag1 == 0.3 and a.variance_inflation > 1.0 and a.service_level == 0.9
    assert a.calibration == "simulation-checked, not validated on real data"
    assert a.required_units == max(0, math.ceil(a.demand_quantile - 40))
    assert "lead-time variability not modelled" in a.method


def test_assess_orders_less_than_the_summed_q90_heuristic_and_more_than_summed_q50():
    kw = dict(decision_date=date(2011, 12, 8), coverage_days=21, safety_days=5)
    ltd = assess(_pos(), flat_path(), acf=ar1_acf(0.3), **kw)
    old = assess(_pos(), flat_path(), basis="q90_sum", **kw)
    med = assess(_pos(), flat_path(), basis="q50_plus_safety", **kw)
    assert ltd.basis == "leadtime_demand" and old.basis == "q90_sum"
    assert med.required_units < ltd.required_units < old.required_units


def test_assess_longer_lead_time_orders_more_and_service_level_orders_more():
    base = assess(_pos(), flat_path(), date(2011, 12, 8), 21, 5, lead_time_days=0, acf=ar1_acf(0.3))
    longer = assess(_pos(), flat_path(), date(2011, 12, 8), 21, 5, lead_time_days=7, acf=ar1_acf(0.3))
    higher = assess(_pos(), flat_path(), date(2011, 12, 8), 21, 5, lead_time_days=0, service_level=0.97, acf=ar1_acf(0.3))
    assert longer.required_units > base.required_units and higher.required_units > base.required_units


def test_assess_needs_q10_for_the_new_basis_and_older_bases_do_not():
    no_q10 = [{k: v for k, v in r.items() if k != "q10"} for r in flat_path()]
    with pytest.raises(ValueError):
        assess(_pos(), no_q10, date(2011, 12, 8), 21, 5)
    assert assess(_pos(), no_q10, date(2011, 12, 8), 21, 5, basis="q90_sum").basis == "q90_sum"


def test_assess_respects_capacity_and_position():
    capped = Position(sku_id="S1", on_hand=40, allocated=0, on_order=0, capacity=60)
    assert assess(capped, flat_path(), date(2011, 12, 8), 21, 5, acf=ar1_acf(0.3)).required_units <= 20
    rich = Position(sku_id="S1", on_hand=5000, allocated=0, on_order=0, capacity=None)
    a = assess(rich, flat_path(), date(2011, 12, 8), 21, 5, acf=ar1_acf(0.3))
    assert a.required_units == 0 and a.status in ("excess", "healthy")
