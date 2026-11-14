"""Empirical growth: Chapman-Richards yield curves indexed by yield class.

British forestry describes stand productivity by **yield class** (YC): the maximum mean
annual increment (MAI) of stem volume, in m3 ha-1 yr-1, that a stand reaches over its life
(Edwards & Christie 1981, Forestry Commission Booklet 48). DT4 represents the standing stem
volume of an *unthinned* even-aged stand by a Chapman-Richards curve

    V(t) = A * (1 - exp(-k t)) ** p

and ties its parameters to yield class:

* ``p`` (shape) and the age of MAI culmination ``t*`` are species constants
  (:mod:`forest.species`). Because MAI = V(t)/t peaks where p x e^-x = 1 - e^-x with x = k t,
  the rate is ``k = x*(p) / t*``.
* The asymptote is set so that the curve's peak MAI equals the yield class:
  ``A = YC * t* / (1 - exp(-x*)) ** p``.

Above-ground woody biomass (the quantity ESA CCI maps) is ``AGB = V * wood_density * BEF``.

These curves are a compact stand-in for the Forest Research yield models: they reproduce the
defining property of yield class (peak MAI = YC at a species-typical age) but are not copies
of the published tables, which are not openly licensed as code. Yield class is calibrated to
Biomass CCI v7 per landscape (:mod:`forest.calibration`).

Management. Thinning and partial harvest lower the standing volume below the unthinned
curve. A thinned stand then keeps growing with the increment of the unthinned curve at its
age, scaled by its relative stocking to the power ``STOCKING_EXPONENT`` (0.5): a stand thinned
to 70 % of full stocking keeps about 84 % of the increment, in line with the British
experience that moderate thinning changes cumulative production little. Continuous cover
harvests also *rejuvenate* the stand: after a harvest its effective age moves back to the age
at which the unthinned curve holds the remaining volume, standing for regeneration in gaps.
"""

from __future__ import annotations

import math

import numpy as np

from . import species as sp

STOCKING_EXPONENT = 0.5
LITTER_FRACTION = 0.025     # foliage and fine litter, t DM per t AGB per year (a priori)
MORTALITY_FRACTION = 0.004  # background tree mortality, fraction of AGB per year (a priori)


def x_star(p: float) -> float:
    """Solve p x e^-x = 1 - e^-x for x > 0 (where MAI of a Chapman-Richards curve peaks)."""
    f = lambda x: p * x * math.exp(-x) - (1.0 - math.exp(-x))  # noqa: E731
    lo, hi = 1e-6, 50.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def curve_parameters(species: str, yc) -> tuple[np.ndarray, float, float]:
    """Return (A, k, p) of the Chapman-Richards curve for a species and yield class(es)."""
    s = sp.get(species)
    p = s.cr_shape
    xs = x_star(p)
    k = xs / s.culmination_age
    A = np.asarray(yc, dtype=float) * s.culmination_age / (1.0 - math.exp(-xs)) ** p
    return A, k, p


def volume(age, yc, species: str) -> np.ndarray:
    """Standing stem volume (m3/ha) of an unthinned stand of a given age and yield class."""
    A, k, p = curve_parameters(species, yc)
    t = np.maximum(np.asarray(age, dtype=float), 0.0)
    return A * (1.0 - np.exp(-k * t)) ** p


def age_for_volume(vol, yc, species: str) -> np.ndarray:
    """Inverse of :func:`volume`: the age at which the unthinned curve holds ``vol``."""
    A, k, p = curve_parameters(species, yc)
    frac = np.clip(np.asarray(vol, dtype=float) / A, 0.0, 0.999999)
    return -np.log(1.0 - frac ** (1.0 / p)) / k


def to_agb(vol, species: str) -> np.ndarray:
    s = sp.get(species)
    return np.asarray(vol, dtype=float) * s.wood_density * s.bef


def to_volume(agb, species: str) -> np.ndarray:
    s = sp.get(species)
    return np.asarray(agb, dtype=float) / (s.wood_density * s.bef)


def agb(age, yc, species: str) -> np.ndarray:
    """Above-ground woody biomass (Mg dry matter/ha) of an unthinned stand."""
    return to_agb(volume(age, yc, species), species)


def mai(age, yc, species: str) -> np.ndarray:
    a = np.maximum(np.asarray(age, dtype=float), 1e-9)
    return volume(a, yc, species) / a


def agb_table(species: str, thetas, max_age: int = 200) -> np.ndarray:
    """AGB of unthinned stands, shape (len(thetas), max_age + 1), ages 0..max_age."""
    ages = np.arange(max_age + 1, dtype=float)
    return agb(ages[None, :], np.asarray(thetas, dtype=float)[:, None], species)


class YieldCurveModel:
    """Annual-step stand model on yield curves, vectorised over ensemble members.

    State is a dict of numpy arrays, one entry per member: ``age`` (effective age, years),
    ``vol`` (standing stem volume, m3/ha) and ``yc`` (yield class).
    """

    name = "yield_curve"
    productivity_name = "yield_class"
    productivity_unit = "m3 ha-1 yr-1 (peak mean annual increment)"

    def __init__(self, species: str, landscape=None):
        self.species = species
        self.sp = sp.get(species)
        self.landscape = landscape  # unused: yield curves carry no climate

    # Productivity grid for calibration and the range simulations are clipped to. It runs
    # from YC 2 to four classes above the species' published maximum, wider than the usual
    # range, so CCI calibration is not clipped at the grid edge (SAR saturation and thinning
    # push CCI-calibrated yield classes below the Forest Research ranges).
    def theta_grid(self) -> np.ndarray:
        return np.arange(2.0, self.sp.yc_max + 5, 1.0)

    def theta_default(self) -> float:
        return float(self.sp.yc_default)

    def init(self, age, theta, agb0=None) -> dict:
        age = np.atleast_1d(np.asarray(age, dtype=float))
        theta = np.atleast_1d(np.asarray(theta, dtype=float))
        n = max(age.size, theta.size, 1 if agb0 is None else np.atleast_1d(agb0).size)
        age = np.broadcast_to(age, (n,)).copy()
        theta = np.broadcast_to(theta, (n,)).copy()
        vol = volume(age, theta, self.species)
        if agb0 is not None:
            vol = np.broadcast_to(to_volume(agb0, self.species), (n,)).copy()
        return {"age": age, "vol": vol, "yc": theta}

    def agb(self, state) -> np.ndarray:
        return to_agb(state["vol"], self.species)

    def step(self, state, year_index: int = 0) -> dict:
        """Grow every member by one year. Returns flux diagnostics in t DM/ha/yr."""
        age, vol, yc = state["age"], state["vol"], state["yc"]
        ref0 = volume(age, yc, self.species)
        ref1 = volume(age + 1.0, yc, self.species)
        stocking = np.where(ref0 > 1e-9, np.clip(vol / np.maximum(ref0, 1e-9), 0.0, 1.0), 1.0)
        grown = vol + (ref1 - ref0) * stocking ** STOCKING_EXPONENT
        # The curve is net of tree mortality, so mortality is reported as a flux to deadwood
        # (MORTALITY_FRACTION of AGB) without being subtracted from the standing volume again.
        mort = MORTALITY_FRACTION * to_agb(vol, self.species)
        state["vol"] = np.maximum(grown, 0.0)
        state["age"] = age + 1.0
        return {"litterfall": LITTER_FRACTION * to_agb(state["vol"], self.species),
                "mortality": mort}

    def remove(self, state, fraction, rejuvenate: bool = False) -> np.ndarray:
        """Take ``fraction`` (0-1, per member) of standing biomass out. Returns removed AGB."""
        f = np.clip(np.broadcast_to(np.asarray(fraction, dtype=float), state["vol"].shape), 0, 1)
        removed = to_agb(state["vol"] * f, self.species)
        state["vol"] = state["vol"] * (1.0 - f)
        if rejuvenate:
            new_age = age_for_volume(state["vol"], state["yc"], self.species)
            state["age"] = np.where(f > 0, np.minimum(state["age"], new_age), state["age"])
        return removed

    def replant(self, state, mask) -> None:
        mask = np.asarray(mask, dtype=bool)
        state["age"] = np.where(mask, 0.0, state["age"])
        state["vol"] = np.where(mask, 0.0, state["vol"])

    def agb_table(self, thetas, max_age: int = 200) -> np.ndarray:
        return agb_table(self.species, thetas, max_age)
