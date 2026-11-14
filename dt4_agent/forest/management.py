"""Management regimes: what is cut, when, and where the wood goes.

A regime is a set of rules applied once a year, after growth, to every ensemble member.
Regimes are *responses* in the Living Earth EBCF sense: scenario outcomes, never
observations. Four regimes cover the main British practice:

``no_intervention``
    Nothing is cut. The stand grows and self-thins (3-PG) or follows its curve.
``thin_and_fell``
    Thinning every ``thin_interval`` years from the species' first-thinning age, removing
    ``thin_fraction`` of standing biomass, then clearfell at ``rotation_age`` and replanting
    the next year. The classic lowland regime (for example Thetford pine).
``clearfell_no_thin``
    No thinning, clearfell at ``rotation_age`` and replant: the usual upland regime where
    thinning raises wind risk (for example Kielder Sitka spruce).
``continuous_cover``
    Continuous cover forestry: from the first-thinning age, every ``ccf_interval`` years
    ``ccf_fraction`` of standing biomass is harvested selectively and the stand is never
    clearfelled. Each harvest *rejuvenates* the stand (regeneration in the gaps), see the
    growth modules.

Harvested biomass is split into brash left on site (``RESIDUE_FRACTION``, to deadwood) and
logs, which go into three harvested wood product (HWP) pools in shares that depend on the
operation (small thinnings make more pulp and panels, mature fellings more sawnwood).
The shares are a priori values typical of British conifer markets.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

RESIDUE_FRACTION = 0.15

# product shares of log biomass: sawnwood, wood panels, paper and pulp
PRODUCT_SHARES = {
    "thinning": (0.20, 0.40, 0.40),
    "fell": (0.50, 0.30, 0.20),
    "ccf": (0.45, 0.35, 0.20),
    "salvage": (0.30, 0.40, 0.30),
}


@dataclass(frozen=True)
class Regime:
    name: str
    description: str
    thin: bool = False
    clearfell: bool = False
    ccf: bool = False
    rotation_age: int | None = None   # None: species default
    thin_interval: int = 5
    thin_fraction: float = 0.25
    ccf_interval: int = 10
    ccf_fraction: float = 0.20
    first_intervention_age: int | None = None  # None: species first-thinning age

    def with_options(self, **kw) -> "Regime":
        return replace(self, **{k: v for k, v in kw.items() if v is not None})


REGIMES: dict[str, Regime] = {
    "no_intervention": Regime("no_intervention", "No harvesting; the stand grows and self-thins."),
    "thin_and_fell": Regime("thin_and_fell", "Thin every 5 years (25 % of standing biomass) "
                            "from first-thinning age, clearfell at rotation, replant.",
                            thin=True, clearfell=True),
    "clearfell_no_thin": Regime("clearfell_no_thin", "No thinning; clearfell at rotation and "
                                "replant (typical upland Sitka spruce).", clearfell=True),
    "continuous_cover": Regime("continuous_cover", "Selective harvest of 20 % of standing "
                               "biomass every 10 years from first-thinning age; never clearfelled.",
                               ccf=True),
}


def get(name: str) -> Regime:
    try:
        return REGIMES[name]
    except KeyError:
        raise ValueError(f"unknown regime {name!r}; known: {sorted(REGIMES)}") from None
