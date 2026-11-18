"""The DT6 inventory: every Trees Outside Woodland object of a pilot, with its lidar heights.

``scripts/extract_pilots.py`` writes ``data/<pilot>_crowns.npz``. Each row is one object of
the National Trees Outside Woodland map (Forest Research 2025, OGL v3): a lone tree, a group
of trees or a small woodland, all with canopy over 3 m and at least 5 m2 outside NFI
woodland. NFI overhanging canopy is left to DT4.

What DT6 derives per object:

``n_trees``
    1 for a lone tree; for groups and small woods the number of tree tops found in the
    first-return canopy height model (local maxima 5 m apart), at least 1.
``crown_diam_m``
    the diameter of a circle with the object's area shared equally among its trees.
``height_m``
    the tallest first return above ground (NLP). Trees in groups and small woods are not all
    as tall as the tallest, so their representative height is ``GROUP_HEIGHT_FACTOR`` (0.85)
    of it.
``crown_ratio``
    crown diameter / height, kept constant as a tree grows, so biomass can be grown with
    height alone.
``p_conifer``
    the pilot's a priori conifer share (``trees.pilots``), since no open dataset gives leaf
    type for these trees.
``h_lz``, ``date_lz``
    last-return heights at every lidar epoch (old EA surveys and the NLP) and their flight
    dates, the observations DT6 is calibrated against.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from . import allometry
from .pilots import DATA_DIR, get

CLASSES = ("lone_tree", "group_of_trees", "small_woodland")
GROUP_HEIGHT_FACTOR = 0.85
CITATION = ("National Trees Outside Woodland Map V1 (Forest Research / Forestry Commission, "
            "NCEA, 2025) and Environment Agency LIDAR (National LIDAR Programme and LIDAR "
            "Tiles DSM/DTM). Open Government Licence v3.0.")


def crowns_path(key: str):
    return DATA_DIR / f"{key}_crowns.npz"


@dataclass(frozen=True)
class Inventory:
    key: str
    tow_id: np.ndarray
    cls: np.ndarray              # 0 lone tree, 1 group of trees, 2 small woodland
    area_m2: np.ndarray
    n_trees: np.ndarray
    crown_diam_m: np.ndarray
    height_m: np.ndarray         # representative tree height (first return)
    h_fz: np.ndarray             # tallest first return
    fz_date: np.ndarray
    lon: np.ndarray
    lat: np.ndarray
    x: np.ndarray
    y: np.ndarray
    epoch_year: np.ndarray
    h_lz: np.ndarray             # (object, epoch) last-return height, NaN where not covered
    date_lz: np.ndarray
    p_conifer: float

    @property
    def n(self) -> int:
        return int(self.cls.size)

    @property
    def crown_ratio(self) -> np.ndarray:
        return self.crown_diam_m / np.maximum(self.height_m, 0.5)

    @property
    def leaf_off_ratio(self) -> np.ndarray:
        """Last-return / first-return height at the latest NLP flight (same night)."""
        r = self.h_lz[:, -1] / np.maximum(self.h_fz, 0.5)
        return np.clip(np.where(np.isfinite(r), r, 1.0), 0.5, 1.0)

    def agb_kg(self) -> np.ndarray:
        """AGB of each object (kg): its trees times the biomass of one representative tree."""
        return self.n_trees * allometry.agb_kg(self.height_m, self.crown_diam_m, self.p_conifer)

    def select(self, mask) -> "Inventory":
        m = np.asarray(mask, dtype=bool)
        kw = {k: (getattr(self, k)[m] if isinstance(getattr(self, k), np.ndarray) and
                  getattr(self, k).shape[:1] == (self.n,) and k != "epoch_year" else getattr(self, k))
              for k in self.__dataclass_fields__}
        return Inventory(**kw)


@lru_cache(maxsize=16)
def load(key: str) -> Inventory:
    pilot = get(key)
    path = crowns_path(key)
    if not path.exists():
        raise FileNotFoundError(f"{path.name} is missing; run scripts/extract_pilots.py {key}")
    d = np.load(path)
    ok = np.isfinite(d["h_fz"]) & (d["h_fz"] >= 3.0) & (d["area_m2"] > 0)
    cls = d["tow_class"].astype(int)[ok]
    area = d["area_m2"].astype(float)[ok]
    n_trees = np.where(cls == 0, 1, np.maximum(d["n_tops"][ok], 1)).astype(int)
    h_fz = d["h_fz"].astype(float)[ok]
    height = np.where(cls == 0, h_fz, GROUP_HEIGHT_FACTOR * h_fz)
    cd = 2.0 * np.sqrt(area / (n_trees * np.pi))
    return Inventory(key=key, tow_id=d["tow_id"][ok], cls=cls, area_m2=area, n_trees=n_trees,
                     crown_diam_m=cd, height_m=height, h_fz=h_fz,
                     fz_date=d["fz_date"].astype(float)[ok], lon=d["lon"].astype(float)[ok],
                     lat=d["lat"].astype(float)[ok], x=d["x"].astype(float)[ok],
                     y=d["y"].astype(float)[ok], epoch_year=d["epoch_year"].astype(int),
                     h_lz=d["h_lz"].astype(float)[ok], date_lz=d["date_lz"].astype(float)[ok],
                     p_conifer=pilot.p_conifer)


def summary(inv: Inventory, mask=None) -> dict:
    m = np.ones(inv.n, bool) if mask is None else np.asarray(mask, bool)
    agb = inv.agb_kg()[m]
    rows = []
    for i, name in enumerate(CLASSES):
        k = m & (inv.cls == i)
        rows.append({"class": name, "objects": int(k.sum()), "trees": int(inv.n_trees[k].sum()),
                     "canopy_area_ha": float(inv.area_m2[k].sum() / 1e4),
                     "height_median_m": float(np.median(inv.h_fz[k])) if k.any() else None,
                     "agb_t": float(inv.agb_kg()[k].sum() / 1000)})
    return {"objects": int(m.sum()), "trees": int(inv.n_trees[m].sum()),
            "canopy_area_ha": float(inv.area_m2[m].sum() / 1e4), "agb_t": float(agb.sum() / 1000),
            "by_class": rows}
