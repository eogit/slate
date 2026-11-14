"""Process-based growth: a crown light-use-efficiency (LUE) model for a single open-grown tree.

Why a crown model
-----------------
A tree outside woodland intercepts light over its own crown, not over a share of a closed
canopy, so stand models such as 3-PG (used in DT4) do not apply. This model grows one tree
from the light its crown absorbs, using the same monthly HadUK-Grid climate as DT4:

    APAR_m   = 0.5 * Rs_m * leaf_on_m * (1 - exp(-K_EXT * LAI))          (MJ m-2 crown)
    E        = sum_m APAR_m * fT_m * fFrost_m * fDrought_m                 (MJ m-2 crown yr-1)
    dAGB/dt  = ETA_WOOD * Y_NPP * EPS_MAX * theta * E * A_crown(H) - TURNOVER * AGB

``A_crown = pi (cr H / 2)^2`` is the crown projection area of a tree with crown ratio ``cr``
(crown diameter / height, held constant). Height is recovered from AGB by inverting the
Jucker et al. (2017) allometry for the same crown ratio and conifer share. Because gain grows
with H^2 and turnover with AGB ~ H^4, the tree approaches an asymptotic height that rises with
``sqrt(theta)``: big crowns on good sites grow tall, as they should.

``theta`` (0-1) scales the maximum light-use efficiency and is the one parameter that is
calibrated against lidar; it absorbs everything the climate modifiers do not represent
(soil, exposure, species, pruning).

Modifiers (3-PG conventions, Landsberg & Waring 1997)
-----------------------------------------------------
* temperature: beta function of mean monthly temperature (Tmin 0, Topt 18, Tmax 35 deg C for
  broadleaves; Topt 15 for conifers);
* frost: ``1 - frost_days / days_in_month``;
* drought: a 150 mm soil bucket filled by rain and emptied by Hargreaves potential
  evaporation, run to a steady annual cycle; ``fDrought = min(1, ASW / (0.5 ASW_max))``;
* leaf-on: broadleaves April to October (half months in April and October), conifers all
  year. The pilot's conifer share mixes the two.

Constants
---------
``EPS_MAX`` 6.0 g dry matter MJ-1 APAR (the 3-PG maximum canopy quantum efficiency, 0.06 mol C mol-1 photons), ``Y_NPP`` 0.47 (Waring et al. 1998), ``ETA_WOOD``
0.35 of NPP to above-ground woody biomass, ``TURNOVER`` 0.015 yr-1 (branch shedding),
``LAI`` 4 and ``K_EXT`` 0.5. Trees start at 1.3 m (an established sapling) at age 0.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from . import allometry

EPS_MAX = 6.0e-3      # kg dry matter per MJ APAR (3-PG maximum quantum efficiency)
Y_NPP = 0.47
ETA_WOOD = 0.35
TURNOVER = 0.015
LAI = 4.0
K_EXT = 0.5
ASW_MAX = 150.0
H_START = 1.3
H_LIMIT = 45.0        # no British open-grown tree exceeds this; caps the inverse allometry
THETA_GRID = np.linspace(0.04, 1.0, 25)
THETA_NAME = "light-use efficiency multiplier (0-1)"
DAYS = np.array([31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
LEAF_ON_BROADLEAF = np.array([0, 0, 0, 0.5, 1, 1, 1, 1, 1, 0.5, 0, 0])


def _f_temp(t, t_min=0.0, t_opt=18.0, t_max=35.0):
    t = np.asarray(t, float)
    ok = (t > t_min) & (t < t_max)
    e = (t_max - t_opt) / (t_opt - t_min)
    tt = np.clip(t, t_min + 1e-6, t_max - 1e-6)
    f = ((tt - t_min) / (t_opt - t_min)) * ((t_max - tt) / (t_max - t_opt)) ** e
    return np.where(ok, f, 0.0)


def _f_drought(climate) -> np.ndarray:
    """Monthly drought modifier from a steady-state soil water bucket."""
    tmax, tmin = np.asarray(climate.tmax_c), np.asarray(climate.tmin_c)
    tas = (tmax + tmin) / 2
    rs = np.asarray(climate.solar_mj_m2_d)
    # Hargreaves PET (mm/day) from radiation, with the 0.0135 coefficient on Rs in MJ/m2/day
    pet = 0.0135 * (tas + 17.8) * rs / 2.45 * DAYS
    rain = np.asarray(climate.rain_mm)
    asw = ASW_MAX
    f = np.ones(12)
    for _ in range(4):                       # spin up to a steady annual cycle
        for m in range(12):
            asw = min(ASW_MAX, max(0.0, asw + rain[m] - pet[m] * min(1.0, asw / (0.5 * ASW_MAX))))
            f[m] = min(1.0, asw / (0.5 * ASW_MAX))
    return f


def effective_light(climate, p_conifer: float = 0.0) -> float:
    """Annual climate-weighted APAR per m2 of crown, E (MJ m-2 yr-1)."""
    tas = (np.asarray(climate.tmax_c) + np.asarray(climate.tmin_c)) / 2
    rs = np.asarray(climate.solar_mj_m2_d) * DAYS
    f_frost = 1.0 - np.clip(np.asarray(climate.frost_days) / DAYS, 0, 1)
    f_dry = _f_drought(climate)
    absorb = 1.0 - math.exp(-K_EXT * LAI)
    broad = 0.5 * rs * LEAF_ON_BROADLEAF * absorb * _f_temp(tas) * f_frost * f_dry
    conif = 0.5 * rs * absorb * _f_temp(tas, t_opt=15.0) * f_frost * f_dry
    return float(((1 - p_conifer) * broad + p_conifer * conif).sum())


class _HeightLookup:
    """Fast inverse allometry: AGB -> height for one crown ratio and conifer share."""

    def __init__(self, crown_ratio: float, p_conifer: float):
        self.h = np.linspace(0.3, H_LIMIT, 800)
        self.log_agb = np.log(allometry.agb_kg(self.h, crown_ratio * self.h, p_conifer))

    def __call__(self, agb):
        return np.interp(np.log(np.maximum(agb, 1e-6)), self.log_agb, self.h)


@lru_cache(maxsize=256)
def _lookup(crown_ratio: float, p_conifer: float) -> _HeightLookup:
    return _HeightLookup(crown_ratio, p_conifer)


class CrownLUEModel:
    """Single-tree crown light-use model; ``theta`` scales the light-use efficiency."""

    name = "crown_lue"
    theta_grid = THETA_GRID
    theta_name = THETA_NAME

    def __init__(self, p_conifer: float = 0.0, climate=None):
        if climate is None:
            raise ValueError("the crown LUE model needs a monthly climate (trees.pilots)")
        self.p_conifer = float(p_conifer)
        self.climate = climate
        self.light = effective_light(climate, self.p_conifer)

    def _gain(self, theta, h, crown_ratio):
        area = math.pi * (crown_ratio * h / 2.0) ** 2
        return ETA_WOOD * Y_NPP * EPS_MAX * np.asarray(theta, float) * self.light * area

    def grow(self, theta, agb0, crown_ratio: float, years: int) -> np.ndarray:
        """AGB trajectory (years+1 values per theta) from a starting AGB, yearly steps."""
        cr = round(float(crown_ratio), 3)
        inv = _lookup(cr, round(self.p_conifer, 3))
        theta = np.atleast_1d(np.asarray(theta, float))
        agb = np.broadcast_to(np.asarray(agb0, float), theta.shape).astype(float)
        out = np.empty(theta.shape + (years + 1,))
        out[..., 0] = agb
        for t in range(years):
            h = inv(agb)
            agb = np.maximum(agb + self._gain(theta, h, cr) - TURNOVER * agb, 1e-6)
            out[..., t + 1] = agb
        return out

    def height_table(self, ages, crown_ratio: float = 0.7) -> np.ndarray:
        """Heights for every ``theta_grid`` value (rows) and age (columns) from a sapling."""
        ages = np.asarray(ages, float)
        cr = round(float(crown_ratio), 3)
        inv = _lookup(cr, round(self.p_conifer, 3))
        agb0 = allometry.agb_kg(H_START, cr * H_START, self.p_conifer)
        traj = self.grow(self.theta_grid, agb0, cr, int(math.ceil(ages.max())) + 1)
        h = inv(traj)
        years = np.arange(h.shape[1])
        return np.vstack([np.interp(ages, years, row) for row in h])

    def project_height(self, theta, h_now, years, crown_ratio) -> np.ndarray:
        """Height ``years`` ahead of trees of height ``h_now`` (vectorised over trees)."""
        theta = np.atleast_1d(np.asarray(theta, float))
        h_now = np.broadcast_to(np.asarray(h_now, float), theta.shape)
        cr = np.broadcast_to(np.asarray(crown_ratio, float), theta.shape)
        out = np.empty(theta.shape)
        for i in range(theta.size):
            c = round(float(cr.flat[i]), 2)
            inv = _lookup(c, round(self.p_conifer, 3))
            agb0 = allometry.agb_kg(h_now.flat[i], c * h_now.flat[i], self.p_conifer)
            out.flat[i] = inv(self.grow(theta.flat[i], agb0, c, int(years))[..., -1])[0]
        return out
