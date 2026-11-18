"""Ensemble projections of trees outside woodland: baseline growth, ash dieback, new planting.

How a projection works
----------------------
Every selected TOW object keeps its own calibrated productivity ``theta_i`` (with its
posterior SD) and age ``a_i`` at its reference lidar date ``t_i`` (``calibration``). For a
calendar year ``Y`` its representative tree height is anchored to what lidar saw and grown
along its own curve:

    H_i(Y) = h_obs_i + [ H(theta, a_i + Y - t_i) - H(theta, a_i) ]

so the projection starts from the measured tree, not from a curve that may miss it. AGB is
the crown allometry for the tree's crown ratio, times its number of trees and the fraction
still alive. Each ensemble member draws:

* ``theta`` per object from N(theta_i, sd_i), clipped to the model grid (growth uncertainty);
* a crown-level allometric residual, lognormal with ``allometry.SIGMA_TREE`` (fixed in time);
* a systematic allometry factor for the whole area, lognormal SD ``allometry.SYSTEMATIC_SD``;
* the conifer share from a Beta distribution around the pilot prior (leaf type is unknown);
* for ash dieback, the ash share of broadleaved trees and the final ash mortality.

Background mortality of open-grown trees is ``BACKGROUND_MORTALITY`` (0.5 % of trees a year,
mostly from field-boundary removal and old-tree collapse; Brown & Fisher 2009 for hedgerow
trees). Dead trees go to firewood (``carbon.FIREWOOD_FRACTION``) or stay as deadwood.

Ash dieback (*Hymenoscyphus fraxineus*)
---------------------------------------
Cumulative ash mortality ``M(t) = m_max (1 - exp(-t / tau))`` from the scenario start,
``m_max`` 0.8 and ``tau`` 10 years by default (Coker et al. 2019 project 50-95 % mortality;
Hill et al. 2019). Ash is assumed to be ``ash_share`` (default 0.15) of broadleaved trees
outside woodland; no open map gives the true share, so it is drawn per member. Optionally a
share of dead ash is replanted with young trees of the pilot's typical productivity.

New planting
------------
``planting`` grows a cohort of new trees (hedgerow trees, agroforestry, riparian buffers or
street trees) from 1.3 m saplings along the pilot's calibrated curve with establishment
survival by type, then background mortality.
"""

from __future__ import annotations

import numpy as np

from . import allometry, carbon
from .calibration import CROWN_RATIO_BINS, TABLE_STEP
from .crown_lue import H_START
from .inventory import Inventory

BACKGROUND_MORTALITY = 0.005
P_CONIFER_CONCENTRATION = 20.0
PLANTING_TYPES = {
    # establishment survival after 5 years, crown ratio of the grown tree, trees per km (info)
    "hedgerow": {"survival": 0.85, "crown_ratio": 0.7},
    "agroforestry": {"survival": 0.90, "crown_ratio": 0.6},
    "riparian": {"survival": 0.85, "crown_ratio": 0.6},
    "urban": {"survival": 0.75, "crown_ratio": 0.6},
}
ASH_DEFAULTS = {"ash_share": 0.15, "m_max": 0.8, "tau_years": 10.0}


class HeightBank:
    """Height tables H(theta, age) for each crown-ratio bin, with fast bilinear lookup."""

    def __init__(self, model, max_age: float = 450.0):
        self.model = model
        self.grid = model.theta_grid
        self.ages = np.arange(0.0, max_age + TABLE_STEP, TABLE_STEP)
        self.tables = np.stack([model.height_table(self.ages, cr) for cr in CROWN_RATIO_BINS])

    @staticmethod
    def cr_index(crown_ratio) -> np.ndarray:
        return np.argmin(np.abs(np.asarray(crown_ratio, float)[..., None] - CROWN_RATIO_BINS), -1)

    def height(self, theta, age, cr_idx) -> np.ndarray:
        theta, age, cr_idx = np.broadcast_arrays(np.asarray(theta, float),
                                                 np.asarray(age, float), np.asarray(cr_idx))
        g = self.grid
        tq = np.clip(theta, g[0], g[-1])
        i = np.clip(np.searchsorted(g, tq) - 1, 0, g.size - 2)
        wt = (tq - g[i]) / (g[i + 1] - g[i])
        aq = np.clip(age, 0.0, self.ages[-1]) / TABLE_STEP
        j = np.clip(np.floor(aq).astype(int), 0, self.ages.size - 2)
        wa = aq - j
        T = self.tables
        h00, h01 = T[cr_idx, i, j], T[cr_idx, i, j + 1]
        h10, h11 = T[cr_idx, i + 1, j], T[cr_idx, i + 1, j + 1]
        return ((1 - wt) * ((1 - wa) * h00 + wa * h01) + wt * ((1 - wa) * h10 + wa * h11))


def _summ(x: np.ndarray) -> dict:
    """Mean and 5-95 % range across members for each year (x is members x years)."""
    return {"mean": np.mean(x, 0).tolist(), "p05": np.percentile(x, 5, 0).tolist(),
            "p95": np.percentile(x, 95, 0).tolist()}


def _draw_p_conifer(rng, p, n):
    if p <= 0:
        return np.zeros(n)
    c = P_CONIFER_CONCENTRATION
    return rng.beta(p * c, (1 - p) * c, n)


def simulate(bank: HeightBank, inv: Inventory, fit, start_year: int = 2025, years: int = 50,
             n_members: int = 50, seed: int = 0, theta_shift: float = 0.0,
             ash: dict | None = None, replant_share: float = 0.0,
             firewood_fraction: float = carbon.FIREWOOD_FRACTION) -> dict:
    """Project the selected trees; ``ash`` switches on ash dieback (see ``ASH_DEFAULTS``)."""
    rng = np.random.default_rng(seed)
    ok = np.isfinite(fit.theta)
    n_obj = int(ok.sum())
    if n_obj == 0:
        raise ValueError("no calibrated trees in the selection")
    theta0, sd0, age0 = fit.theta[ok] + theta_shift, fit.theta_sd[ok], fit.age[ok]
    t_ref = np.nanmax(np.column_stack([inv.fz_date, inv.date_lz]), axis=1)[ok]
    h_obs = inv.height_m[ok]
    cr = inv.crown_ratio[ok]
    cri = bank.cr_index(cr)
    n_trees = inv.n_trees[ok].astype(float)
    g = bank.grid
    yrs = np.arange(years + 1)
    cal = start_year + yrs
    M, Yn = n_members, years + 1

    theta = np.clip(theta0[None] + sd0[None] * rng.standard_normal((M, n_obj)), g[0], g[-1])
    resid = np.exp(allometry.SIGMA_TREE * rng.standard_normal((M, n_obj))
                   - 0.5 * allometry.SIGMA_TREE ** 2)
    system = np.exp(allometry.SYSTEMATIC_SD * rng.standard_normal(M)
                    - 0.5 * allometry.SYSTEMATIC_SD ** 2)
    p_con = _draw_p_conifer(rng, inv.p_conifer, M)

    # survival: background and ash
    alive = (1 - BACKGROUND_MORTALITY) ** yrs[None, :].repeat(M, 0)       # members x years
    ash_cfg = None
    if ash is not None:
        ash_cfg = {**ASH_DEFAULTS, **ash}
        share = ash_cfg["ash_share"]
        f_ash = rng.beta(share * 20, (1 - share) * 20, M) if 0 < share < 1 else np.full(M, share)
        m_max = np.clip(ash_cfg["m_max"] + 0.05 * rng.standard_normal(M), 0, 1)
        m_ash = m_max[:, None] * (1 - np.exp(-yrs[None, :] / ash_cfg["tau_years"]))
        alive = alive * (1 - ((1 - p_con) * f_ash)[:, None] * m_ash)

    living_c = np.zeros((M, Yn))
    to_soil = np.zeros((M, Yn))
    dead_in = np.zeros((M, Yn))
    height_med = np.zeros((M, Yn))
    pools = carbon.Pools(M)
    dw = np.zeros((M, Yn))
    fw = np.zeros((M, Yn))
    prev_tree_agb = None
    area_crown = np.pi * (cr * h_obs / 2) ** 2
    for k, year in enumerate(cal):
        age_now = age0[None] + (year - t_ref)[None]
        base = bank.height(theta, age0[None], cri[None])
        h = np.maximum(h_obs[None] + bank.height(theta, age_now, cri[None]) - base, 0.5)
        height_med[:, k] = np.median(h, 1)
        tree_agb = np.empty_like(h)
        for m in range(M):
            tree_agb[m] = allometry.agb_kg(h[m], cr * h[m], p_con[m])
        tree_agb *= resid * system[:, None] / 1000.0                          # t DM
        obj_agb = tree_agb * n_trees[None]
        living_c[:, k] = carbon.CARBON_FRACTION * obj_agb.sum(1) * alive[:, k] * (1 + allometry.ROOT_SHOOT)
        crown_area = (area_crown[None] * (h / h_obs[None]) ** 2 * n_trees[None]).sum(1)
        to_soil[:, k] = carbon.litter_to_soil_t_c(obj_agb.sum(1) * alive[:, k],
                                                  crown_area * alive[:, k], inv.p_conifer)
        if k > 0:
            dead_in[:, k] = (alive[:, k - 1] - alive[:, k]) * prev_tree_agb
            pools.step(dead_in[:, k], firewood_fraction)
        dw[:, k], fw[:, k] = pools.deadwood, pools.firewood
        prev_tree_agb = obj_agb.sum(1)

    replant_c = np.zeros((M, Yn))
    if replant_share > 0 and ash_cfg is not None:
        trees_dead = -np.diff(alive, axis=1, prepend=alive[:, :1]) * n_trees.sum()
        planted = replant_share * trees_dead
        young = _young_tree_agb_t(bank, np.median(theta, 1), yrs, 0.7, p_con)   # M x years
        surv = PLANTING_TYPES["hedgerow"]["survival"]
        for m in range(M):
            conv = np.convolve(planted[m], young[m])[:Yn]
            replant_c[m] = carbon.CARBON_FRACTION * (1 + allometry.ROOT_SHOOT) * surv * conv * system[m]
        living_c = living_c + replant_c

    total = living_c + dw + fw
    net_c = np.zeros((M, Yn))
    net_c[:, 1:] = -(np.diff(total, axis=1)) - to_soil[:, 1:]
    out = {
        "years": cal.tolist(), "n_objects": n_obj, "n_trees": int(n_trees.sum()),
        "n_members": M, "seed": seed,
        "living_c_t": _summ(living_c), "deadwood_c_t": _summ(dw), "firewood_c_t": _summ(fw),
        "replanted_living_c_t": _summ(replant_c) if replant_share > 0 else None,
        "to_soil_t_c_yr": _summ(to_soil),
        "net_flux_t_co2_yr": _summ(carbon.to_co2(net_c)),
        "trees_alive": _summ(alive * n_trees.sum()),
        "height_median_m": _summ(height_med),
        "cumulative_net_t_co2": _summ(np.cumsum(carbon.to_co2(net_c), 1)),
        "ash": ash_cfg, "replant_share": replant_share,
        "sign_convention": "positive flux = emission to the atmosphere",
    }
    return out


def _young_tree_agb_t(bank: HeightBank, theta, yrs, crown_ratio, p_con) -> np.ndarray:
    """AGB (t DM) of one tree planted at year 0 as a 1.3 m sapling, per member and year."""
    theta = np.atleast_1d(theta)
    cri = bank.cr_index(crown_ratio)
    # age offset so the curve passes through the sapling height at planting
    ages = bank.ages
    out = np.empty((theta.size, yrs.size))
    for m, th in enumerate(theta):
        curve = bank.height(np.full(ages.size, th), ages, np.full(ages.size, cri))
        a0 = float(np.interp(H_START, curve, ages)) if curve[-1] > H_START else 0.0
        h = bank.height(np.full(yrs.size, th), a0 + yrs, np.full(yrs.size, cri))
        out[m] = allometry.agb_kg(h, crown_ratio * h, p_con[m]) / 1000.0
    return out


def planting(bank: HeightBank, theta_median: float, theta_sd: float, n_trees: int,
             kind: str = "hedgerow", p_conifer: float = 0.0, start_year: int = 2025,
             years: int = 50, n_members: int = 50, seed: int = 0) -> dict:
    """Carbon of a new planting of ``n_trees`` young trees of a given kind."""
    if kind not in PLANTING_TYPES:
        raise ValueError(f"unknown planting type {kind!r}; known: {tuple(PLANTING_TYPES)}")
    cfg = PLANTING_TYPES[kind]
    rng = np.random.default_rng(seed)
    g = bank.grid
    theta = np.clip(theta_median + theta_sd * rng.standard_normal(n_members), g[0], g[-1])
    p_con = _draw_p_conifer(rng, p_conifer, n_members)
    system = np.exp(allometry.SYSTEMATIC_SD * rng.standard_normal(n_members)
                    - 0.5 * allometry.SYSTEMATIC_SD ** 2)
    surv0 = np.clip(cfg["survival"] + 0.05 * rng.standard_normal(n_members), 0.3, 1.0)
    yrs = np.arange(years + 1)
    est = np.minimum(yrs / 5.0, 1.0)                              # losses over the first 5 yr
    alive = n_trees * (1 - (1 - surv0[:, None]) * est[None]) * \
        (1 - BACKGROUND_MORTALITY) ** np.maximum(yrs - 5, 0)[None]
    agb = _young_tree_agb_t(bank, theta, yrs, cfg["crown_ratio"], p_con) * system[:, None]
    living = carbon.CARBON_FRACTION * (1 + allometry.ROOT_SHOOT) * agb * alive
    h = np.array([bank.height(np.full(yrs.size, th), yrs, np.full(yrs.size, bank.cr_index(cfg["crown_ratio"])))
                  for th in theta])
    crown = np.pi * (cfg["crown_ratio"] * h / 2) ** 2 * alive
    to_soil = carbon.litter_to_soil_t_c(agb * alive, crown, p_conifer)
    pools = carbon.Pools(n_members)
    dw, fw = np.zeros_like(living), np.zeros_like(living)
    for k in range(1, yrs.size):
        dead = np.maximum(alive[:, k - 1] - alive[:, k], 0) * agb[:, k - 1]
        pools.step(dead)
        dw[:, k], fw[:, k] = pools.deadwood, pools.firewood
    total = living + dw + fw
    net = np.zeros_like(living)
    net[:, 1:] = -np.diff(total, axis=1) - to_soil[:, 1:]
    return {"years": (start_year + yrs).tolist(), "kind": kind, "n_planted": int(n_trees),
            "n_members": n_members, "seed": seed, "establishment_survival": cfg["survival"],
            "trees_alive": _summ(alive), "living_c_t": _summ(living),
            "deadwood_c_t": _summ(dw), "firewood_c_t": _summ(fw),
            "to_soil_t_c_yr": _summ(to_soil),
            "net_flux_t_co2_yr": _summ(carbon.to_co2(net)),
            "cumulative_net_t_co2": _summ(np.cumsum(carbon.to_co2(net), 1)),
            "sign_convention": "positive flux = emission to the atmosphere"}
