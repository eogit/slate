"""Biomass change and its attribution, following the Living Earth EBCF rules.

The SLATE inventory asks every twin to keep state, observed impact, inferred pressure and
management response in separate fields, and to name a pressure only when independent
evidence supports it (Lucas et al. 2022, Global Change Biology 28, 6293). DT4 does this in
two steps.

1. :func:`area_change` measures the change in CCI AGB between two years, pixel by pixel and
   for the area, and labels it as an **impact** only where it is larger than the combined
   uncertainty (90 %). Each significant pixel is also classed as a **modification** (woody
   vegetation remains, its amount changed) or a candidate **conversion** (AGB fell below the
   woodland threshold, e.g. a clearfell or windthrow; whether the land cover class really
   changed needs the land-cover twin).
2. :func:`attribute` assigns significant losses to a **pressure** (harvest, wind, fire, biotic,
   drought) only where the caller supplies evidence that overlaps them in space and time
   (felling licences, storm footprints, fire perimeters, tree-health surveys). Without
   evidence the loss stays "unattributed". The result uses the EBCF ``impact (pressure)``
   notation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import cci

PRESSURES = ("harvest", "wind", "fire", "biotic", "drought")
IMPACT_LOSS = "woody vegetation amount decrease"
IMPACT_GAIN = "woody vegetation amount increase"
IMPACT_NONE = "no detectable change"


def area_change(cube: cci.Cube, year1: int, year2: int, mask: np.ndarray) -> dict:
    if year2 <= year1:
        raise ValueError("year2 must be after year1")
    pc = cci.pixel_change(cube, year1, year2, mask)
    area = cube.pixel_area_ha()
    d = pc["delta"][mask]
    sd = cci.area_sd(pc["sd"][mask])
    mean = float(d.mean())
    significant = abs(mean) > cci.Z90 * sd
    after = cube.agb[cube.year_index(year2)]
    conversion = pc["loss"] & (after < cci.WOODLAND_MEDIAN_MG_HA)
    modification_loss = pc["loss"] & ~conversion
    impact = IMPACT_NONE if not significant else (IMPACT_LOSS if mean < 0 else IMPACT_GAIN)
    return {
        "year1": int(year1), "year2": int(year2),
        "delta_agb_mean_mg_ha": mean, "delta_agb_sd_mg_ha": sd,
        "delta_agb_p05_mg_ha": mean - cci.Z90 * sd, "delta_agb_p95_mg_ha": mean + cci.Z90 * sd,
        "delta_agb_per_year_mg_ha": mean / (year2 - year1),
        "significant_at_90pct": bool(significant),
        "impact": impact,
        "loss_area_ha": float(area[pc["loss"]].sum()),
        "gain_area_ha": float(area[pc["gain"]].sum()),
        "conversion_candidate_area_ha": float(area[conversion].sum()),
        "modification_loss_area_ha": float(area[modification_loss].sum()),
        "area_ha": float(area[mask].sum()),
        "crosses_sensor_epoch": cci.crosses_epoch(year1, year2),
        "_loss_mask": pc["loss"],
    }


@dataclass(frozen=True)
class Evidence:
    """Independent evidence of a pressure: what, when and where."""

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

    def footprint(self, cube: cci.Cube) -> np.ndarray:
        lon, lat = cube.lonlat()
        if self.bbox is not None:
            w, s, e, n = self.bbox
            return (lon >= w) & (lon <= e) & (lat >= s) & (lat <= n)
        plon, plat = self.point
        dx = (lon - plon) * 111_320.0 * math.cos(math.radians(plat))
        dy = (lat - plat) * 111_320.0
        return np.hypot(dx, dy) <= max(self.radius_m, 50.0)


def attribute(cube: cci.Cube, change: dict, evidence: list[Evidence]) -> dict:
    """Split the significant loss of ``change`` among pressures with overlapping evidence."""
    loss = change["_loss_mask"]
    area = cube.pixel_area_ha()
    total = float(area[loss].sum())
    claimed = np.zeros(cube.shape, dtype=bool)
    rows = []
    for ev in evidence:
        overlaps_time = ev.year_to > change["year1"] and ev.year_from <= change["year2"]
        hit = loss & ev.footprint(cube) & ~claimed if overlaps_time else np.zeros_like(loss)
        claimed |= hit
        a = float(area[hit].sum())
        rows.append({"pressure": ev.pressure, "source": ev.source,
                     "years": [ev.year_from, ev.year_to], "overlaps_in_time": overlaps_time,
                     "attributed_loss_area_ha": a,
                     "share_of_loss": a / total if total else 0.0,
                     "label": f"{IMPACT_LOSS} ({ev.pressure})"})
    unattributed = float(area[loss & ~claimed].sum())
    return {"loss_area_ha": total, "attributions": rows,
            "unattributed_loss_area_ha": unattributed,
            "unattributed_share": unattributed / total if total else 0.0,
            "rule": "A pressure is named only where independent evidence overlaps a "
                    "significant loss in space and time (Living Earth EBCF)."}
