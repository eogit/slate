"""Carbon pools of trees outside woodland.

DT6 tracks, per ensemble member and in tonnes of carbon for the selected trees (not per
hectare, because these are scattered objects):

* **living biomass**: above-ground from the crown allometry (``allometry.agb_kg``) and
  below-ground with a root:shoot ratio of 0.26 (Cairns et al. 1997);
* **deadwood**: trees that die and are left in place (hedge bottoms, field corners), decaying
  with a 20-year half-life as in DT4;
* **firewood**: dead or felled trees taken for fuel, the usual fate of a hedgerow or field
  tree on a farm; burnt within a year or two (half-life ``FIREWOOD_HALF_LIFE`` 1 year);
* **litter to soil**: leaves, twigs and roots shed each year. DT6 does not keep a litter pool:
  the carbon is handed to the soil twin (DT7) as ``to_soil_t_c_yr``. Leaf fall is
  ``LEAF_MASS_KG_M2`` of crown area per year for broadleaves (a third of that for conifers),
  plus branch shedding at the crown model's turnover rate.

Sign convention as in DT4 and DT8: a positive flux is an emission to the atmosphere, so
growing trees have a negative net flux. Net flux = -(change in living + deadwood + firewood
carbon) - carbon passed to the soil.
"""

from __future__ import annotations

import math

import numpy as np

from .allometry import CARBON_FRACTION, CO2_PER_C, ROOT_SHOOT

K_DEADWOOD = math.log(2) / 20.0
FIREWOOD_HALF_LIFE = 1.0
K_FIREWOOD = math.log(2) / FIREWOOD_HALF_LIFE
FIREWOOD_FRACTION = 0.7          # share of dead or felled TOW biomass taken for fuel
LEAF_MASS_KG_M2 = 0.3            # annual leaf fall per m2 crown, broadleaves (kg DM)
BRANCH_TURNOVER = 0.015          # per year, as in crown_lue.TURNOVER
FINE_ROOT_SHARE = 0.5            # fine-root litter as a share of leaf litter


class Pools:
    """Deadwood and firewood carbon, one value per ensemble member (t C)."""

    def __init__(self, n: int):
        self.deadwood = np.zeros(n)
        self.firewood = np.zeros(n)

    def total(self) -> np.ndarray:
        return self.deadwood + self.firewood

    def step(self, dead_agb_t_dm, firewood_fraction: float = FIREWOOD_FRACTION) -> dict:
        """Add a year's dead biomass (t DM, above and below ground) and decay both pools."""
        c_in = CARBON_FRACTION * np.asarray(dead_agb_t_dm, float) * (1 + ROOT_SHOOT)
        # roots always stay in the ground as deadwood; only the above-ground part is burnt
        above = c_in / (1 + ROOT_SHOOT)
        fw_in = firewood_fraction * above
        dw_in = c_in - fw_in
        dw_out = self.deadwood * (1 - math.exp(-K_DEADWOOD))
        fw_out = self.firewood * (1 - math.exp(-K_FIREWOOD))
        self.deadwood = self.deadwood + dw_in - dw_out
        self.firewood = self.firewood + fw_in - fw_out
        return {"deadwood_to_air": dw_out, "firewood_to_air": fw_out}


def living_carbon_t(agb_t_dm) -> tuple[np.ndarray, np.ndarray]:
    """Above- and below-ground living carbon (t C) from AGB (t DM)."""
    agb = np.asarray(agb_t_dm, float)
    return CARBON_FRACTION * agb, CARBON_FRACTION * agb * ROOT_SHOOT


def litter_to_soil_t_c(agb_t_dm, crown_area_m2, p_conifer: float) -> np.ndarray:
    """Carbon shed to the soil in a year (t C): leaves, fine roots and branches."""
    leaf = LEAF_MASS_KG_M2 * ((1 - p_conifer) + p_conifer / 3.0) * np.asarray(crown_area_m2) / 1e3
    branch = BRANCH_TURNOVER * np.asarray(agb_t_dm, float)
    return CARBON_FRACTION * (leaf * (1 + FINE_ROOT_SHARE) + branch)


def to_co2(c) -> np.ndarray:
    return np.asarray(c, float) * CO2_PER_C
