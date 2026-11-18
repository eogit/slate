"""Data assimilation: an ensemble Kalman filter that learns tree productivity from new heights.

New height measurements (a new NLP flight, a drone survey, a field clinometer reading) are
matched to TOW objects by id or by the nearest object centroid. For each object the filter
carries an ensemble of ``(theta, age)`` drawn from its calibrated posterior and forecasts the
representative tree height at the measurement date, anchored to the lidar height as in
``scenario``:

    H = h_obs + H(theta, age + dt) - H(theta, age)

then applies the stochastic EnKF analysis (perturbed observations; Evensen 2003)

    x_i <- x_i + K (y + e_i - H x_i),   K = Cov(x, Hx) / (Var(Hx) + R)

``theta`` and age are updated through their ensemble covariances with height and clipped to
their grids. The area-level result is the mean change in ``theta`` over the updated objects,
which the parameter store keeps as a learned shift for the site, so later projections of the
whole area use it (the way DT8 learns its CH4 parameters).
"""

from __future__ import annotations

import math

import numpy as np

from .calibration import AGE_GRID
from .inventory import GROUP_HEIGHT_FACTOR, Inventory

N_ENSEMBLE = 200
OBS_SD_FLOOR = 0.5
MATCH_RADIUS_M = 15.0


def match(inv: Inventory, obs: list[dict]) -> list[int]:
    """Index of the TOW object for each observation (by ``tow_id`` or nearest centroid)."""
    ids = {str(t): i for i, t in enumerate(inv.tow_id)}
    out = []
    for o in obs:
        if o.get("tow_id") is not None:
            out.append(ids.get(str(o["tow_id"]), -1))
            continue
        dx = (inv.lon - o["lon"]) * 111_320.0 * math.cos(math.radians(o["lat"]))
        dy = (inv.lat - o["lat"]) * 111_320.0
        d = np.hypot(dx, dy)
        j = int(np.argmin(d))
        out.append(j if d[j] <= MATCH_RADIUS_M else -1)
    return out


def assimilate(bank, inv: Inventory, fit, obs: list[dict], seed: int = 0) -> dict:
    """Update (theta, age) of the matched objects; return per-object and area results.

    Each observation: ``{"tow_id" or "lon"+"lat", "year": decimal year, "height_m": tallest
    height of the object, "sd_m": error SD, "kind": "first_return" | "last_return" | "field"}``.
    """
    rng = np.random.default_rng(seed)
    idx = match(inv, obs)
    t_ref = np.nanmax(np.column_stack([inv.fz_date, inv.date_lz]), axis=1)
    cri_all = bank.cr_index(inv.crown_ratio)
    g = bank.grid
    rows, d_theta = [], []
    for o, i in zip(obs, idx):
        if i < 0 or not np.isfinite(fit.theta[i]):
            rows.append({"matched": False, **{k: o.get(k) for k in ("tow_id", "lon", "lat")}})
            continue
        th = np.clip(fit.theta[i] + fit.theta_sd[i] * rng.standard_normal(N_ENSEMBLE), g[0], g[-1])
        ag = np.clip(fit.age[i] + max(fit.age_sd[i], 1.0) * rng.standard_normal(N_ENSEMBLE),
                     AGE_GRID[0], AGE_GRID[-1])
        gf = 1.0 if inv.cls[i] == 0 else GROUP_HEIGHT_FACTOR
        dt = float(o["year"]) - t_ref[i]
        h0 = inv.height_m[i]

        def forecast(theta, age):
            return np.maximum(h0 + bank.height(theta, age + dt, cri_all[i])
                              - bank.height(theta, age, cri_all[i]), 0.5)

        hx = forecast(th, ag)
        y = float(o["height_m"]) * gf
        r = max(float(o.get("sd_m", 1.0)), OBS_SD_FLOOR) ** 2
        var = hx.var(ddof=1) + r
        yp = y + math.sqrt(r) * rng.standard_normal(N_ENSEMBLE)
        k_th = np.cov(th, hx)[0, 1] / var
        k_ag = np.cov(ag, hx)[0, 1] / var
        innov = yp - hx
        th_a = np.clip(th + k_th * innov, g[0], g[-1])
        ag_a = np.clip(ag + k_ag * innov, AGE_GRID[0], AGE_GRID[-1])
        d_theta.append(float(th_a.mean() - fit.theta[i]))
        rows.append({"matched": True, "tow_id": str(inv.tow_id[i]), "year": float(o["year"]),
                     "observed_height_m": float(o["height_m"]),
                     "forecast_height_m": float(hx.mean() / gf),
                     "forecast_sd_m": float(hx.std(ddof=1) / gf),
                     "theta_prior": float(fit.theta[i]), "theta_posterior": float(th_a.mean()),
                     "theta_posterior_sd": float(th_a.std(ddof=1)),
                     "age_prior": float(fit.age[i]), "age_posterior": float(ag_a.mean()),
                     "analysis_height_m": float(forecast(th_a, ag_a).mean() / gf)})
    n = len(d_theta)
    return {"n_observations": len(obs), "n_matched": n, "objects": rows,
            "theta_shift": float(np.mean(d_theta)) if n else 0.0,
            "theta_shift_sd": float(np.std(d_theta, ddof=1) / math.sqrt(n)) if n > 1 else None}
