"""Lead-time-demand model: the distribution of demand over the protection interval, from daily forecast quantiles.

Why this exists. Replenishment needs a quantile of TOTAL demand over the days a purchase must cover (supplier lead
time plus the review/coverage period), not a quantile of one day. The earlier heuristic summed the daily q90 values.
That is the q90 of the window only if every day is at its own 90th percentile at once, i.e. if daily demand is perfectly
dependent. With any real day-to-day independence the sum is far above the true window q90 (over-stocking); and summing
daily q50 values, the alternative, sits below it (under-stocking). Neither is calibrated.

The model, step by step (all closed form, no fitted weights):
  1. Daily moments from the forecast's q10/q50/q90 with Swanson's rule:  mean = 0.3 q10 + 0.4 q50 + 0.3 q90,
     sd = (q90 - q10) / 2.563  (the Pearson-Tukey 10/90 approximation; exact for a normal, a fair approximation for
     moderately skewed daily demand).
  2. Window mean is the sum of daily means. Window variance adds the daily variances AND the covariances between days,
     corr(day i, day i+k) = r_k for k = 1..14 (negative lags ignored), computed in O(n * 14).
  3. The autocorrelations r_k are measured, not guessed, when history exists: `estimate_dependence` takes them from the
     SKU's own recent sales (day-of-week-adjusted residuals around a trailing 56-day level) and keeps only the leading run
     of lag pairs whose sum is positive (Geyer's initial positive sequence), so sampling noise at long lags is not added
     to the variance. Measuring the whole curve matters:
     a latent demand level that persists for weeks gives small lag-1 correlation but a long tail, and a one-parameter
     AR(1) fitted to lag 1 alone under-covers it (85 % against a 90 % target at moderate persistence, in simulation).
     With no usable history the portfolio's median curve is used and labelled; with none at all a declared AR(1)
     default (rho = 0.3) is used and labelled.
  4. Lead-time uncertainty (optional): if the supplier lead time has a standard deviation, add mean_daily**2 * var(L).
     Terms carry point lead times, so this is zero unless a caller supplies it; the output says so.
  5. The window total is fitted with a gamma distribution (non-negative, right-skewed) matching mean and variance, and the
     requested service-level quantile is read off exactly (regularised incomplete gamma, bisection).

What it does NOT claim. The gamma family, the single dependence curve shared by all days of a window and the 14-day
cut-off are modelling choices. Calibration has been checked on
simulated demand with known dependence (tests/test_leadtime_demand.py, evaluations/leadtime_demand_study.py); it has NOT
been validated on a real retail history, which needs the licensed dataset. Until then the output carries
`calibration: "simulation-checked, not validated on real data"`.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

SWANSON_Z = 2.563               # (P90 - P10) / (2 * 1.2816)
DEFAULT_RHO = 0.3               # declared fallback when no history is available (assumed, labelled)
MAX_LAG = 14                    # autocorrelations used (two weeks); longer-range dependence is not modelled
MIN_OBS_FOR_ACF = 84            # twelve weeks of recorded days (56 are consumed by the trailing level)


@dataclass(frozen=True)
class WindowDemand:
    mean: float
    sd: float
    quantile: float             # demand not exceeded with probability `service_level`
    service_level: float
    protection_days: int
    variance_inflation: float   # window variance / sum of daily variances (1.0 = independent days)
    lag1: float                 # first autocorrelation used, for display
    dependence_basis: str       # "history" | "pooled" | "assumed default" | "given"
    extrapolated_days: int      # days beyond the forecast horizon filled with the last week's mean/sd
    lead_time_sd_days: float


def daily_moments(q10: float, q50: float, q90: float) -> tuple[float, float]:
    lo, mid, hi = sorted((q10, q50, q90))
    return max(0.3 * lo + 0.4 * mid + 0.3 * hi, 0.0), max((hi - lo) / SWANSON_Z, 0.0)


def ar1_acf(rho: float, max_lag: int = MAX_LAG) -> tuple[float, ...]:
    rho = max(0.0, min(0.95, rho))
    return tuple(rho ** k for k in range(1, max_lag + 1))


def window_variance(sds: Sequence[float], acf: Sequence[float]) -> float:
    """Var(sum of days) given corr(day i, day i+k) = acf[k-1]. Negative autocorrelations are ignored: sampling noise must
    never lower a variance (every added term is non-negative, so the result is at least the independent-days variance)."""
    n = len(sds)
    total = sum(s * s for s in sds)
    for k in range(1, min(len(acf), n - 1) + 1):
        r = acf[k - 1]
        if r > 0.0:
            total += 2.0 * r * sum(sds[i] * sds[i + k] for i in range(n - k))
    return total


# --- exact gamma quantile (no scipy dependency) -----------------------------------------------------------------

def _gammainc_lower(a: float, x: float) -> float:
    """Regularised lower incomplete gamma P(a, x): series for x < a + 1, continued fraction otherwise."""
    if x <= 0.0:
        return 0.0
    gln = math.lgamma(a)
    if x < a + 1.0:
        term = total = 1.0 / a
        ap = a
        for _ in range(500):
            ap += 1.0
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-15:
                break
        return total * math.exp(-x + a * math.log(x) - gln)
    b = x + 1.0 - a
    c, d = 1e300, 1.0 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return 1.0 - math.exp(-x + a * math.log(x) - gln) * h


def gamma_quantile(mean: float, var: float, p: float) -> float:
    """p-quantile of a gamma distribution with the given mean and variance."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    if mean <= 0.0:
        return 0.0
    if var <= mean * 1e-9:      # (almost) deterministic
        return mean
    shape, scale = mean * mean / var, var / mean
    lo, hi = 0.0, mean + 12.0 * math.sqrt(var)
    while _gammainc_lower(shape, hi / scale) < p:
        hi *= 2.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if _gammainc_lower(shape, mid / scale) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-9 * max(hi, 1.0):
            break
    return 0.5 * (lo + hi)


# --- dependence from history -------------------------------------------------------------------------------------

def estimate_dependence(values: Sequence[float], weekdays: Sequence[int], level_days: int = 56,
                        max_lag: int = MAX_LAG) -> tuple[tuple[float, ...], int] | None:
    """Autocorrelations r_1..r_max_lag of day-of-week-adjusted residuals around a trailing level.

    `values` are recorded daily unit sales in date order and `weekdays` the matching 0-6 weekday numbers. Returns
    (acf, observations used) or None when there is too little history. `acf` is zero from the first lag pair whose sum is
    not positive onward. Days with no record are not zeros (absence is not demand), so callers pass only recorded days."""
    n = len(values)
    if n < MIN_OBS_FOR_ACF or n != len(weekdays):
        return None
    mean_all = sum(values) / n
    if mean_all <= 0:
        return None
    by_dow: dict[int, list[float]] = {}
    for v, d in zip(values, weekdays, strict=True):
        by_dow.setdefault(d, []).append(v)
    factor = {d: (sum(xs) / len(xs)) / mean_all for d, xs in by_dow.items()}
    adj = [v / factor[d] if factor[d] > 0 else v for v, d in zip(values, weekdays, strict=True)]
    resid = [adj[i] - sum(adj[i - level_days:i]) / level_days for i in range(level_days, n)]
    if len(resid) < max_lag + 14:
        return None
    m = sum(resid) / len(resid)
    den = sum((r - m) ** 2 for r in resid)
    if den <= 0:
        return None
    raw = [sum((resid[i] - m) * (resid[i - k] - m) for i in range(k, len(resid))) / den for k in range(1, max_lag + 1)]
    acf = [0.0] * max_lag
    for i in range(0, max_lag - 1, 2):            # initial positive sequence: stop at the first lag pair that sums to <= 0
        if raw[i] + raw[i + 1] <= 0.0:
            break
        acf[i], acf[i + 1] = raw[i], raw[i + 1]
    return tuple(acf), len(resid)


def pooled_dependence(curves: Sequence[Sequence[float]]) -> tuple[float, ...] | None:
    """Lag-by-lag median of several autocorrelation curves (the portfolio's typical dependence)."""
    if not curves:
        return None
    k = len(curves[0])
    return tuple(sorted(c[i] for c in curves)[len(curves) // 2] for i in range(k))


# --- the model ---------------------------------------------------------------------------------------------------

def window_demand(path: Sequence[dict], protection_days: int, service_level: float = 0.9,
                  acf: Sequence[float] | None = None, dependence_basis: str = "given",
                  lead_time_sd_days: float = 0.0) -> WindowDemand:
    """`path`: daily rows ordered by date with q10, q50, q90 (day 1 = the day after the decision date).

    `acf`: autocorrelations at lags 1.. (see `estimate_dependence`); None = the declared AR(1) default.
    Days beyond the forecast horizon repeat the mean and sd of the last 7 forecast days (flagged in the result)."""
    if protection_days < 1:
        raise ValueError("protection_days must be at least 1")
    if not 0.5 <= service_level < 1.0:
        raise ValueError("service_level must be in [0.5, 1)")
    if not path:
        raise ValueError("forecast path is empty")
    if acf is None:
        acf, dependence_basis = ar1_acf(DEFAULT_RHO), "assumed default"
    moments = [daily_moments(p["q10"], p["q50"], p["q90"]) for p in path]
    used = moments[:protection_days]
    extra = protection_days - len(used)
    if extra > 0:
        tail = moments[-7:]
        mu_t, sd_t = sum(m for m, _ in tail) / len(tail), sum(s for _, s in tail) / len(tail)
        used = used + [(mu_t, sd_t)] * extra
    sds = [sd for _, sd in used]
    mean = sum(m for m, _ in used)
    var = window_variance(sds, acf)
    independent = sum(x * x for x in sds)
    if lead_time_sd_days > 0:
        var += (mean / protection_days) ** 2 * lead_time_sd_days ** 2
    q = gamma_quantile(mean, var, service_level)
    return WindowDemand(mean=mean, sd=math.sqrt(var), quantile=q, service_level=service_level, protection_days=protection_days,
                        variance_inflation=(var / independent) if independent > 0 else 1.0, lag1=float(acf[0]) if acf else 0.0,
                        dependence_basis=dependence_basis, extrapolated_days=max(extra, 0), lead_time_sd_days=lead_time_sd_days)
