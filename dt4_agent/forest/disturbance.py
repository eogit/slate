"""Disturbances: wind, fire, pests and pathogens, drought.

A disturbance kills a share (``severity``, 0-1) of the standing above-ground biomass. Part of
the killed wood is salvaged and goes into wood products, part burns (fire only), and the
rest stays on site as deadwood. A severity of ``STAND_REPLACING`` (0.8) or more is treated as
stand-replacing: what survives is cleared with the salvage and the site is replanted the
next year.

Disturbances enter a simulation in two ways:

* **prescribed** events (year, kind, severity), for hindcasts ("what did storm Arwen do?")
  or stress tests;
* **stochastic** hazards: each year every member suffers each kind of event with the
  species' annual probability (:mod:`forest.species`) times ``hazard_multiplier``; severity
  is drawn from a Beta distribution with mean ``MEAN_SEVERITY[kind]``. The random generator
  is seeded, so a run is repeatable.

All default rates and shares are a priori assumptions, flagged as such in results.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

KINDS = ("wind", "fire", "biotic", "drought")
STAND_REPLACING = 0.8
SALVAGE = {"wind": 0.7, "fire": 0.3, "biotic": 0.5, "drought": 0.0}
COMBUSTED = {"wind": 0.0, "fire": 0.25, "biotic": 0.0, "drought": 0.0}  # of killed biomass
MEAN_SEVERITY = {"wind": 0.6, "fire": 0.5, "biotic": 0.3, "drought": 0.15}
BETA_CONCENTRATION = 6.0


@dataclass(frozen=True)
class Event:
    year: int
    kind: str
    severity: float
    salvage_fraction: float | None = None   # None: default for the kind

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"unknown disturbance {self.kind!r}; known: {KINDS}")
        if not 0.0 <= self.severity <= 1.0:
            raise ValueError("severity must be between 0 and 1")

    @property
    def salvage(self) -> float:
        return SALVAGE[self.kind] if self.salvage_fraction is None else self.salvage_fraction


def hazard_rates(species, multiplier: float = 1.0) -> dict[str, float]:
    return {"wind": species.hazard_wind * multiplier, "fire": species.hazard_fire * multiplier,
            "biotic": species.hazard_biotic * multiplier, "drought": 0.002 * multiplier}


def draw(rng: np.random.Generator, rates: dict[str, float], n: int) -> dict[str, np.ndarray]:
    """Severity per member for each kind this year (0 = no event)."""
    out = {}
    for kind, rate in rates.items():
        hit = rng.random(n) < rate
        m = MEAN_SEVERITY[kind]
        sev = rng.beta(m * BETA_CONCENTRATION, (1 - m) * BETA_CONCENTRATION, n)
        out[kind] = np.where(hit, sev, 0.0)
    return out
