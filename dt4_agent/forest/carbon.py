"""Forest carbon pools and harvested wood products.

DT4 tracks, per hectare and per ensemble member, carbon in

* **living biomass**: above-ground (from the growth model) and below-ground roots, the latter
  from the Mokany et al. (2006) root-to-shoot relation (:func:`forest.species.root_shoot_ratio`), so both
  growth models are compared on the same root rule;
* **deadwood**: fed by tree mortality, unsalvaged disturbance kill and harvest brash, decaying
  with ``K_DEADWOOD`` (about a 20-year half-life);
* **litter**: fed by foliage and fine-litter fall, decaying with ``K_LITTER``;
* **harvested wood products**: sawnwood, panels and paper, with first-order decay and the
  IPCC (2019) default half-lives of 35, 25 and 2 years.

Soil carbon is left to DT7: DT4 reports the carbon that leaves litter and deadwood each year
(``to_soil_t_c_ha_yr``) as DT7's input. Decay of litter and deadwood is split between CO2
released to the air (``HUMIFICATION`` share goes to the soil instead).

Sign convention as in DT8: a positive flux is an emission to the atmosphere, so a growing
forest has a negative net flux. Units: t C/ha for stocks, t C/ha/yr and t CO2/ha/yr for fluxes.
"""

from __future__ import annotations

import math

import numpy as np

from .species import CARBON_FRACTION, CO2_PER_C, root_shoot_ratio

K_DEADWOOD = math.log(2) / 20.0
K_LITTER = math.log(2) / 3.0
HUMIFICATION = 0.25                     # share of decayed litter/deadwood C passed to soil
HWP_HALF_LIFE = (35.0, 25.0, 2.0)       # sawnwood, panels, paper (IPCC 2019 defaults)
K_HWP = tuple(math.log(2) / h for h in HWP_HALF_LIFE)
HWP_NAMES = ("sawnwood", "panels", "paper")


class Pools:
    """Dead and product carbon pools, one value per ensemble member (t C/ha)."""

    def __init__(self, n: int, deadwood=0.0, litter=0.0):
        self.deadwood = np.full(n, float(deadwood)) if np.ndim(deadwood) == 0 else np.asarray(deadwood, float).copy()
        self.litter = np.full(n, float(litter)) if np.ndim(litter) == 0 else np.asarray(litter, float).copy()
        self.hwp = np.zeros((3, n))

    def total(self) -> np.ndarray:
        return self.deadwood + self.litter + self.hwp.sum(axis=0)

    def step(self, deadwood_in_dm, litter_in_dm, products_dm_by_share) -> dict:
        """Add a year's inputs (t DM/ha) and decay all pools. Returns C fluxes (t C/ha/yr).

        ``products_dm_by_share`` is a (3, n) array of log biomass into each product pool.
        """
        dw_in = CARBON_FRACTION * np.asarray(deadwood_in_dm, float)
        lit_in = CARBON_FRACTION * np.asarray(litter_in_dm, float)
        prod_in = CARBON_FRACTION * np.asarray(products_dm_by_share, float)
        dw_decay = self.deadwood * (1 - math.exp(-K_DEADWOOD))
        lit_decay = self.litter * (1 - math.exp(-K_LITTER))
        self.deadwood = self.deadwood + dw_in - dw_decay
        self.litter = self.litter + lit_in - lit_decay
        hwp_out = np.zeros_like(self.hwp)
        for i, k in enumerate(K_HWP):
            hwp_out[i] = self.hwp[i] * (1 - math.exp(-k))
            self.hwp[i] = self.hwp[i] + prod_in[i] - hwp_out[i]
        decayed = dw_decay + lit_decay
        return {"to_soil": HUMIFICATION * decayed,
                "dead_to_air": (1 - HUMIFICATION) * decayed,
                "hwp_to_air": hwp_out.sum(axis=0)}


def living_carbon(agb_dm, conifer: bool) -> tuple[np.ndarray, np.ndarray]:
    """Above- and below-ground living carbon (t C/ha) from AGB (t DM/ha)."""
    agb_dm = np.asarray(agb_dm, float)
    bgb_dm = agb_dm * root_shoot_ratio(agb_dm, conifer)
    return CARBON_FRACTION * agb_dm, CARBON_FRACTION * bgb_dm


def to_co2(c) -> np.ndarray:
    return np.asarray(c, float) * CO2_PER_C
