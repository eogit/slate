"""DT2 emission engine: enteric and manure methane per 1 km cell, for an area, under scenarios.

The pipeline for one call is

    June Survey head counts (herd.py)
      -> placed on the 1 km grid with Malek et al. + Living England (maps.py)
      -> optionally scaled by a site's learned factors (assimilation.py, state.py)
      -> scenario changes to heads, grazing share, manure systems, enteric methane
      -> x inventory emission factors (factors.py)
      -> summed over the requested area.

Units: heads, hectares, tonnes CH4 per year; CO2e with the GWP100 of AR5 (28, the Farm Carbon
Calculator's choice) and AR6 (27, as DT8 reports). Positive = emission to the atmosphere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from .factors import CATEGORIES, GWP100, shares_with
from .grid import GRID
from .herd import GROUPS, LSU, SPECIES_OF_GROUP, group_structure
from .maps import AllocationConfig, allocate, grazing_area, layers

# --------------------------------------------------------------------------- #
# areas
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Area:
    """A region of England: a BNG box, a circle around a WGS84 point, or all of England."""
    bbox_bng: tuple[float, float, float, float] | None = None   # xmin, ymin, xmax, ymax (m)
    lat: float | None = None
    lon: float | None = None
    radius_km: float | None = None

    def describe(self) -> str:
        if self.bbox_bng:
            return "BNG box %.0f,%.0f,%.0f,%.0f m" % self.bbox_bng
        if self.lat is not None:
            return f"{self.radius_km:g} km around {self.lat:.4f}N {self.lon:.4f}E"
        return "England"

    def mask(self) -> np.ndarray:
        """1 km cells of England whose centre lies in the area."""
        eng = layers()["england"]
        if self.bbox_bng is None and self.lat is None:
            return eng.copy()
        rows, cols = np.indices(GRID.shape)
        x = GRID.x0 + (cols + 0.5) * GRID.res
        y = GRID.y1 - (rows + 0.5) * GRID.res
        if self.bbox_bng:
            x0, y0, x1, y1 = self.bbox_bng
            m = (x >= x0) & (x < x1) & (y >= y0) & (y < y1)
        else:
            cx, cy = to_bng(self.lat, self.lon)
            m = (x - cx) ** 2 + (y - cy) ** 2 <= (self.radius_km * 1000.0) ** 2
        return m & eng


@lru_cache(maxsize=1)
def _transformer():
    from pyproj import Transformer
    return Transformer.from_crs(4326, 27700, always_xy=True)


def to_bng(lat: float, lon: float) -> tuple[float, float]:
    return _transformer().transform(lon, lat)


# --------------------------------------------------------------------------- #
# scenarios
# --------------------------------------------------------------------------- #


@dataclass
class Scenario:
    """Changes applied inside the area. Empty = the baseline (inventory 2023 practice)."""
    herd_change_pct: dict[str, float] = field(default_factory=dict)   # group -> %
    pasture_pct: dict[str, float] = field(default_factory=dict)       # group -> % excreta
    ad_pct_of_housed: float | None = None                             # cattle manure to AD
    enteric_reduction_pct: dict[str, float] = field(default_factory=dict)   # group -> %
    grassland_loss_pct: float = 0.0     # improved + semi-natural grassland converted
    max_stocking_lsu_ha: float | None = None

    def is_baseline(self) -> bool:
        return (not self.herd_change_pct and not self.pasture_pct and
                self.ad_pct_of_housed is None and not self.enteric_reduction_pct and
                self.grassland_loss_pct == 0 and self.max_stocking_lsu_ha is None)


def per_head_factors(group: str, sc: Scenario | None = None) -> dict[str, float]:
    """Head-weighted enteric and manure kg CH4/head/yr of a group (England herd structure)."""
    sc = sc or Scenario()
    ent = man = lsu = 0.0
    for code, frac in group_structure()[group].items():
        cat = CATEGORIES[code]
        shares = None
        if group in sc.pasture_pct or (sc.ad_pct_of_housed is not None
                                       and cat.species == "cattle"):
            shares = shares_with(cat, pasture_pct=sc.pasture_pct.get(group),
                                 ad_pct_of_housed=(sc.ad_pct_of_housed
                                                   if cat.species == "cattle" else None))
        red = sc.enteric_reduction_pct.get(group, 0.0) / 100.0
        ent += frac * cat.enteric * (1.0 - red)
        man += frac * cat.manure_ef(shares)
        lsu += frac * LSU[code]
    return {"enteric": ent, "manure": man, "lsu": lsu}


@lru_cache(maxsize=8)
def _baseline_heads(cfg: AllocationConfig) -> dict[str, np.ndarray]:
    return allocate(cfg)


def heads(cfg: AllocationConfig, area_mask: np.ndarray, scales: dict[str, float],
          sc: Scenario | None = None) -> dict[str, np.ndarray]:
    """Heads per cell per group inside the area, after site scaling and the scenario."""
    sc = sc or Scenario()
    base = _baseline_heads(cfg)
    L = layers()
    out = {}
    for g in GROUPS:
        sp = SPECIES_OF_GROUP[g]
        h = np.where(area_mask, base[g], 0.0) * scales.get(sp if sp != "goats" else "sheep", 1.0)
        h = h * (1.0 + sc.herd_change_pct.get(g, 0.0) / 100.0)
        if sc.grassland_loss_pct:
            # Animals leave with the grass they grazed: the loss is taken from improved and
            # semi-natural grassland, rough grazing is kept.
            ga = grazing_area(sp if sp != "goats" else "sheep", cfg)
            if sp == "cattle":
                lost = ga * sc.grassland_loss_pct / 100.0
            else:
                lost = (L["improved_grassland"] + L["semi_natural_grassland"]) \
                    * sc.grassland_loss_pct / 100.0
            h = h * np.where(ga > 0, 1.0 - lost / np.where(ga > 0, ga, 1.0), 1.0)
        out[g] = h
    if sc.max_stocking_lsu_ha is not None:
        lsu = sum(out[g] * per_head_factors(g)["lsu"] for g in GROUPS)
        area = grassland(area_mask)["grazing_ha_cell"]
        cap = sc.max_stocking_lsu_ha * area
        f = np.where(lsu > cap, cap / np.where(lsu > 0, lsu, 1.0), 1.0)
        out = {g: out[g] * f for g in GROUPS}
    return out


def grassland(area_mask: np.ndarray) -> dict:
    L = layers()
    imp = np.where(area_mask, L["improved_grassland"], 0.0)
    acn = np.where(area_mask, L["semi_natural_grassland"], 0.0)
    rough = np.where(area_mask, L["rough_grazing"], 0.0)
    return {"improved_ha": float(imp.sum()), "semi_natural_ha": float(acn.sum()),
            "rough_grazing_ha": float(rough.sum()),
            "land_ha": float(np.where(area_mask, L["le_total"], 0.0).sum()),
            "grazing_ha_cell": imp + acn + rough}


def emissions_grid(cfg: AllocationConfig, area_mask: np.ndarray, scales: dict[str, float],
                   sc: Scenario | None = None) -> dict[str, dict[str, np.ndarray]]:
    """t CH4 per cell, per group and source (enteric, manure), plus heads."""
    sc = sc or Scenario()
    h = heads(cfg, area_mask, scales, sc)
    out = {}
    for g in GROUPS:
        f = per_head_factors(g, sc)
        out[g] = {"heads": h[g], "enteric": h[g] * f["enteric"] / 1000.0,
                  "manure": h[g] * f["manure"] / 1000.0, "lsu": h[g] * f["lsu"]}
    return out


def summarise(grid: dict, area_mask: np.ndarray) -> dict:
    """Area totals from ``emissions_grid`` output."""
    groups = {}
    for g, d in grid.items():
        ent, man = float(d["enteric"].sum()), float(d["manure"].sum())
        groups[g] = {"heads": float(d["heads"].sum()), "lsu": float(d["lsu"].sum()),
                     "enteric_t_ch4": ent, "manure_t_ch4": man, "total_t_ch4": ent + man}
    ent = sum(v["enteric_t_ch4"] for v in groups.values())
    man = sum(v["manure_t_ch4"] for v in groups.values())
    gl = grassland(area_mask)
    lsu = sum(v["lsu"] for v in groups.values())
    grazing = gl["improved_ha"] + gl["semi_natural_ha"] + gl["rough_grazing_ha"]
    return {"groups": groups, "enteric_t_ch4": ent, "manure_t_ch4": man,
            "total_t_ch4": ent + man,
            "t_co2e_ar5": (ent + man) * GWP100["AR5"], "t_co2e_ar6": (ent + man) * GWP100["AR6"],
            "cells_km2": int(area_mask.sum()), "lsu": lsu,
            "grassland": {k: v for k, v in gl.items() if k != "grazing_ha_cell"},
            "stocking_lsu_per_grazing_ha": lsu / grazing if grazing > 0 else None,
            "kg_ch4_per_grazing_ha": (ent + man) * 1000.0 / grazing if grazing > 0 else None}


def run(area: Area, cfg: AllocationConfig, scales: dict[str, float] | None = None,
        sc: Scenario | None = None) -> dict:
    m = area.mask()
    return summarise(emissions_grid(cfg, m, scales or {}, sc), m)
