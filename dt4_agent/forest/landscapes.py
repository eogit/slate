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
3-PG needs monthly climate. Following the decision to calibrate on Biomass CCI v7 only,
DT4 does not download gridded climate. Each landscape carries a monthly 1991-2020 style
climatology typed in from nearby Met Office stations (Santon Downham for Thetford; Kielder
Castle and Redesdale for Kielder). The values are rounded approximations, good enough for a
growth model whose productivity is then calibrated to CCI, but they are not HadUK-Grid.
Replacing them with HadUK-Grid or UKCP18 is a later step.

Solar radiation is global horizontal irradiation in MJ m-2 day-1, monthly means.
Available soil water capacity and soil texture class are a priori values for the dominant
soils (Breckland sands; Kielder peaty gleys).
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    climate: Climate
    notes: tuple[str, ...] = field(default_factory=tuple)


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
    climate=Climate(
        tmax_c=(7.5, 8.2, 11.2, 14.3, 17.7, 20.7, 23.3, 23.1, 19.9, 15.2, 10.5, 7.9),
        tmin_c=(0.9, 0.8, 2.0, 3.7, 6.7, 9.7, 11.8, 11.6, 9.3, 6.8, 3.5, 1.3),
        rain_mm=(52, 40, 38, 40, 45, 52, 54, 58, 52, 61, 58, 54),
        solar_mj_m2_d=(2.7, 5.0, 8.9, 13.5, 17.0, 18.5, 18.0, 15.0, 10.8, 6.4, 3.3, 2.1),
        frost_days=(12, 12, 8, 5, 1, 0, 0, 0, 0, 2, 6, 11),
        source="Approximate 1991-2020 monthly climatology, Santon Downham area (rounded)",
    ),
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
    climate=Climate(
        tmax_c=(5.6, 6.0, 8.0, 10.9, 14.2, 16.8, 18.6, 18.2, 15.6, 11.9, 8.2, 5.8),
        tmin_c=(-0.5, -0.6, 0.4, 1.8, 4.2, 7.1, 9.0, 8.8, 6.9, 4.4, 1.7, -0.3),
        rain_mm=(140, 105, 100, 70, 70, 75, 85, 95, 95, 125, 140, 140),
        solar_mj_m2_d=(2.0, 4.0, 7.6, 12.0, 15.8, 16.5, 15.6, 13.0, 9.0, 5.0, 2.6, 1.5),
        frost_days=(15, 14, 12, 7, 2, 0, 0, 0, 0, 3, 9, 14),
        source="Approximate 1991-2020 monthly climatology, Kielder Castle and Redesdale (rounded)",
    ),
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
