"""From crown structure to biomass and carbon.

Above-ground biomass (AGB) of a tree comes from its height H and crown diameter CD with the
remote-sensing allometry of Jucker et al. (2017, Global Change Biology 23, 177-190, Eq. 7),
fitted to 108,753 trees worldwide:

    AGB [kg] = (0.016 + alpha_G) * (H * CD) ** (2.013 + beta_G) * exp(0.204 / 2)

with alpha_G = beta_G = 0 for angiosperms and alpha_G = 0.093, beta_G = -0.223 for
gymnosperms. The last factor corrects the log-regression bias. The paper's validation error
is sigma_v = 0.69 on the log scale for a single tree, which DT6 carries as the per-tree
uncertainty; it averages out over many trees, so ``SYSTEMATIC_SD`` (0.2, log scale) is kept
as the part that does not (open-grown trees carry more branch wood than the forest trees
most of the data come from).

Below-ground biomass uses a fixed root:shoot ratio ``ROOT_SHOOT`` (0.26, the temperate mean
of Cairns et al. 1997), because the stand-level relations DT4 uses do not apply to single
trees. Carbon is ``CARBON_FRACTION`` (0.5, as DT4) of dry matter.

Leaf type is not in any open TOW dataset, so a crown's biomass is the expectation over its
conifer probability ``p_conifer``.
"""

from __future__ import annotations

import numpy as np

CITATION = ("Jucker et al. 2017, Allometric equations for integrating remote sensing imagery "
            "into forest monitoring programmes, Global Change Biology 23, 177-190")
CARBON_FRACTION = 0.5
CO2_PER_C = 44.0 / 12.0
ROOT_SHOOT = 0.26
SIGMA_TREE = 0.69          # Jucker et al. validation error, log scale, one tree
SYSTEMATIC_SD = 0.2        # allometric error that does not average out over many trees
_CORR = float(np.exp(0.204 / 2))
ANGIO = (0.016 * _CORR, 2.013)
GYMNO = ((0.016 + 0.093) * _CORR, 2.013 - 0.223)


def agb_kg(height_m, crown_diam_m, p_conifer=0.0):
    """Above-ground biomass (kg dry matter) of one tree; works on arrays."""
    hc = np.maximum(np.asarray(height_m, dtype=float), 0.0) * np.maximum(np.asarray(crown_diam_m, dtype=float), 0.0)
    a = ANGIO[0] * hc ** ANGIO[1]
    g = GYMNO[0] * hc ** GYMNO[1]
    p = np.asarray(p_conifer, dtype=float)
    return (1.0 - p) * a + p * g


def height_for_agb(agb, crown_ratio, p_conifer=0.0):
    """Height (m) of a tree with AGB ``agb`` (kg) whose crown diameter is ``crown_ratio * H``.

    Inverts :func:`agb_kg` numerically (bisection, vectorised), since the conifer mixture has
    no closed form.
    """
    agb = np.asarray(agb, dtype=float)
    c = np.asarray(crown_ratio, dtype=float)
    lo = np.zeros(np.broadcast(agb, c, np.asarray(p_conifer)).shape)
    hi = np.full_like(lo, 80.0)
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        f = agb_kg(mid, c * mid, p_conifer) - agb
        lo = np.where(f < 0, mid, lo)
        hi = np.where(f < 0, hi, mid)
    return 0.5 * (lo + hi)


def bgb_kg(agb):
    return ROOT_SHOOT * np.asarray(agb, dtype=float)


def living_carbon_t(agb_kg_):
    """(above-ground, below-ground) carbon in tonnes for AGB in kg."""
    a = np.asarray(agb_kg_, dtype=float) * CARBON_FRACTION / 1000.0
    return a, a * ROOT_SHOOT
