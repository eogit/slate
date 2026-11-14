"""Tree species known to DT4 and their a priori parameters.

Every species carries three parameter groups:

* **Yield-curve shape** (``culmination_age``, ``cr_shape``) and the range of yield classes.
  The yield curve itself is in :mod:`forest.yield_curves`.
* **Wood conversion**: basic density (oven-dry tonnes per m3 of fresh stem volume) and the
  biomass expansion factor (BEF) from merchantable stem volume to above-ground woody biomass
  (stem, bark and branches, as in the ESA CCI AGB definition), and the IPCC carbon fraction.
* **3-PG parameters** (:mod:`forest.threepg`), named as in Sands & Landsberg (2002) and the
  3-PGpjs spreadsheet so they can be checked against the literature.

Sources and status. All values are *a priori*: typical published figures for British
conditions, rounded. The productivity parameter of each growth model (yield class or the
3-PG fertility rating) is calibrated to Biomass CCI v7 per landscape, which absorbs much of
the error in the rest. Wood densities and BEFs follow the ranges in the Forest Research
carbon lookup tables (Woodland Carbon Code) and IPCC (2006) Table 4.14; 3-PG values start
from the 3-PGpjs defaults and published spruce and pine parameterisations (e.g. Xenakis et
al. 2008 for Scots pine; Minunno et al. 2010) and were adjusted so unthinned stands reach
plausible British standing biomass.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CARBON_FRACTION = 0.5     # t C per t dry matter (IPCC 2006 default 0.47 is an option)
CO2_PER_C = 44.0 / 12.0


@dataclass(frozen=True)
class Species:
    code: str
    name: str
    latin: str
    conifer: bool
    yc_min: int
    yc_max: int
    yc_default: int
    culmination_age: float      # age (years) at which mean annual increment peaks
    cr_shape: float             # Chapman-Richards shape exponent p
    wood_density: float         # t dry matter per m3 stem volume
    bef: float                  # above-ground woody biomass / stem biomass
    rotation_age: int           # typical economic clearfell age in Britain
    first_thin_age: int
    hazard_wind: float          # a priori annual probability of stand-damaging wind
    hazard_fire: float
    hazard_biotic: float
    threepg: dict = field(default_factory=dict)


# Shared 3-PG defaults (3-PGpjs, Sands & Landsberg 2002); each species overrides some.
_3PG_DEFAULT = dict(
    pFS2=1.0, pFS20=0.15,          # foliage:stem partitioning at DBH 2 cm and 20 cm
    aS=0.09, nS=2.45,              # stem mass (kg/tree) = aS * DBH(cm) ** nS
    pRx=0.8, pRn=0.25,             # max and min fraction of NPP to roots
    Tmin=-2.0, Topt=15.0, Tmax=30.0,
    kF=1.0,                        # days of production lost per frost day
    fN0=0.4, fNn=1.0, m0=0.0,      # nutrition modifier at FR = 0, its shape; root partitioning
    MaxAge=150.0, nAge=4.0, rAge=0.95,
    gammaF1=0.02, gammaF0=0.001, tgammaF=60.0,  # monthly litterfall: mature, young, months
    gammaR=0.015,                  # monthly root turnover
    wSx1000=350.0, thinPower=1.5,  # self-thinning: max stem mass (kg/tree) at 1000 trees/ha
    mF=0.0, mR=0.2, mS=0.2,        # fractions of mean single-tree pools lost per dying tree
    SLA0=5.0, SLA1=3.5, tSLA=6.0,  # specific leaf area (m2/kg) young, mature, age at mean
    k=0.5,                         # light extinction coefficient
    fullCanAge=12.0,               # age at canopy cover
    MaxIntcptn=0.2, LAImaxIntcptn=5.0,
    alphaCx=0.055,                 # canopy quantum efficiency (mol C / mol PAR)
    Y=0.47,                        # NPP / GPP
    MaxCond=0.02, LAIgcx=3.33, CoeffCond=0.05, BLcond=0.2,
    deciduous=False,
    stems_planted=2500.0,          # stems/ha at planting
)


def _p(**over) -> dict:
    d = dict(_3PG_DEFAULT)
    d.update(over)
    return d


SPECIES: dict[str, Species] = {
    "SS": Species(
        code="SS", name="Sitka spruce", latin="Picea sitchensis", conifer=True,
        yc_min=6, yc_max=24, yc_default=14, culmination_age=50, cr_shape=3.0,
        wood_density=0.33, bef=1.30, rotation_age=45, first_thin_age=22,
        hazard_wind=0.006, hazard_fire=0.0002, hazard_biotic=0.001,
        threepg=_p(Tmin=-2.0, Topt=14.0, Tmax=28.0, alphaCx=0.042, wSx1000=400.0,
                   aS=0.08, nS=2.45, SLA0=5.0, SLA1=3.5, fullCanAge=12.0, MaxIntcptn=0.25),
    ),
    "CP": Species(
        code="CP", name="Corsican pine", latin="Pinus nigra subsp. laricio", conifer=True,
        yc_min=6, yc_max=20, yc_default=12, culmination_age=55, cr_shape=3.0,
        wood_density=0.40, bef=1.25, rotation_age=60, first_thin_age=22,
        hazard_wind=0.002, hazard_fire=0.0008, hazard_biotic=0.003,
        threepg=_p(Tmin=0.0, Topt=17.0, Tmax=32.0, alphaCx=0.052, wSx1000=300.0,
                   aS=0.10, nS=2.40, pFS2=0.8, pFS20=0.12, SLA0=4.0, SLA1=3.0,
                   gammaF1=0.012, fullCanAge=15.0, MaxAge=180.0, MaxIntcptn=0.15),
    ),
    "SP": Species(
        code="SP", name="Scots pine", latin="Pinus sylvestris", conifer=True,
        yc_min=4, yc_max=14, yc_default=8, culmination_age=65, cr_shape=3.0,
        wood_density=0.42, bef=1.25, rotation_age=70, first_thin_age=25,
        hazard_wind=0.002, hazard_fire=0.0008, hazard_biotic=0.001,
        threepg=_p(Tmin=-2.0, Topt=15.0, Tmax=30.0, alphaCx=0.036, wSx1000=250.0,
                   aS=0.10, nS=2.40, pFS2=0.8, pFS20=0.12, SLA0=4.5, SLA1=3.0,
                   gammaF1=0.014, fullCanAge=15.0, MaxAge=200.0, MaxIntcptn=0.15),
    ),
    "OK": Species(
        code="OK", name="Oak", latin="Quercus robur and Q. petraea", conifer=False,
        yc_min=2, yc_max=8, yc_default=4, culmination_age=80, cr_shape=3.0,
        wood_density=0.56, bef=1.40, rotation_age=150, first_thin_age=30,
        hazard_wind=0.001, hazard_fire=0.0001, hazard_biotic=0.002,
        threepg=_p(Tmin=2.0, Topt=18.0, Tmax=32.0, alphaCx=0.065, wSx1000=600.0,
                   aS=0.12, nS=2.40, pFS2=0.6, pFS20=0.10, SLA0=14.0, SLA1=14.0,
                   fullCanAge=20.0, MaxAge=400.0, MaxIntcptn=0.15, deciduous=True,
                   stems_planted=2250.0),
    ),
}


def get(code: str) -> Species:
    try:
        return SPECIES[code]
    except KeyError:
        raise ValueError(f"unknown species {code!r}; known: {sorted(SPECIES)}") from None


def root_shoot_ratio(agb_mg_ha, conifer: bool = True):
    """Below-ground / above-ground biomass ratio from Mokany et al. (2006).

    BGB = 0.489 * AGB ** 0.890 (Mg/ha), fitted across forest types (Global Change Biology 12,
    84-96), so the ratio is 0.489 * AGB ** -0.110: about 0.38 at 10, 0.32 at 50, 0.29 at 100
    and 0.27 at 200 Mg/ha. It is continuous, unlike the IPCC (2006) Table 4.4 classes, whose
    steps would show up as spurious root-carbon jumps in annual fluxes. ``conifer`` is kept
    for a later species-specific rule. Works on scalars and numpy arrays.
    """
    import numpy as np

    a = np.maximum(np.asarray(agb_mg_ha, dtype=float), 1.0)
    r = 0.489 * a ** -0.110
    return float(r) if r.ndim == 0 else r
