"""Pilot landscapes of the DT4 twin: where they are, what grows there, and their climate.

DT4 starts with two contrasting British forests:

* **Thetford** (Breckland, East Anglia): lowland pine on dry, poor sands, mostly Corsican and
  Scots pine in its second rotation. About 600 mm of rain a year.
* **Kielder** (Northumberland): upland Sitka spruce on peaty gleys, the largest planted forest
  in England, harvested by clearfelling. About 1,250 mm of rain a year.

Each landscape is a lon/lat window (EPSG:4326) around the forest core. The window is cut out
of the ESA Biomass CCI v7.0 tiles by ``scripts/extract_cci_pilots.py``.

Climate
-------
3-PG needs monthly climate. Each landscape's climate is the HadUK-Grid 1991-2020 monthly
average over its window, extracted by ``scripts/extract_haduk_climate.py`` from the Met Office
Climate Data Portal into ``data/haduk_<key>.json`` (Open Government Licence v3.0). Global
radiation, which HadUK-Grid lacks, is estimated from the diurnal temperature range
(Hargreaves-Samani) and monthly frost days from the annual air-frost count; see that script.

Solar radiation is global horizontal irradiation in MJ m-2 day-1, monthly means.
Available soil water capacity and soil texture class are a priori values for the dominant
soils (Breckland sands; Kielder peaty gleys).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


@dataclass(frozen=True)
class Climate:
    """Monthly climatology (12 values per field, January first)."""

    tmax_c: tuple[float, ...]
    tmin_c: tuple[float, ...]
    rain_mm: tuple[float, ...]
    solar_mj_m2_d: tuple[float, ...]
    frost_days: tuple[float, ...]
    source: str

    def __post_init__(self):
        for name in ("tmax_c", "tmin_c", "rain_mm", "solar_mj_m2_d", "frost_days"):
            if len(getattr(self, name)) != 12:
                raise ValueError(f"{name} needs 12 monthly values")

    @property
    def annual_rain_mm(self) -> float:
        return float(sum(self.rain_mm))

    @property
    def mean_temp_c(self) -> float:
        return float(sum((a + b) / 2 for a, b in zip(self.tmax_c, self.tmin_c)) / 12)


@dataclass(frozen=True)
class Landscape:
    key: str
    name: str
    description: str
    bbox: tuple[float, float, float, float]  # west, south, east, north (degrees, EPSG:4326)
    cci_tile: str                            # CCI 10x10 degree tile, named by its NW corner
    latitude: float                          # representative latitude for day length
    species: str                             # dominant species code (see forest.species)
    max_asw_mm: float                        # available soil water capacity of the root zone
    soil_class: str                          # 3-PG soil texture class: sand, sandy_loam, clay_loam, clay
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def climate(self) -> Climate:
        """HadUK-Grid 1991-2020 monthly climate of the landscape (from data/haduk_<key>.json)."""
        return load_climate(self.key)


def haduk_path(key: str) -> Path:
    return DATA_DIR / f"haduk_{key}.json"


@lru_cache(maxsize=16)
def load_climate(key: str) -> Climate:
    path = haduk_path(key)
    if not path.exists():
        raise FileNotFoundError(f"{path.name} is missing; run scripts/extract_haduk_climate.py")
    d = json.loads(path.read_text())
    return Climate(tmax_c=tuple(d["tmax_c"]), tmin_c=tuple(d["tmin_c"]), rain_mm=tuple(d["rain_mm"]),
                   solar_mj_m2_d=tuple(d["solar_mj_m2_d"]), frost_days=tuple(d["frost_days"]),
                   source=d["source"])


THETFORD = Landscape(
    key="thetford",
    name="Thetford Forest",
    description="Lowland Corsican and Scots pine on Breckland sands, East Anglia",
    bbox=(0.55, 52.38, 0.80, 52.52),
    cci_tile="N60E000",
    latitude=52.45,
    species="CP",
    max_asw_mm=90.0,
    soil_class="sand",
    notes=("Planted from the 1920s; now a mosaic of second-rotation stands of all ages.",
           "Corsican pine is the main timber species; Scots pine is the second."),
)

KIELDER = Landscape(
    key="kielder",
    name="Kielder Forest",
    description="Upland Sitka spruce on peaty gleys, Northumberland",
    bbox=(-2.70, 55.13, -2.35, 55.30),
    cci_tile="N60W010",
    latitude=55.22,
    species="SS",
    max_asw_mm=180.0,
    soil_class="clay_loam",
    notes=("Planted mostly 1926-1970s; clearfelled and restocked on a 40-60 year rotation.",
           "Sitka spruce covers about three quarters of the forest; lodgepole pine and Norway "
           "spruce make up most of the rest."),
)

LANDSCAPES: dict[str, Landscape] = {THETFORD.key: THETFORD, KIELDER.key: KIELDER}


def get(key: str) -> Landscape:
    try:
        return LANDSCAPES[key]
    except KeyError:
        raise ValueError(f"unknown landscape {key!r}; known: {sorted(LANDSCAPES)}") from None
