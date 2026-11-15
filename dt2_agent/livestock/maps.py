"""DT2's spatial state: where England's cattle, sheep and goats are, and where the grass is.

Three data layers, all on the 1 km British National Grid of ``grid.py`` and shipped in
``livestock/data`` (regenerate with the scripts in ``dt2_agent/scripts``):

* ``malek_lsu_1km.npz``: livestock units per 1 km cell from Malek et al. (2024), Zenodo
  10.5281/zenodo.13734518: cattle grazing managed grassland, cattle kept indoors ("other",
  clipped at 5 LSU/ha), cattle and sheep/goats on semi-natural land, sheep/goats elsewhere.
* ``living_england_1km.npz``: hectares of each Living England (Natural England, Phase 4)
  habitat class per cell. This is DT2's grassland map.
* ``naei_ch4_agriculture_2020.npz``: the NAEI 1 km agricultural methane map, used only to
  calibrate the allocation and to validate it.

How livestock are placed (``allocate``)
---------------------------------------
Head counts come from the June Survey (``herd.py``); the maps only decide where the heads go.
A species' weight in each cell starts from the Malek layers. The weight is then redistributed
inside blocks of ``block_km`` x ``block_km`` cells in proportion to the Living England grazing
area of each cell, so the block total of Malek is kept but the animals sit on the grass that
Living England maps at segment scale (Malek allocated to Corine Land Cover, 25 ha minimum
mapping unit). Cattle follow improved grassland plus ``acn_weight`` x semi-natural (acid,
calcareous, neutral) grassland; sheep and goats follow improved and semi-natural grassland and
rough grazing (dwarf shrub heath, bog, bracken, fen/marsh/swamp, saltmarsh). The weight of the
housed-cattle layer (``alpha_other``), the block size and ``acn_weight`` are calibrated against
the NAEI map on half of England and scored on the other half (``calibration.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from .grid import GRID
from .herd import GROUPS, SPECIES_OF_GROUP, group_totals

DATA = Path(__file__).resolve().parent / "data"

GRASS_CLASSES = {
    "improved_grassland": ("Improved Grassland",),
    "semi_natural_grassland": ("Acid, Calcareous, Neutral Grassland",),
    "rough_grazing": ("Dwarf Shrub Heath", "Bog", "Bracken", "Fen, Marsh and Swamp",
                      "Coastal Saltmarsh"),
}
MALEK_SOURCE = ("Malek, Romanchuk, Yashchun and See (2024), Spatial distribution of cattle, sheep "
                "and goat density, and grazed areas for the EU and the UK, v1, Zenodo, "
                "doi:10.5281/zenodo.13734518 (CC BY 4.0), ~2020, 100 m, LSU/ha")
LE_SOURCE = ("Living England Habitat Map Phase 4, Natural England (Open Government Licence), "
             "segments assigned to 1 km cells by centroid")
NAEI_SOURCE = ("NAEI gridded emissions 2020, methane, SNAP 10 agriculture, 1 km "
               "(naei.energysecurity.gov.uk, Open Government Licence)")


@dataclass(frozen=True)
class AllocationConfig:
    alpha_other: float = 0.0     # weight of Malek's housed-cattle layer
    block_km: int = 10           # 0 = no Living England refinement
    acn_weight: float = 0.5      # semi-natural grassland weight for cattle


@lru_cache(maxsize=1)
def layers() -> dict[str, np.ndarray]:
    """All shipped layers as float64 arrays, plus the England mask."""
    m = np.load(DATA / "malek_lsu_1km.npz")
    le = np.load(DATA / "living_england_1km.npz")
    classes = [str(c) for c in le["classes"]]
    ha = le["ha"].astype("f8")
    out = {k: m[k].astype("f8") for k in m.files if k != "cap_lsu_ha"}
    out["england"] = ha.sum(0) > 50.0     # Living England covers England only
    out["le_total"] = ha.sum(0)
    for name, members in GRASS_CLASSES.items():
        out[name] = sum(ha[classes.index(c)] for c in members)
    out["arable"] = ha[classes.index("Arable and Horticultural")]
    out["woodland"] = (ha[classes.index("Broadleaved, Mixed and Yew Woodland")]
                       + ha[classes.index("Coniferous Woodland")])
    out["naei_ch4_t"] = np.load(DATA / "naei_ch4_agriculture_2020.npz")["t_ch4"].astype("f8")
    return out


def le_classes() -> dict[str, float]:
    """England area (ha) of every Living England class."""
    le = np.load(DATA / "living_england_1km.npz")
    return {str(c): float(a.sum()) for c, a in zip(le["classes"], le["ha"])}


def _blocks(a: np.ndarray, k: int) -> np.ndarray:
    ny, nx = a.shape
    py, px = (-ny) % k, (-nx) % k
    a = np.pad(a, ((0, py), (0, px)))
    return a.reshape(a.shape[0] // k, k, a.shape[1] // k, k).sum((1, 3))


def _expand(b: np.ndarray, k: int, shape) -> np.ndarray:
    return np.kron(b, np.ones((k, k)))[: shape[0], : shape[1]]


def refine(weight: np.ndarray, grass: np.ndarray, k: int) -> np.ndarray:
    """Keep each k x k block's total of ``weight`` but share it out in proportion to ``grass``.

    Blocks with no grazing area keep the original weights.
    """
    if k <= 0:
        return weight.copy()
    wb = _expand(_blocks(weight, k), k, weight.shape)
    gb = _expand(_blocks(grass, k), k, weight.shape)
    return np.where(gb > 0, wb * grass / np.where(gb > 0, gb, 1.0), weight)


def grazing_area(species: str, cfg: AllocationConfig) -> np.ndarray:
    """Living England area (ha) that a species is allocated to, with weights."""
    L = layers()
    if species == "cattle":
        return L["improved_grassland"] + cfg.acn_weight * L["semi_natural_grassland"]
    return L["improved_grassland"] + L["semi_natural_grassland"] + L["rough_grazing"]


def species_weights(cfg: AllocationConfig) -> dict[str, np.ndarray]:
    """Unnormalised spatial weights per species, zero outside England."""
    L = layers()
    eng = L["england"]
    cattle = L["cattle_grazing"] + L["cattle_seminatural"] + cfg.alpha_other * L["cattle_other"]
    small = L["sheep_goats_other"] + L["sheep_goat_seminatural"]
    w = {"cattle": refine(np.where(eng, cattle, 0.0),
                          np.where(eng, grazing_area("cattle", cfg), 0.0), cfg.block_km),
         "sheep": refine(np.where(eng, small, 0.0),
                         np.where(eng, grazing_area("sheep", cfg), 0.0), cfg.block_km)}
    w["goats"] = w["sheep"]
    return w


def allocate(cfg: AllocationConfig) -> dict[str, np.ndarray]:
    """Heads per 1 km cell for each group (dairy, beef_other, sheep, goats)."""
    w = species_weights(cfg)
    tot = group_totals()
    return {g: tot[g] * w[SPECIES_OF_GROUP[g]] / w[SPECIES_OF_GROUP[g]].sum() for g in GROUPS}
