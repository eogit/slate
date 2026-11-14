"""Canopy-height change of trees outside woodland and its attribution (Living Earth EBCF).

As in DT4, state, observed impact and inferred pressure are kept apart, and a pressure is
named only where independent evidence supports it (Lucas et al. 2022).

1. :func:`height_change` compares the last-return height of every object between two lidar
   epochs (the nearest available epochs to the requested years). A change is an **impact**
   only where it exceeds the 90 % threshold of the combined observation error
   (``Z90 * sqrt(2) * calibration.SIGMA_LZ`` = 3.5 m). Significant reductions are classed as
   * **modification**: the tree is still taller than 3 m (pruning, pollarding, crown loss,
     partial felling), or
   * **removal candidate**: the object fell below the 3 m TOW threshold (felled, or a hedge
     cut down). Whether the land cover really changed needs the land-cover twin.
   The biomass lost is estimated with the crown allometry.
2. :func:`attribute` assigns significant reductions to a pressure (felling, hedge or tree
   management, ash dieback and other disease, storm, development) only where evidence
   overlaps them in space and time. Without evidence they stay "unattributed".

Limitation: the TOW map lists trees present in 2016-2023, so trees removed *before* the map
was made are not in the inventory and their loss cannot be seen. Gains of new trees between
epochs are likewise only seen if they are on the map today.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import allometry
from .calibration import SIGMA_LZ, lz_ratio
from .inventory import GROUP_HEIGHT_FACTOR, Inventory

Z90 = 1.645
THRESHOLD_M = Z90 * math.sqrt(2) * SIGMA_LZ
TOW_MIN_HEIGHT = 3.0
PRESSURES = ("felling", "tree_management", "ash_dieback", "disease", "storm", "development")
IMPACT_LOSS = "woody vegetation amount decrease"
IMPACT_GAIN = "woody vegetation amount increase"
IMPACT_NONE = "no detectable change"


def nearest_epoch(inv: Inventory, year: int) -> int:
    return int(np.argmin(np.abs(inv.epoch_year - year)))


def height_change(inv: Inventory, year1: int, year2: int, mask=None) -> dict:
    """Object-by-object last-return height change between the epochs nearest two years."""
    if year2 <= year1:
        raise ValueError("year2 must be after year1")
    e1, e2 = nearest_epoch(inv, year1), nearest_epoch(inv, year2)
    if e1 == e2:
        raise ValueError(f"years {year1} and {year2} map to the same lidar epoch "
                         f"({int(inv.epoch_year[e1])}); epochs: {inv.epoch_year.tolist()}")
    m = np.ones(inv.n, bool) if mask is None else np.asarray(mask, bool)
    h1, h2 = inv.h_lz[:, e1], inv.h_lz[:, e2]
    both = m & np.isfinite(h1) & np.isfinite(h2)
    d = np.where(both, h2 - h1, np.nan)
    loss = both & (d < -THRESHOLD_M)
    gain = both & (d > THRESHOLD_M)
    removal = loss & (h2 < TOW_MIN_HEIGHT)
    modification = loss & ~removal
    # biomass lost: representative tree heights before and after (last return scaled to
    # first return with the pilot ratio), crown ratio held constant
    g = np.where(inv.cls == 0, 1.0, GROUP_HEIGHT_FACTOR)
    rho = lz_ratio(inv)
    hr1, hr2 = g * h1 / rho, g * np.maximum(h2, 0.0) / rho
    cr = inv.crown_ratio
    agb1 = inv.n_trees * allometry.agb_kg(np.nan_to_num(hr1), cr * np.nan_to_num(hr1), inv.p_conifer)
    agb2 = inv.n_trees * allometry.agb_kg(np.nan_to_num(hr2), cr * np.nan_to_num(hr2), inv.p_conifer)
    dyears = float(np.nanmedian(inv.date_lz[both, e2] - inv.date_lz[both, e1])) if both.any() else float("nan")
    lost_t = float((agb1 - agb2)[loss].sum() / 1000)
    n = int(both.sum())
    share_loss = loss.sum() / n if n else 0.0
    impact = IMPACT_NONE
    if n and loss.sum() > 0.05 * n:
        impact = IMPACT_LOSS
    elif n and gain.sum() > 0.05 * n:
        impact = IMPACT_GAIN
    return {
        "epoch1": int(inv.epoch_year[e1]), "epoch2": int(inv.epoch_year[e2]),
        "years_between_median": dyears,
        "objects_compared": n,
        "median_change_m": float(np.nanmedian(d[both])) if n else None,
        "median_growth_m_yr": float(np.nanmedian(d[both]) / dyears) if n and dyears > 0 else None,
        "threshold_m": THRESHOLD_M,
        "significant_reductions": int(loss.sum()),
        "significant_increases": int(gain.sum()),
        "modification_reductions": int(modification.sum()),
        "removal_candidates": int(removal.sum()),
        "share_reduced": float(share_loss),
        "agb_lost_t": lost_t,
        "impact": impact,
        "impact_rule": "an area impact is reported when over 5 % of compared objects change "
                       "beyond the 90 % threshold",
        "_loss_mask": loss,
        "_years": (int(inv.epoch_year[e1]), int(inv.epoch_year[e2])),
    }


@dataclass(frozen=True)
class Evidence:
    """Independent evidence of a pressure: what, when and where (lon/lat)."""

    pressure: str
    year_from: int
    year_to: int
    bbox: tuple[float, float, float, float] | None = None
    point: tuple[float, float] | None = None
    radius_m: float = 0.0
    source: str = ""

    def __post_init__(self):
        if self.pressure not in PRESSURES:
            raise ValueError(f"unknown pressure {self.pressure!r}; known: {PRESSURES}")
        if self.bbox is None and self.point is None:
            raise ValueError("evidence needs a bbox or a point")

    def footprint(self, inv: Inventory) -> np.ndarray:
        if self.bbox is not None:
            w, s, e, n = self.bbox
            return (inv.lon >= w) & (inv.lon <= e) & (inv.lat >= s) & (inv.lat <= n)
        plon, plat = self.point
        dx = (inv.lon - plon) * 111_320.0 * math.cos(math.radians(plat))
        dy = (inv.lat - plat) * 111_320.0
        return np.hypot(dx, dy) <= max(self.radius_m, 10.0)


def attribute(inv: Inventory, change: dict, evidence: list[Evidence]) -> dict:
    """Split significant reductions among pressures whose evidence overlaps them."""
    loss = change["_loss_mask"]
    y1, y2 = change["_years"]
    total = int(loss.sum())
    claimed = np.zeros(inv.n, bool)
    rows = []
    for ev in evidence:
        overlaps = ev.year_to >= y1 and ev.year_from <= y2
        hit = loss & ev.footprint(inv) & ~claimed if overlaps else np.zeros(inv.n, bool)
        claimed |= hit
        rows.append({"pressure": ev.pressure, "source": ev.source,
                     "years": [ev.year_from, ev.year_to], "overlaps_in_time": overlaps,
                     "attributed_objects": int(hit.sum()),
                     "share_of_reductions": hit.sum() / total if total else 0.0,
                     "label": f"{IMPACT_LOSS} ({ev.pressure})"})
    un = int((loss & ~claimed).sum())
    return {"reductions": total, "attributions": rows, "unattributed_objects": un,
            "unattributed_share": un / total if total else 0.0,
            "rule": "A pressure is named only where independent evidence overlaps a "
                    "significant reduction in space and time (Living Earth EBCF)."}
