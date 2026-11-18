"""Crown-by-crown calibration of either growth model against repeat EA lidar heights.

What is estimated
-----------------
For every tree object, two unknowns on a grid:

* ``theta``, the growth model's productivity (site index for ``size_age``, the light-use
  multiplier for ``crown_lue``), and
* ``age``, the age of the representative tree at the reference date (the latest National
  LIDAR Programme flight over the tile), 1-300 years.

Nothing else is tuned: the curve shapes, the allometry and the climate are fixed. The TOW map
is the inventory (what trees exist and how big their crowns are); lidar heights are the only
calibration data, as agreed in the concept.

Observations and operators
--------------------------
* the first-return height of the object at the reference date (``h_fz``), sigma 1.0 m;
* the last-return height at every lidar epoch (``h_lz``: old EA "LIDAR Tiles" surveys from
  1998 and every NLP flight), sigma 1.5 m. Last returns penetrate leafless or open crowns, so
  they are modelled as ``rho * H`` with ``rho`` the pilot's median ratio of last to first
  return on the same NLP night, per TOW class (one number per class, so the held-out epoch is
  never used to fit its own operator). Old surveys at 1-2 m resolution miss some crown tops;
  sigma 1.5 m allows for that.

Both operators act on the representative tree height (the tallest return for a lone tree,
``GROUP_HEIGHT_FACTOR`` times it for groups and small woods), so the observed heights are
divided by the same factor.

Disturbance
-----------
Where an earlier epoch is more than ``DROP_M`` (3 m) taller than a later one, the tree was
cut back, pollarded, or partly lost. Observations before the drop belong to a different tree
and are dropped; the drop is recorded as an event (``change.py`` analyses those). Whole trees
that were lost before the TOW map was made are invisible: the map lists only trees present in
2016-2023.

Prior
-----
Gaussian on ``theta`` around the middle of its grid with SD = a quarter of the grid range;
uniform on age. With only one epoch, theta and age trade off almost perfectly (a short tree
can be young and vigorous or old and slow); repeat epochs separate them through growth.

Validation
----------
``validate`` holds out the latest epoch (first and last return), fits each crown on the
earlier epochs alone, predicts the last-return height at the latest date, and compares the
error with a persistence baseline (no growth since the previous epoch).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .inventory import GROUP_HEIGHT_FACTOR, Inventory

SIGMA_FZ = 1.0
SIGMA_LZ = 1.5
DROP_M = 3.0
SAME_FLIGHT_YR = 0.5
MIN_POOL = 30
EB_ITERATIONS = 6
AGE_GRID = np.arange(1.0, 301.0)
TABLE_STEP = 0.5
CROWN_RATIO_BINS = np.array([0.4, 0.7, 1.0, 1.5])


@dataclass
class CrownFit:
    """Per-object posterior summaries (arrays over the inventory)."""

    theta: np.ndarray
    theta_sd: np.ndarray
    age: np.ndarray
    age_sd: np.ndarray
    n_obs: np.ndarray
    growth_m_yr: np.ndarray       # current height growth of the representative tree
    event_year: np.ndarray        # mid-year of a detected height drop (NaN if none)
    event_drop_m: np.ndarray

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def lz_ratio(inv: Inventory) -> np.ndarray:
    """Per-object last/first return ratio: the pilot median for the object's TOW class."""
    r = inv.h_lz[:, -1] / np.maximum(inv.h_fz, 0.5)
    out = np.ones(inv.n)
    for c in range(3):
        m = (inv.cls == c) & np.isfinite(r)
        if m.sum() >= 5:
            out[inv.cls == c] = float(np.clip(np.median(r[m]), 0.5, 1.0))
    return out


def observations(inv: Inventory, holdout_last: bool = False):
    """Observation times, heights (of the representative tree) and sigmas per object.

    Returns ``t`` (object, k) decimal years, ``h`` (object, k) and ``s`` (object, k), NaN
    where missing; column 0 is the first-return height, the rest are last-return epochs.
    Also returns the detected height-drop events.
    """
    g = np.where(inv.cls == 0, 1.0, GROUP_HEIGHT_FACTOR)
    rho = lz_ratio(inv)
    t = np.column_stack([inv.fz_date, inv.date_lz]).astype(float)
    h = np.column_stack([inv.h_fz * g, inv.h_lz * g[:, None] / rho[:, None]]).astype(float)
    s = np.column_stack([np.full(inv.n, SIGMA_FZ),
                         np.full(inv.h_lz.shape, SIGMA_LZ)]).astype(float)
    if holdout_last:
        h[:, 0] = np.nan
        h[:, -1] = np.nan
    bad = ~np.isfinite(h) | ~np.isfinite(t)
    h[bad] = np.nan
    t[bad] = np.nan
    ev_year = np.full(inv.n, np.nan)
    ev_drop = np.full(inv.n, np.nan)
    order = np.argsort(np.where(np.isnan(t), np.inf, t), axis=1)
    for i in range(inv.n):
        ti, hi = t[i, order[i]], h[i, order[i]]
        ok = np.isfinite(hi)
        ti, hi = ti[ok], hi[ok]
        if hi.size < 2:
            continue
        # the latest index j such that some earlier observation exceeds hi[j] by DROP_M
        # observations on the same night (first and last return) are never a "drop"
        later_min = np.minimum.accumulate(hi[::-1])[::-1]
        drops = [j for j in range(hi.size - 1)
                 if ti[j + 1] - ti[j] > SAME_FLIGHT_YR and hi[j] - later_min[j + 1] > DROP_M]
        if drops:
            j = drops[-1]
            k = j + 1 + int(np.argmin(hi[j + 1:]))
            ev_year[i] = 0.5 * (ti[j] + ti[j + 1])
            ev_drop[i] = hi[j] - hi[k]
            cut = ti[j]
            gone = t[i] <= cut
            h[i, gone] = np.nan
    return t, h, s, ev_year, ev_drop


def _tables(model, ages_max: float = 340.0):
    """Height tables for each crown-ratio bin on a half-year age grid."""
    ages = np.arange(0.0, ages_max + TABLE_STEP, TABLE_STEP)
    return ages, {cr: model.height_table(ages, cr) for cr in CROWN_RATIO_BINS}


def theta_prior(model) -> tuple[float, float]:
    g = model.theta_grid
    return 0.5 * (g[0] + g[-1]), 0.25 * (g[-1] - g[0])


def fit_crowns(model, inv: Inventory, holdout_last: bool = False,
               prior: tuple[float, float] | None = None) -> CrownFit:
    """Grid posterior over (theta, age) for every object of an inventory.

    ``prior`` is (mean, sd) of the Gaussian theta prior; the default is the broad prior of
    ``theta_prior``. ``calibrate`` replaces it with the pilot's own distribution.
    """
    t, h, s, ev_year, ev_drop = observations(inv, holdout_last)
    ages, tables = _tables(model)
    grid = model.theta_grid
    mu, sd = prior or theta_prior(model)
    log_prior = -0.5 * ((grid - mu) / sd) ** 2
    t_ref = np.nanmax(np.column_stack([inv.fz_date, inv.date_lz]), axis=1)
    cr_bin = CROWN_RATIO_BINS[np.argmin(np.abs(inv.crown_ratio[:, None] - CROWN_RATIO_BINS), 1)]
    n = inv.n
    out = {k: np.full(n, np.nan) for k in ("theta", "theta_sd", "age", "age_sd", "growth")}
    n_obs = np.zeros(n, int)
    for i in range(n):
        ok = np.isfinite(h[i])
        n_obs[i] = int(ok.sum())
        if not ok.any():
            continue
        table = tables[cr_bin[i]]
        dt = t_ref[i] - t[i, ok]                                 # years before reference
        a = AGE_GRID[:, None] - dt[None, :]                       # (age, obs)
        idx = np.clip(a / TABLE_STEP, 0, ages.size - 1)
        lo = np.floor(idx).astype(int)
        hi = np.minimum(lo + 1, ages.size - 1)
        w = idx - lo
        pred = table[:, lo] * (1 - w) + table[:, hi] * w           # (theta, age, obs)
        pred = np.where(a[None] < 0, 0.0, pred)
        ll = -0.5 * (((pred - h[i, ok]) / s[i, ok]) ** 2).sum(-1) + log_prior[:, None]
        p = np.exp(ll - ll.max())
        p /= p.sum()
        pt, pa = p.sum(1), p.sum(0)
        out["theta"][i] = (pt * grid).sum()
        out["theta_sd"][i] = np.sqrt((pt * (grid - out["theta"][i]) ** 2).sum())
        out["age"][i] = (pa * AGE_GRID).sum()
        out["age_sd"][i] = np.sqrt((pa * (AGE_GRID - out["age"][i]) ** 2).sum())
        j = np.clip((AGE_GRID / TABLE_STEP).astype(int), 0, ages.size - 3)
        rate = (table[:, j + 2] - table[:, j]) / (2 * TABLE_STEP)     # m/yr at each age
        out["growth"][i] = (p * rate).sum()
    return CrownFit(theta=out["theta"], theta_sd=out["theta_sd"], age=out["age"],
                    age_sd=out["age_sd"], n_obs=n_obs, growth_m_yr=out["growth"],
                    event_year=ev_year, event_drop_m=ev_drop)


def distinct_epochs(t: np.ndarray, h: np.ndarray) -> np.ndarray:
    """Number of distinct flight dates with a usable observation, per object."""
    tt = np.where(np.isfinite(h), np.round(t, 1), np.nan)
    return np.array([np.unique(r[np.isfinite(r)]).size for r in tt])


def pilot_prior(model, fit: CrownFit, n_epochs: np.ndarray) -> tuple[float, float] | None:
    """Empirical-Bayes theta prior from the objects whose growth was observed.

    Objects seen on two or more dates have their productivity pinned down by growth; their
    posterior means give the pilot's distribution of theta (median and robust spread, floored
    at a tenth of the grid range). Single-date objects then borrow it, which is what makes a
    one-epoch tree's projected growth realistic. ``None`` if fewer than ``MIN_POOL`` objects.
    """
    m = np.isfinite(fit.theta) & (n_epochs >= 2) & ~np.isfinite(fit.event_year)
    if m.sum() < MIN_POOL:
        return None
    th = fit.theta[m]
    g = model.theta_grid
    spread = (np.percentile(th, 75) - np.percentile(th, 25)) / 1.349
    return float(np.median(th)), float(max(spread, 0.1 * (g[-1] - g[0])))


def empirical_prior(model, inv: Inventory, holdout_last: bool = False,
                    n_iter: int = EB_ITERATIONS) -> tuple[float, float] | None:
    """Iterated empirical-Bayes theta prior for a pilot (``None`` if too few objects).

    Starting from the broad prior, objects seen on two or more dates are fitted, the prior is
    replaced by the distribution of their posterior means, and the fit is repeated. Iterating
    removes the pull of the broad prior's centre on the first pass, which otherwise makes the
    pilot prior (and so the growth of single-date trees) too high.
    """
    t, h, _, _, _ = observations(inv, holdout_last)
    n_ep = distinct_epochs(t, h)
    multi = n_ep >= 2
    if multi.sum() < MIN_POOL:
        return None
    sub = inv.select(multi)
    prior = None
    for _ in range(n_iter):
        fit = fit_crowns(model, sub, holdout_last, prior)
        new = pilot_prior(model, fit, n_ep[multi])
        if new is None:
            return prior
        if prior is not None and abs(new[0] - prior[0]) < 0.01 * (model.theta_grid[-1] - model.theta_grid[0]):
            return new
        prior = new
    return prior


def calibrate(model, inv: Inventory, holdout_last: bool = False):
    """Calibrate every object with the pilot's empirical theta prior.

    Returns ``(fit, prior)``; ``prior`` is the empirical prior (or the broad default if too
    few objects were seen on two dates).
    """
    prior = empirical_prior(model, inv, holdout_last) or theta_prior(model)
    return fit_crowns(model, inv, holdout_last, prior), prior


def predict_height(model, inv: Inventory, fit: CrownFit, t_ref_from, t_target) -> np.ndarray:
    """Representative-tree height at ``t_target`` from a fit referenced to ``t_ref_from``."""
    ages, tables = _tables(model)
    cr_bin = CROWN_RATIO_BINS[np.argmin(np.abs(inv.crown_ratio[:, None] - CROWN_RATIO_BINS), 1)]
    out = np.full(inv.n, np.nan)
    for cr, table in tables.items():
        m = (cr_bin == cr) & np.isfinite(fit.theta)
        if not m.any():
            continue
        age = fit.age[m] - (t_ref_from[m] - t_target[m])
        for k, (th, ag) in enumerate(zip(fit.theta[m], age)):
            row = np.array([np.interp(ag, ages, r) for r in table])
            out[np.flatnonzero(m)[k]] = np.interp(th, model.theta_grid, row)
    return out


def validate(model, inv: Inventory) -> dict:
    """Hold-out test of the latest epoch against persistence (see module docstring).

    Two-fold by object: the empirical theta prior for one half is learned from the *other*
    half, fitted on all its epochs, so no held-out height ever informs its own forecast. Each
    half is then fitted without its latest epoch and forecast to the latest flight date.
    """
    t, h_all, _, ev_all, _ = observations(inv, holdout_last=False)
    t_ho, h_ho, _, _, _ = observations(inv, holdout_last=True)
    n_train = distinct_epochs(t_ho, h_ho)
    fold = np.arange(inv.n) % 2
    fit = CrownFit(*[np.full(inv.n, np.nan) for _ in range(5)], np.full(inv.n, np.nan),
                   np.full(inv.n, np.nan), np.full(inv.n, np.nan))
    fit.n_obs = np.zeros(inv.n, int)
    priors = []
    for k in (0, 1):
        train = fold != k
        prior = empirical_prior(model, inv.select(train)) or theta_prior(model)
        priors.append(list(prior))
        test = ~train
        f = fit_crowns(model, inv.select(test), holdout_last=True, prior=prior)
        for name, v in f.as_dict().items():
            getattr(fit, name)[test] = v
    t_last = t[:, -1]
    # the fit's reference date is still the latest flight; the latest observations were
    # removed, so the height at the fitted age is a genuine forecast from earlier epochs
    pred = predict_height(model, inv, fit, t_last, t_last)
    hk = h_all[:, 1:-1]
    tk = np.where(np.isfinite(hk), t[:, 1:-1], -np.inf)
    j = np.argmax(tk, axis=1)
    persist = hk[np.arange(inv.n), j]
    gap = t_last - tk[np.arange(inv.n), j]
    m = (np.isfinite(fit.theta) & np.isfinite(h_all[:, -1]) & np.isfinite(pred)
         & np.isfinite(persist) & ~np.isfinite(ev_all) & (gap > SAME_FLIGHT_YR))
    if not m.any():
        return {"n": 0}

    def block(mask):
        obs = h_all[mask, -1]
        e_mod, e_per = pred[mask] - obs, persist[mask] - obs

        def stats(e):
            return {"rmse_m": float(np.sqrt(np.mean(e ** 2))), "bias_m": float(np.mean(e)),
                    "mae_m": float(np.mean(np.abs(e)))}

        sm, sp = stats(e_mod), stats(e_per)
        return {"n": int(mask.sum()), "years_ahead_median": float(np.median(gap[mask])),
                "model": sm, "persistence": sp,
                "skill_vs_persistence": float(1 - sm["rmse_m"] ** 2 / sp["rmse_m"] ** 2),
                "observed_growth_m_yr_median": float(np.median((obs - persist[mask]) / gap[mask])),
                "predicted_growth_m_yr_median": float(np.median((pred[mask] - persist[mask])
                                                                / gap[mask]))}

    out = block(m)
    out["prior_theta_by_fold"] = priors
    multi = m & (n_train >= 2)
    out["trained_on_2plus_epochs"] = block(multi) if multi.sum() >= 10 else {"n": int(multi.sum())}
    return out


def observed_growth(inv: Inventory) -> dict:
    """Median last-return height growth between the first and last lidar epochs."""
    t, h, _, ev, _ = observations(inv)
    lz_t, lz_h = t[:, 1:], h[:, 1:]
    first = np.argmax(np.isfinite(lz_h), axis=1)
    i = np.arange(inv.n)
    dt = lz_t[:, -1] - lz_t[i, first]
    rate = (lz_h[:, -1] - lz_h[i, first]) / np.where(dt > 1, dt, np.nan)
    rate = rate[np.isfinite(rate)]
    if rate.size == 0:
        return {"n": 0}
    return {"n": int(rate.size), "median_m_yr": float(np.median(rate)),
            "p05_m_yr": float(np.percentile(rate, 5)), "p95_m_yr": float(np.percentile(rate, 95)),
            "height_drops": int(np.isfinite(ev).sum())}


def summarise(fit: CrownFit, model) -> dict:
    ok = np.isfinite(fit.theta)
    th, ag = fit.theta[ok], fit.age[ok]
    if th.size == 0:
        return {"n": 0}
    return {"n": int(ok.sum()), "theta_name": model.theta_name,
            "theta_median": float(np.median(th)), "theta_p25": float(np.percentile(th, 25)),
            "theta_p75": float(np.percentile(th, 75)),
            "theta_sd_median": float(np.median(fit.theta_sd[ok])),
            "age_median": float(np.median(ag)), "age_p25": float(np.percentile(ag, 25)),
            "age_p75": float(np.percentile(ag, 75)),
            "growth_m_yr_median": float(np.median(fit.growth_m_yr[ok])),
            "multi_epoch_share": float(np.mean(fit.n_obs[ok] >= 3))}
