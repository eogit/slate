"""Empirical growth: a size-age (height) curve for open-grown trees, indexed by site index.

The model
---------
Height grows along a Chapman-Richards curve

    H(t) = Hmax * (1 - exp(-k t)) ** p,          Hmax = HMAX_PER_SI * SI

with the shape fixed (``p = 1.5``) and ``k`` chosen so that ``H(50) = SI``. The single
parameter ``theta`` is therefore the **site index**: the height (m) a tree reaches at 50
years. This is the open-grown counterpart of the yield-class curves in DT4: a tree outside a
wood has no stand to compete with, so its crown keeps widening and its height is the only
quantity we can follow reliably with repeat lidar.

Biomass follows from height through the crown-based allometry of Jucker et al. (2017) with
the tree's own crown ratio (crown diameter / height, measured once from the TOW polygon and
held constant), so the curve does not need to know about species. Conifer share enters only
through the allometry.

Defaults: ``HMAX_PER_SI = 1.35`` and ``p = 1.5`` give asymptotes of 20-40 m for site indices
of 15-30 m, which matches the range of mature hedgerow oak, ash and field-boundary trees in
lowland England (Forestry Commission booklet 48 for broadleaves; Brewer 2004). They are
priors, not calibrated constants: calibration only estimates SI (and the tree's age).
"""

from __future__ import annotations

import math

import numpy as np

from . import allometry

P_SHAPE = 1.5
HMAX_PER_SI = 1.35
REFERENCE_AGE = 50.0
# k from H(50) = SI:  (1 - exp(-50 k)) ** p = 1 / HMAX_PER_SI
K_RATE = -math.log(1.0 - (1.0 / HMAX_PER_SI) ** (1.0 / P_SHAPE)) / REFERENCE_AGE
THETA_GRID = np.linspace(4.0, 30.0, 27)      # site index (m at 50 years)
THETA_NAME = "site index (height at 50 years, m)"


class SizeAgeModel:
    """Height-age curve indexed by site index; AGB through the crown allometry."""

    name = "size_age"
    theta_grid = THETA_GRID
    theta_name = THETA_NAME

    def __init__(self, p_conifer: float = 0.0, climate=None):
        # climate is accepted for a common interface; the empirical curve does not use it
        self.p_conifer = float(p_conifer)

    @staticmethod
    def height(theta, age) -> np.ndarray:
        """Height (m) at ``age`` (years) for site index ``theta`` (broadcasts)."""
        theta = np.asarray(theta, dtype=float)
        age = np.maximum(np.asarray(age, dtype=float), 0.0)
        return HMAX_PER_SI * theta * (1.0 - np.exp(-K_RATE * age)) ** P_SHAPE

    def height_table(self, ages, crown_ratio: float = 0.7) -> np.ndarray:
        """Heights for every ``theta_grid`` value (rows) and age (columns)."""
        return self.height(self.theta_grid[:, None], np.asarray(ages, float)[None, :])

    def agb_kg(self, theta, age, crown_ratio) -> np.ndarray:
        h = self.height(theta, age)
        return allometry.agb_kg(h, crown_ratio * h, self.p_conifer)

    def project_height(self, theta, h_now, years) -> np.ndarray:
        """Height ``years`` ahead of a tree of height ``h_now`` (equivalent-age shift)."""
        theta = np.asarray(theta, float)
        frac = np.clip(np.asarray(h_now, float) / (HMAX_PER_SI * theta), 0.0, 0.999)
        age = -np.log(1.0 - frac ** (1.0 / P_SHAPE)) / K_RATE
        return self.height(theta, age + years)
