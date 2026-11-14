"""Calibrating both growth models to ESA Biomass CCI v7 (and only to it).

Each landscape is a mosaic of stands of different ages, so its mean AGB says little about
growth on its own (Thetford's mean barely moves from 2005 to 2024 because growth and felling
balance). DT4 therefore calibrates **pixel by pixel**: every 100 m woodland pixel is treated
as one even-aged stand with two unknowns, its productivity ``theta`` (yield class, or the 3-PG
fertility rating) and its age, and both are fitted to that pixel's 18-year CCI trajectory.

For each model a lookup table of unthinned AGB against age is built for every productivity
on a grid (:meth:`agb_table`), and each pixel takes the (theta, age) pair that minimises

    sum_years ((CCI - model) / SD)^2  +  ((theta - theta_prior) / theta_prior_sd)^2

with the CCI per-pixel SD (floored at 10 Mg/ha) as the observation error and a weak prior
on productivity that keeps flat or saturated trajectories from drifting to the grid edges.

Pixels with a stand-replacing loss (a clearfell or windthrow detected in CCI, see
:func:`forest.cci.stand_replacing_events`) are fitted only from the year of the loss, with
the restocked stand's age forced to 0-3 years at that point.

The landscape's productivity is then the distribution of pixel values (median, quartiles,
spread), and the model's skill is measured two ways:

* **fit**: RMSE, bias and R^2 of model against CCI over the fitting years;
* **hold-out**: fit on 2005-2017, predict 2018-2024 for every pixel without a stand-replacing
  loss in the hold-out years, and compare with CCI. This is the fair test for comparing the
  yield curves and 3-PG, because neither model has seen those years.

Limitations to keep in mind. C- and L-band SAR saturate at high biomass, so CCI tends to
underestimate the densest stands, which pulls calibrated productivity down. The fitted
"stand" is an unthinned one: thinning in the real forest also lowers the calibrated
productivity. Sensor changes between 2012 and 2015 can shift CCI levels; the residuals are
reported per epoch so this shows up.
"""

from __future__ import annotations

import numpy as np

from . import cci

PIXEL_CHUNK = 64
RESTOCK_MAX_AGE = 3


def _pixel_index(cube: cci.Cube, mask: np.ndarray, n_sample: int | None, seed: int):
    rows, cols = np.nonzero(mask)
    if n_sample and rows.size > n_sample:
        pick = np.sort(np.random.default_rng(seed).choice(rows.size, n_sample, replace=False))
        rows, cols = rows[pick], cols[pick]
    return rows, cols


def fit_pixels(model, cube: cci.Cube, mask: np.ndarray, fit_years, n_sample: int | None = 2000,
               seed: int = 0, max_age: int = 200, prior_sd: float | None = None) -> dict:
    """Fit (theta, age) to each sampled pixel's CCI trajectory over ``fit_years``."""
    fit_years = list(fit_years)
    rows, cols = _pixel_index(cube, mask, n_sample, seed)
    yi = [cube.year_index(y) for y in fit_years]
    obs = cube.agb[yi][:, rows, cols].T                        # (P, Y)
    sd = np.maximum(cube.sd[yi][:, rows, cols].T, cci.SD_FLOOR_MG_HA)
    ev = cci.stand_replacing_events(cube, mask, fit_years)["year"][rows, cols]
    years = np.array(fit_years)
    y0 = years[0]
    ref_year = np.where(ev > 0, ev, y0)                       # first year each pixel is fitted
    weight = (years[None, :] >= ref_year[:, None]).astype(float)
    dy = np.maximum(years[None, :] - ref_year[:, None], 0)     # (P, Y) years since ref

    grid = model.theta_grid()
    table = model.agb_table(grid, max_age)                     # (T, A+1)
    span = int(years[-1] - y0)
    ages = np.arange(0, max_age - span)                        # candidate age at ref year
    prior = model.theta_default()
    psd = prior_sd if prior_sd is not None else (grid.max() - grid.min()) / 2.0
    prior_cost = ((grid - prior) / psd) ** 2                   # (T,)

    best_t = np.empty(rows.size)
    best_a = np.empty(rows.size)
    best_cost = np.empty(rows.size)
    for s in range(0, rows.size, PIXEL_CHUNK):
        e = min(s + PIXEL_CHUNK, rows.size)
        idx = np.clip(ages[None, :, None] + dy[s:e, None, :], 0, max_age)   # (p, A, Y)
        pred = table[:, idx]                                               # (T, p, A, Y)
        r = (obs[None, s:e, None, :] - pred) / sd[None, s:e, None, :]
        cost = (r ** 2 * weight[None, s:e, None, :]).sum(-1)               # (T, p, A)
        cost = cost + prior_cost[:, None, None]
        restock = ev[s:e] > 0
        if restock.any():
            cost[:, restock, RESTOCK_MAX_AGE + 1:] = np.inf
        flat = cost.transpose(1, 0, 2).reshape(e - s, -1)
        k = flat.argmin(axis=1)
        ti, ai = np.unravel_index(k, (grid.size, ages.size))
        best_t[s:e], best_a[s:e] = grid[ti], ages[ai]
        best_cost[s:e] = flat[np.arange(e - s), k]
    return {"rows": rows, "cols": cols, "theta": best_t, "age_ref": best_a,
            "ref_year": ref_year, "event_year": ev, "cost": best_cost, "table": table,
            "grid": grid, "max_age": max_age}


def predict(fit: dict, years) -> np.ndarray:
    """Model AGB (P, Y) for the fitted pixels in ``years`` (no harvest after the fit)."""
    years = np.asarray(list(years))
    gi = np.searchsorted(fit["grid"], fit["theta"])
    age = fit["age_ref"][:, None] + (years[None, :] - fit["ref_year"][:, None])
    valid = age >= 0
    idx = np.clip(age, 0, fit["max_age"]).astype(int)
    pred = fit["table"][gi[:, None], idx]
    return np.where(valid, pred, np.nan)


def _skill(obs: np.ndarray, pred: np.ndarray) -> dict:
    ok = np.isfinite(pred) & np.isfinite(obs)
    o, p = obs[ok], pred[ok]
    if o.size == 0:
        return {"rmse_mg_ha": None, "bias_mg_ha": None, "r2": None, "n": 0}
    res = p - o
    ss_tot = float(((o - o.mean()) ** 2).sum())
    return {"rmse_mg_ha": float(np.sqrt((res ** 2).mean())), "bias_mg_ha": float(res.mean()),
            "r2": float(1 - (res ** 2).sum() / ss_tot) if ss_tot > 0 else None, "n": int(o.size)}


def calibrate(model, cube: cci.Cube, mask: np.ndarray | None = None, fit_years=None,
              holdout_years=None, n_sample: int | None = 2000, seed: int = 0) -> dict:
    """Calibrate ``model`` on a landscape (or a masked part of it). See the module doc."""
    mask = cube.woodland if mask is None else mask
    fit_years = list(cube.years if fit_years is None else fit_years)
    holdout_years = list(holdout_years or [])
    fit = fit_pixels(model, cube, mask, fit_years, n_sample=n_sample, seed=seed)
    rows, cols = fit["rows"], fit["cols"]

    fi = [cube.year_index(y) for y in fit_years]
    obs_fit = cube.agb[fi][:, rows, cols].T
    pred_fit = predict(fit, fit_years)
    used = np.array(fit_years)[None, :] >= fit["ref_year"][:, None]
    pred_fit = np.where(used, pred_fit, np.nan)

    theta = fit["theta"]
    last_year = cube.years[-1]
    age_last = fit["age_ref"] + (last_year - fit["ref_year"])
    pre = np.array([y <= cci.EPOCH_BREAK[0] for y in fit_years])
    res = pred_fit - obs_fit
    out = {
        "model": model.name, "species": model.species, "landscape": cube.key,
        "productivity_name": model.productivity_name,
        "productivity_unit": model.productivity_unit,
        "cci_version": cci.CCI_VERSION, "fit_years": fit_years, "holdout_years": holdout_years,
        "n_pixels": int(rows.size), "n_woodland_pixels": int(mask.sum()),
        "n_restocked_in_fit": int((fit["event_year"] > 0).sum()),
        "theta_median": float(np.median(theta)), "theta_mean": float(theta.mean()),
        "theta_sd": float(theta.std()), "theta_p25": float(np.percentile(theta, 25)),
        "theta_p75": float(np.percentile(theta, 75)),
        "theta_at_grid_edge_frac": float(np.mean((theta == fit["grid"].min()) |
                                                 (theta == fit["grid"].max()))),
        "age_median_last_cci_year": float(np.median(age_last)),
        "age_p25_last_cci_year": float(np.percentile(age_last, 25)),
        "age_p75_last_cci_year": float(np.percentile(age_last, 75)),
        "last_cci_year": int(last_year),
        "fit": _skill(obs_fit, pred_fit),
        "residual_mean_pre_2013_mg_ha": float(np.nanmean(res[:, pre])) if pre.any() else None,
        "residual_mean_post_2014_mg_ha": float(np.nanmean(res[:, ~pre])) if (~pre).any() else None,
        "landscape_mean_observed": [float(x) for x in np.nanmean(np.where(used, obs_fit, np.nan), 0)],
        "landscape_mean_model": [float(x) for x in np.nanmean(pred_fit, 0)],
    }
    if holdout_years:
        hi = [cube.year_index(y) for y in holdout_years]
        obs_h = cube.agb[hi][:, rows, cols].T
        ev_h = cci.stand_replacing_events(cube, mask, [fit_years[-1]] + holdout_years)["year"][rows, cols]
        keep = ev_h == 0
        pred_h = predict(fit, holdout_years)
        out["holdout"] = _skill(obs_h[keep], pred_h[keep])
        out["holdout"]["pixels_excluded_for_harvest"] = int((~keep).sum())
        out["holdout_landscape_mean_observed"] = [float(x) for x in obs_h[keep].mean(0)]
        out["holdout_landscape_mean_model"] = [float(x) for x in np.nanmean(pred_h[keep], 0)]
    return out
