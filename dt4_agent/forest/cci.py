"""ESA Biomass CCI v7.0: the only observations DT4 is calibrated against.

The cubes in ``forest/data/`` hold, for each pilot landscape, the CCI v7.0 above-ground
biomass (AGB, Mg dry matter ha-1) and its per-pixel standard deviation (SD) on the native
100 m grid (0.000888 degrees, EPSG:4326) for 2005-2012 and 2015-2024. There are no maps for
2013 and 2014. They were cut from the CEDA archive by ``scripts/extract_cci_pilots.py``.

Woodland mask. The woodland mask comes from the National Forest Inventory woodland map GB
2024 (pixels whose centre lies in an NFI polygon of category "Woodland", which includes
felled and young stands), rasterised onto the CCI grid by ``scripts/extract_inventory.py``.
The map only defines *where* the woodland is; it is not used for calibration. If the
inventory file is missing, a CCI-only mask is used instead: a pixel is woodland if its
median AGB over 2015-2024 is at least ``WOODLAND_MEDIAN_MG_HA`` (20 Mg/ha) or it held at
least ``WOODLAND_PEAK_MG_HA`` (60 Mg/ha) in any year. ``Cube.woodland_source`` says which.

Uncertainty of area means. CCI per-pixel errors are spatially correlated, so averaging *n*
pixels does not shrink the error by sqrt(n). DT4 uses an effective sample size
``n_eff = n / CORRELATION_PIXELS`` (25 pixels, about a 500 m correlation length) and keeps a
systematic share ``SYSTEMATIC_FRACTION`` (30 %) of the mean pixel SD that does not average
out at all. Both numbers are assumptions; they make the area SD honest rather than tiny.

Sensor epochs. v7.0 maps for 2005-2012 come from ALOS PALSAR and Envisat ASAR, those for
2015-2024 from ALOS-2 PALSAR-2 and Sentinel-1. Changes measured across the 2012/2015 gap
mix real change with a change of sensors, and results flag them.

Citation: Santoro, M.; Cartus, O. (2026): ESA Biomass Climate Change Initiative
(Biomass_cci): Global datasets of forest above-ground biomass for the years 2005-2012 and
2015-2024, v7.0. NERC EDS CEDA. https://catalogue.ceda.ac.uk/uuid/6429d1aafe1e43b9b414e4a5a7f8b903
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

CCI_VERSION = "7.0"
CCI_YEARS = (2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012,
             2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024)
EPOCH_BREAK = (2012, 2015)  # sensor change between these years
DATA_DIR = Path(__file__).resolve().parent / "data"
CITATION = ("Santoro, M.; Cartus, O. (2026): ESA Biomass Climate Change Initiative (Biomass_cci): "
            "Global datasets of forest above-ground biomass for the years 2005-2012 and "
            "2015-2024, v7.0. NERC EDS Centre for Environmental Data Analysis.")
CATALOGUE = "https://catalogue.ceda.ac.uk/uuid/6429d1aafe1e43b9b414e4a5a7f8b903"
LICENCE = "ESA CCI Biomass terms and conditions v2: free and open, citation required"

WOODLAND_MEDIAN_MG_HA = 20.0
WOODLAND_PEAK_MG_HA = 60.0
CORRELATION_PIXELS = 25.0
SYSTEMATIC_FRACTION = 0.30
SATURATION_MG_HA = 150.0    # CCI v7 plateau in the pilot conifer stands (calibration.py)
SD_FLOOR_MG_HA = 10.0      # minimum observation error used in fitting
Z90 = 1.6449               # two-sided 90 % interval / one-sided 95 % test


@dataclass(frozen=True)
class Cube:
    """CCI AGB and SD for one landscape. Arrays are (year, row, col), float Mg/ha."""

    key: str
    agb: np.ndarray
    sd: np.ndarray
    years: tuple[int, ...]
    transform: tuple[float, ...]  # affine (a, b, c, d, e, f): lon = c + a*col, lat = f + e*row
    woodland: np.ndarray          # (row, col) bool
    woodland_source: str = "NFI woodland GB 2024"

    @property
    def shape(self) -> tuple[int, int]:
        return self.agb.shape[1:]

    def year_index(self, year: int) -> int:
        try:
            return self.years.index(int(year))
        except ValueError:
            raise ValueError(f"no CCI v{CCI_VERSION} map for {year}; years: "
                             f"{self.years[0]}-2012 and 2015-{self.years[-1]}") from None

    def lonlat(self) -> tuple[np.ndarray, np.ndarray]:
        """Pixel-centre longitude and latitude grids."""
        a, _, c, _, e, f = self.transform
        rows, cols = self.shape
        lon = c + a * (np.arange(cols) + 0.5)
        lat = f + e * (np.arange(rows) + 0.5)
        return np.meshgrid(lon, lat)

    def pixel_area_ha(self) -> np.ndarray:
        """Area of each pixel (ha), from the latitude of its row."""
        a, _, _, _, e, _ = self.transform
        _, lat = self.lonlat()
        dy = abs(e) * 111_320.0
        dx = abs(a) * 111_320.0 * np.cos(np.radians(lat))
        return dx * dy / 10_000.0


@lru_cache(maxsize=8)
def load(key: str) -> Cube:
    """Load a landscape's bundled cube (cached)."""
    path = DATA_DIR / f"{key}_cci_v{CCI_VERSION}.npz"
    if not path.exists():
        raise FileNotFoundError(f"{path.name} is missing; run scripts/extract_cci_pilots.py "
                                f"--pilot {key}")
    d = np.load(path)
    agb = d["agb"].astype(float)
    sd = d["agb_sd"].astype(float)
    years = tuple(int(y) for y in d["years"])
    post = np.array([y >= EPOCH_BREAK[1] for y in years])
    inv_path = DATA_DIR / f"{key}_inventory.npz"
    if inv_path.exists():
        woodland = np.load(inv_path)["nfi_woodland"].astype(bool)
        source = "NFI woodland GB 2024"
    else:
        woodland = (np.median(agb[post], axis=0) >= WOODLAND_MEDIAN_MG_HA) | \
                   (agb.max(axis=0) >= WOODLAND_PEAK_MG_HA)
        source = "CCI v7 (median AGB 2015-2024 >= 20 or peak >= 60 Mg/ha)"
    return Cube(key=key, agb=agb, sd=sd, years=years,
                transform=tuple(float(x) for x in d["transform"]), woodland=woodland,
                woodland_source=source)


# --------------------------------------------------------------------------- #
# area selection
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Area:
    """A part of a landscape: everything (default), a lon/lat box, or a point with a radius."""

    bbox: tuple[float, float, float, float] | None = None   # west, south, east, north
    point: tuple[float, float] | None = None                 # lon, lat
    radius_m: float = 0.0

    def describe(self) -> str:
        if self.point is not None:
            return (f"point lon {self.point[0]:.4f}, lat {self.point[1]:.4f}"
                    + (f", radius {self.radius_m:.0f} m" if self.radius_m else " (one pixel)"))
        if self.bbox is not None:
            return "box W {:.4f} S {:.4f} E {:.4f} N {:.4f}".format(*self.bbox)
        return "whole landscape"


def select(cube: Cube, area: Area | None = None, woodland_only: bool = True) -> np.ndarray:
    """Boolean (row, col) mask of the pixels in ``area`` (woodland only by default)."""
    lon, lat = cube.lonlat()
    mask = np.ones(cube.shape, dtype=bool)
    area = area or Area()
    if area.bbox is not None:
        w, s, e, n = area.bbox
        mask &= (lon >= w) & (lon <= e) & (lat >= s) & (lat <= n)
    if area.point is not None:
        plon, plat = area.point
        dx = (lon - plon) * 111_320.0 * math.cos(math.radians(plat))
        dy = (lat - plat) * 111_320.0
        dist = np.hypot(dx, dy)
        if area.radius_m > 0:
            mask &= dist <= area.radius_m
        else:
            nearest = np.zeros(cube.shape, dtype=bool)
            nearest[np.unravel_index(np.argmin(dist), dist.shape)] = True
            if dist.min() > 100.0:
                raise ValueError(f"point is outside the {cube.key} landscape")
            mask &= nearest
            return mask  # a single pixel is returned even if it is not woodland
    if woodland_only:
        mask &= cube.woodland
    if not mask.any():
        raise ValueError(f"no {'woodland ' if woodland_only else ''}pixels in "
                         f"{area.describe()} of {cube.key}")
    return mask


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #
def area_sd(pixel_sd: np.ndarray) -> float:
    """SD of an area-mean AGB from its pixels' SDs (correlated errors, see module doc)."""
    n = pixel_sd.size
    if n == 0:
        return float("nan")
    mean_sd = float(pixel_sd.mean())
    if n == 1:
        return mean_sd
    n_eff = max(1.0, n / CORRELATION_PIXELS)
    random_var = (1.0 - SYSTEMATIC_FRACTION ** 2) * float((pixel_sd ** 2).mean()) / n_eff
    return math.sqrt((SYSTEMATIC_FRACTION * mean_sd) ** 2 + random_var)


def area_stats(cube: Cube, year: int, mask: np.ndarray) -> dict:
    """Mean AGB, its SD and 90 % interval, area and spread for one year."""
    i = cube.year_index(year)
    a = cube.agb[i][mask]
    s = cube.sd[i][mask]
    area_ha = float(cube.pixel_area_ha()[mask].sum())
    mean = float(a.mean())
    sd = area_sd(s)
    return {"year": int(year), "agb_mean_mg_ha": mean, "agb_sd_mg_ha": sd,
            "agb_p05_mg_ha": mean - Z90 * sd, "agb_p95_mg_ha": mean + Z90 * sd,
            "pixel_sd_mean_mg_ha": float(s.mean()),
            "pixel_agb_p10_mg_ha": float(np.percentile(a, 10)),
            "pixel_agb_p90_mg_ha": float(np.percentile(a, 90)),
            "n_pixels": int(mask.sum()), "area_ha": area_ha,
            "agb_total_mg": mean * area_ha}


def crosses_epoch(year1: int, year2: int) -> bool:
    lo, hi = sorted((year1, year2))
    return lo <= EPOCH_BREAK[0] and hi >= EPOCH_BREAK[1]


def pixel_change(cube: Cube, year1: int, year2: int, mask: np.ndarray) -> dict:
    """Per-pixel AGB change with its SD, and which pixels changed significantly (90 %)."""
    i, j = cube.year_index(year1), cube.year_index(year2)
    d = cube.agb[j] - cube.agb[i]
    sd = np.sqrt(cube.sd[i] ** 2 + cube.sd[j] ** 2)
    sig = np.abs(d) > Z90 * np.maximum(sd, 1e-9)
    loss = mask & sig & (d < 0)
    gain = mask & sig & (d > 0)
    return {"delta": d, "sd": sd, "loss": loss, "gain": gain}


def stand_replacing_events(cube: Cube, mask: np.ndarray, years=None,
                           min_before: float = 50.0, min_drop_frac: float = 0.5) -> dict:
    """Find the last stand-replacing loss (clearfell, windthrow, fire) in each pixel.

    A year-to-year drop counts if the pixel held at least ``min_before`` Mg/ha, lost at
    least ``min_drop_frac`` of it, and the loss is significant at 90 % given both years' SD.
    Returns ``{"year": (row, col) int array, 0 = none}`` restricted to ``years`` if given.
    """
    yrs = list(cube.years if years is None else years)
    idx = [cube.year_index(y) for y in yrs]
    event = np.zeros(cube.shape, dtype=int)
    for a, b in zip(idx[:-1], idx[1:]):
        before, after = cube.agb[a], cube.agb[b]
        sd = np.sqrt(cube.sd[a] ** 2 + cube.sd[b] ** 2)
        drop = before - after
        hit = mask & (before >= min_before) & (drop >= min_drop_frac * before) & \
            (drop > Z90 * np.maximum(sd, 1e-9))
        event = np.where(hit, cube.years[b], event)
    return {"year": event}
