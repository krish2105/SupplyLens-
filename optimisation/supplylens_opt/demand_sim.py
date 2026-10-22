"""Simulated daily demand with KNOWN day-to-day dependence, used to check the lead-time-demand model.

Demand on day t is negative-binomial with mean  base * weekday_factor * exp(z_t - s^2/2)  where z is an AR(1) latent level
(persistence `phi`, scale `s`). Persistence of the latent level is what makes consecutive days dependent. The "forecaster"
supplied here is deliberately idealised: it knows the weekday pattern and the stationary distribution, so its daily
q10/q50/q90 are calibrated marginals, but it does not know today's latent level. Real forecasters sit between this and a
forecaster that tracks the level; the study reports results at several persistence values to show the range.
"""
from __future__ import annotations

import numpy as np

WEEKDAY = np.array([1.0, 1.1, 1.0, 1.05, 1.3, 0.6, 0.45])


def simulate(n_days: int, base: float, phi: float, s: float, r: float, rng: np.random.Generator, start_dow: int = 0) -> np.ndarray:
    z = np.empty(n_days)
    z[0] = rng.normal(0, s)
    eps = rng.normal(0, s * np.sqrt(1 - phi ** 2), n_days)
    for t in range(1, n_days):
        z[t] = phi * z[t - 1] + eps[t]
    dow = (np.arange(n_days) + start_dow) % 7
    mu = base * WEEKDAY[dow] * np.exp(z - s ** 2 / 2)
    lam = rng.gamma(r, mu / r)              # gamma-Poisson = negative binomial with variance mu + mu^2 / r
    return rng.poisson(lam).astype(float)


def marginal_quantiles(base: float, s: float, r: float, rng: np.random.Generator, n: int = 40000) -> np.ndarray:
    """(7, 3) array: q10/q50/q90 of daily demand per weekday under the stationary distribution."""
    out = np.empty((7, 3))
    for d in range(7):
        z = rng.normal(0, s, n)
        mu = base * WEEKDAY[d] * np.exp(z - s ** 2 / 2)
        x = rng.poisson(rng.gamma(r, mu / r))
        out[d] = np.percentile(x, [10, 50, 90])
    return out
