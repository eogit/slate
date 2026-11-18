"""Data assimilation: an ensemble Kalman filter that blends a growth model with CCI AGB.

The filter tracks, for one stand or area, an ensemble of members with two state variables:
AGB and the model's productivity ``theta`` (yield class or 3-PG fertility rating). Carrying
``theta`` in the state (state augmentation) is what lets the filter *learn* the site's
productivity from observations, the way DT8 learns its CH4 parameters.

Forecast. Each member moves one year along its own unthinned growth curve: its current AGB
is converted to an "equivalent age" on the curve for its ``theta`` and the curve is read one
year later (so a thinned or disturbed member regrows from where it is, not from where the
curve says it should be). Process noise of ``PROCESS_SD_FRACTION`` of AGB plus
``PROCESS_SD_MIN`` Mg/ha stands for everything the curve leaves out. Curves come from the
model's lookup table, interpolated between productivity grid points, so the filter works
the same way for yield curves and 3-PG.

Analysis. In years with an observation (a CCI v7 map, or values passed in by the caller),
each member is updated with the stochastic EnKF (perturbed observations; Evensen 2003):

    x_i <- x_i + K (y + e_i - H x_i),   K = Cov(x, Hx) / (Var(Hx) + R),   e_i ~ N(0, R)

with H selecting AGB and R the observation variance (the CCI SD squared). ``theta`` is
updated through its ensemble covariance with AGB and clipped to the model's grid.
"""

from __future__ import annotations

import numpy as np

PROCESS_SD_FRACTION = 0.04
PROCESS_SD_MIN = 2.0
OBS_SD_FLOOR = 5.0


class CurveBank:
    """Unthinned AGB curves for a productivity grid, with interpolation in theta."""

    def __init__(self, model, max_age: int = 300):
        self.grid = model.theta_grid()
        table = model.agb_table(self.grid, max_age)
        self.table = np.maximum.accumulate(table, axis=1)  # monotonic for inversion
        self.ages = np.arange(max_age + 1, dtype=float)

    def _rows(self, theta):
        t = np.clip(np.asarray(theta, float), self.grid[0], self.grid[-1])
        i = np.clip(np.searchsorted(self.grid, t) - 1, 0, self.grid.size - 2)
        w = (t - self.grid[i]) / (self.grid[i + 1] - self.grid[i])
        return i, w

    def curve(self, theta) -> np.ndarray:
        """AGB-by-age curves for each theta, shape (n, ages)."""
        i, w = self._rows(theta)
        return (1 - w)[:, None] * self.table[i] + w[:, None] * self.table[i + 1]

    def agb_at(self, theta, age) -> np.ndarray:
        c = self.curve(theta)
        a = np.asarray(age, float)
        return np.array([np.interp(a[k], self.ages, c[k]) for k in range(c.shape[0])])

    def step(self, theta, agb) -> np.ndarray:
        """Move each member one year along its curve from its current AGB."""
        c = self.curve(theta)
        out = np.empty(c.shape[0])
        for k in range(c.shape[0]):
            eq_age = np.interp(agb[k], c[k], self.ages)
            out[k] = np.interp(eq_age + 1.0, self.ages, c[k])
        return out


def enkf(model, years, obs_agb, obs_sd, *, prior_theta: float, prior_theta_sd: float,
         start_year: int | None = None, prior_age: float | None = None,
         prior_agb: float | None = None, prior_agb_sd: float | None = None,
         n_members: int = 100, seed: int = 0, bank: CurveBank | None = None) -> dict:
    """Run the filter over consecutive years from ``start_year`` to the last observation.

    ``years``, ``obs_agb`` and ``obs_sd`` list the observations (gaps are fine, e.g. no CCI
    maps in 2013-2014). The initial AGB ensemble comes from ``prior_agb`` (+- ``prior_agb_sd``)
    if given, else from each member's curve at ``prior_age``, else from the first observation.
    """
    rng = np.random.default_rng(seed)
    bank = bank or CurveBank(model)
    years = [int(y) for y in years]
    obs = dict(zip(years, np.asarray(obs_agb, float)))
    osd = dict(zip(years, np.maximum(np.asarray(obs_sd, float), OBS_SD_FLOOR)))
    y0 = start_year if start_year is not None else min(years)
    y1 = max(years)
    n = n_members
    theta = np.clip(rng.normal(prior_theta, prior_theta_sd, n), bank.grid[0], bank.grid[-1])
    if prior_agb is not None:
        agb = np.maximum(rng.normal(prior_agb, prior_agb_sd or 0.2 * prior_agb + 5, n), 0.0)
    elif prior_age is not None:
        agb = bank.agb_at(theta, np.full(n, float(prior_age)))
    else:
        first = min(years)
        agb = np.maximum(rng.normal(obs[first], osd[first], n), 0.0)

    rows = []
    for year in range(y0, y1 + 1):
        if year > y0:
            agb = bank.step(theta, agb)
            agb = np.maximum(agb + rng.normal(0, PROCESS_SD_FRACTION * agb + PROCESS_SD_MIN), 0.0)
        f_mean, f_sd = float(agb.mean()), float(agb.std(ddof=1))
        row = {"year": year, "forecast_agb_mean": f_mean, "forecast_agb_sd": f_sd}
        if year in obs:
            y, r = obs[year], osd[year] ** 2
            hx = agb
            var_hx = float(np.var(hx, ddof=1))
            k_agb = var_hx / (var_hx + r)
            cov_th = float(np.cov(theta, hx, ddof=1)[0, 1])
            k_th = cov_th / (var_hx + r)
            pert = y + rng.normal(0, np.sqrt(r), n)
            innov = pert - hx
            agb = np.maximum(agb + k_agb * innov, 0.0)
            theta = np.clip(theta + k_th * innov, bank.grid[0], bank.grid[-1])
            row.update({"observed_agb": float(y), "observed_sd": float(np.sqrt(r)),
                        "innovation": float(y - f_mean), "gain": k_agb})
        row.update({"analysis_agb_mean": float(agb.mean()),
                    "analysis_agb_sd": float(agb.std(ddof=1)),
                    "theta_mean": float(theta.mean()), "theta_sd": float(theta.std(ddof=1))})
        rows.append(row)
    return {"model": model.name, "years": rows, "theta_mean": float(theta.mean()),
            "theta_sd": float(theta.std(ddof=1)), "agb_mean": float(agb.mean()),
            "agb_sd": float(agb.std(ddof=1)), "n_members": n,
            "n_observations": len(years)}


def synthetic_observations(model, *, theta_true: float, age_start: float, years,
                           noise_frac: float = 0.15, seed: int = 1,
                           bank: CurveBank | None = None) -> dict:
    """AGB observations from the model itself with known productivity, plus noise."""
    rng = np.random.default_rng(seed)
    bank = bank or CurveBank(model)
    years = [int(y) for y in years]
    ages = np.array([age_start + (y - years[0]) for y in years], float)
    truth = bank.agb_at(np.full(len(years), theta_true), ages)
    sd = noise_frac * truth + 5.0
    return {"years": years, "truth": truth, "obs": truth + rng.normal(0, sd), "sd": sd}
