"""Learn a site's livestock numbers from methane observations (linear-Gaussian update).

DT2's methane in a set of cells is linear in two site factors, one for cattle and one for
sheep and goats:

    y_i = s_cattle * c_i + s_sheep * q_i + e_i

where c_i and q_i are the cattle and small-ruminant methane DT2 predicts for observation i with
factors of 1. With a Gaussian prior on (s_cattle, s_sheep) (the site's current values and their
standard deviations) and Gaussian errors e_i, the posterior is Gaussian and has a closed form
(the Kalman update for a static state). The posterior becomes the site's new prior, so the twin
keeps learning as observations arrive.

Two kinds of observations are supported:

* ``cells``: methane per 1 km cell, for example the NAEI map (the default, shipped) or a flux
  inversion. Cells share one error standard deviation, ``rel_sd`` (default 30 %) of the mean
  observed cell. (Errors proportional to each cell's own value would favour the small cells
  and bias the factors low.) Neighbouring cells are not independent, because both DT2 and any
  gridded product spread animals with smooth proxies, so the error is inflated as if only one
  cell in ``cells_per_independent_obs`` (default 25, one per 5 km x 5 km) were independent,
  as DT4 does for Biomass CCI.
* ``total``: one area total with its standard deviation, for example from an aircraft mass
  balance or a satellite inversion.

``other_fraction`` removes the share of the observation that comes from livestock DT2 does not
model (pigs, poultry, horses, deer); about 5-10 % in England's NAEI agriculture map.
"""

from __future__ import annotations

import numpy as np


def _components(grid: dict) -> tuple[np.ndarray, np.ndarray]:
    cattle = sum(grid[g]["enteric"] + grid[g]["manure"] for g in ("dairy", "beef_other"))
    small = sum(grid[g]["enteric"] + grid[g]["manure"] for g in ("sheep", "goats"))
    return cattle, small


def update(prior: dict, H: np.ndarray, y: np.ndarray, sd: np.ndarray) -> dict:
    """Posterior of (cattle, sheep) given y = H @ s + e, e ~ N(0, diag(sd^2))."""
    m0 = np.array([prior["cattle"], prior["sheep"]])
    P0 = np.diag([prior["cattle_sd"] ** 2, prior["sheep_sd"] ** 2])
    Rinv = 1.0 / sd ** 2
    Pinv = np.linalg.inv(P0) + H.T @ (H * Rinv[:, None])
    P = np.linalg.inv(Pinv)
    m = P @ (np.linalg.inv(P0) @ m0 + H.T @ (Rinv * y))
    m = np.maximum(m, 0.0)
    return {"cattle": float(m[0]), "sheep": float(m[1]),
            "cattle_sd": float(np.sqrt(P[0, 0])), "sheep_sd": float(np.sqrt(P[1, 1])),
            "correlation": float(P[0, 1] / np.sqrt(P[0, 0] * P[1, 1]))}


def from_cells(prior: dict, grid: dict, mask: np.ndarray, obs: np.ndarray, *,
               rel_sd: float = 0.3, other_fraction: float = 0.05,
               cells_per_independent_obs: float = 25.0,
               sample: np.ndarray | None = None) -> tuple[dict, dict]:
    """Assimilate per-cell methane (t CH4/yr) over the masked cells (or ``sample`` of them)."""
    c, q = _components(grid)
    sel = mask & np.isfinite(obs) & (obs > 0) if sample is None else sample
    H = np.column_stack([c[sel], q[sel]])
    y = obs[sel] * (1.0 - other_fraction)
    if len(y) == 0:
        raise ValueError("no observed cells with methane > 0 in the area")
    sd = np.full(len(y), rel_sd * y.mean() * np.sqrt(cells_per_independent_obs))
    post = update(prior, H, y, sd)
    before = H @ np.array([prior["cattle"], prior["sheep"]])
    after = H @ np.array([post["cattle"], post["sheep"]])
    diag = {"n_obs": int(sel.sum()), "observed_t_ch4": float(y.sum()),
            "predicted_before_t_ch4": float(before.sum()),
            "predicted_after_t_ch4": float(after.sum()),
            "rmse_before_t": float(np.sqrt(np.mean((before - y) ** 2))) if len(y) else None,
            "rmse_after_t": float(np.sqrt(np.mean((after - y) ** 2))) if len(y) else None}
    return post, diag


def from_total(prior: dict, grid: dict, observed_t: float, sd_t: float,
               other_fraction: float = 0.0) -> tuple[dict, dict]:
    """Assimilate one area total (t CH4/yr) with its standard deviation."""
    c, q = _components(grid)
    H = np.array([[c.sum(), q.sum()]])
    y = np.array([observed_t * (1.0 - other_fraction)])
    post = update(prior, H, y, np.array([sd_t]))
    before = float((H @ np.array([prior["cattle"], prior["sheep"]]))[0])
    after = float((H @ np.array([post["cattle"], post["sheep"]]))[0])
    return post, {"n_obs": 1, "observed_t_ch4": float(y[0]), "predicted_before_t_ch4": before,
                  "predicted_after_t_ch4": after}
