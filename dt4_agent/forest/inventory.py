"""Forest inventory on the CCI grid: woodland, species, planting year, yield class.

``scripts/extract_inventory.py`` rasterises two Forestry Commission open datasets (OGL v3.0)
onto each landscape's CCI v7 100 m grid:

* the **NFI woodland map GB 2024** (woodland mask and interpreted forest type), and
* the **Forestry England sub-compartment database** (main species, planting year and the
  Forestry England yield class of each stand on the public forest estate).

This module turns those rasters into what the twin needs per pixel:

``species``
    DT4 species group (:mod:`forest.species`). Sub-compartment species are mapped to groups
    with :data:`SPECIES_MAP`. Pixels with no recorded species (open ground, felled, outside the
    estate) take a group from the NFI forest type: conifer types get the landscape's dominant
    conifer, broadleaved types the mixed-broadleaf group, felled and young-tree types the
    dominant conifer (they are restocking).
``age``
    Stand age in a given year from the planting year, where recorded.
``fe_yield_class``
    Forestry England's yield class. **It is never used for calibration** (DT4 calibrates to
    Biomass CCI v7 only); it is kept as an independent check of the CCI-calibrated yield class.
``woodland``
    NFI woodland category (``CATEGORY == "Woodland"``), including felled and young stands.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parent / "data"
NFI_CITATION = ("National Forest Inventory Woodland GB 2024 and Forestry England Subcompartments, "
                "Forestry Commission open data. Contains, or is based on, information supplied "
                "by the Forestry Commission; Open Government Licence v3.0.")

# Forestry England species names -> DT4 species groups
SPECIES_MAP = {
    "Sitka spruce": "SS", "Norway spruce": "NS", "Serbian spruce": "NS", "Oriental spruce": "NS",
    "Corsican pine": "CP", "Austrian pine": "CP", "Macedonian pine": "CP", "Maritime pine": "CP",
    "Scots pine": "SP", "Lodgepole pine": "LP", "Mountain pine": "LP",
    "Douglas fir": "DF", "Grand Fir": "DF", "Noble fir": "DF", "Western hemlock": "DF",
    "Western red cedar": "DF", "Leyland cypress": "DF", "Wellingtonia": "DF", "Coast redwood": "DF",
    "Lawson cypress": "DF", "Mixed conifers": "DF", "Other conifers": "DF",
    "Hybrid larch": "LA", "European larch": "LA", "Japanese larch": "LA",
    "Oak (robur/petraea)": "OK", "Pedunculate oak": "OK", "Sessile oak": "OK", "Red oak": "OK",
    "Turkey oak": "OK",
    "Beech": "BE",
    "Birch (downy/silver)": "BI", "Downy birch": "BI", "Silver birch": "BI",
}
BROADLEAF_DEFAULT = "MB"   # sycamore, ash, alder, poplar, chestnut, rowan, mixed broadleaves


def species_group(fe_name: str | None) -> str | None:
    if not fe_name:
        return None
    if fe_name in SPECIES_MAP:
        return SPECIES_MAP[fe_name]
    low = fe_name.lower()
    if any(w in low for w in ("conifer", "pine", "spruce", "fir", "larch", "cedar", "cypress", "hemlock")):
        return "DF"
    return BROADLEAF_DEFAULT


def inventory_path(key: str) -> Path:
    return DATA_DIR / f"{key}_inventory.npz"


@dataclass(frozen=True)
class Inventory:
    key: str
    woodland: np.ndarray            # (row, col) bool, NFI woodland
    ift: np.ndarray                 # (row, col) object array of NFI forest type names ('' outside)
    species: np.ndarray             # (row, col) object array of DT4 species codes ('' none)
    species_recorded: np.ndarray    # (row, col) bool: species from a sub-compartment record
    fe_species_name: np.ndarray     # (row, col) object array of the raw FE species name
    planting_year: np.ndarray       # (row, col) int, 0 = unknown
    fe_yield_class: np.ndarray      # (row, col) int, 0 = unknown
    fe_present: np.ndarray

    def age(self, year: int) -> np.ndarray:
        """Stand age (years) in ``year``; -1 where the planting year is unknown or later."""
        a = year - self.planting_year
        return np.where((self.planting_year > 0) & (a >= 0), a, -1)


@lru_cache(maxsize=8)
def load(key: str, dominant_conifer: str | None = None) -> Inventory:
    path = inventory_path(key)
    if not path.exists():
        raise FileNotFoundError(f"{path.name} is missing; run scripts/extract_inventory.py")
    d = np.load(path)
    if dominant_conifer is None:
        from .landscapes import get

        dominant_conifer = get(key).species
    ift_names = np.array([""] + [str(x) for x in d["nfi_ift_names"]], dtype=object)
    ift = ift_names[d["nfi_ift"]]
    fe_names = np.array([""] + [str(x) for x in d["fe_species_names"]], dtype=object)
    fe_name = fe_names[d["fe_species"]]
    lut = {n: (species_group(n) or "") for n in fe_names}
    species = np.vectorize(lut.get, otypes=[object])(fe_name)
    recorded = species != ""
    conifer_types = {"Conifer", "Mixed mainly conifer", "Felled", "Young trees", "Windblow",
                     "Ground prep", "Failed", "Assumed woodland", "Low density"}
    broad_types = {"Broadleaved", "Mixed mainly broadleaved", "Coppice", "Coppice with standards",
                   "Shrub"}
    fill = np.where(np.isin(ift, list(conifer_types)), dominant_conifer,
                    np.where(np.isin(ift, list(broad_types)), BROADLEAF_DEFAULT, ""))
    species = np.where(recorded, species, fill).astype(object)
    return Inventory(key=key, woodland=d["nfi_woodland"].astype(bool), ift=ift, species=species,
                     species_recorded=recorded, fe_species_name=fe_name,
                     planting_year=d["fe_planting_year"].astype(int),
                     fe_yield_class=d["fe_yield_class"].astype(int),
                     fe_present=d["fe_present"].astype(bool))


def composition(inv: Inventory, mask: np.ndarray, pixel_area_ha: np.ndarray, year: int) -> list[dict]:
    """Area, share, age and FE yield class by species group within ``mask``."""
    sel = mask & (inv.species != "")
    total = float(pixel_area_ha[sel].sum())
    rows = []
    for code in sorted(set(inv.species[sel])):
        m = sel & (inv.species == code)
        ages = inv.age(year)[m]
        ages = ages[ages >= 0]
        yc = inv.fe_yield_class[m]
        yc = yc[yc > 0]
        rows.append({"species": code, "area_ha": float(pixel_area_ha[m].sum()),
                     "share": float(pixel_area_ha[m].sum() / total) if total else 0.0,
                     "recorded_share": float((m & inv.species_recorded).sum() / m.sum()),
                     "age_median": float(np.median(ages)) if ages.size else None,
                     "age_p25": float(np.percentile(ages, 25)) if ages.size else None,
                     "age_p75": float(np.percentile(ages, 75)) if ages.size else None,
                     "fe_yield_class_median": float(np.median(yc)) if yc.size else None,
                     "n_pixels": int(m.sum())})
    return sorted(rows, key=lambda r: -r["area_ha"])
