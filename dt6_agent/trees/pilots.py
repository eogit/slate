"""Pilot areas of the DT6 twin: ten 5 km Ordnance Survey tiles across England's landscapes.

Each pilot is one 5 x 5 km OS National Grid tile (EPSG:27700). The tiles were chosen to span
England's regions and farmed, wetland, upland-fringe and urban landscapes, and every one has
at least one Environment Agency lidar survey from before the National LIDAR Programme (NLP),
so tree heights can be compared over 5 to 20 years. Three tiles (fens, leicestershire,
oxford) were also flown twice by the NLP itself.

The Trees Outside Woodland (TOW) map and the open lidar cover England only, so all pilots are
English (``region`` is the TOW map's regional collection).

Leaf type. No open dataset says whether a tree outside woodland is broadleaved or conifer.
``p_conifer`` is an a priori share per pilot: 8 % by default (England's non-woodland trees are
overwhelmingly broadleaved), 35 % in Breckland, whose Scots pine rows and shelterbelts are a
defining feature, and 15 % in the Tyne valley.

Climate: the HadUK-Grid 1991-2020 monthly average over the tile, from the Met Office Climate
Data Portal, extracted by ``scripts/extract_pilots.py`` into ``data/haduk_<key>.json`` exactly
as DT4 does (radiation from the diurnal temperature range, Hargreaves-Samani).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
TILE_M = 5000.0
_LETTERS = {"TL": (5, 2), "SX": (2, 0), "ST": (3, 1), "SO": (3, 2), "SK": (4, 3), "SE": (4, 4),
            "SJ": (3, 3), "SP": (4, 2), "NY": (3, 5)}


@dataclass(frozen=True)
class Climate:
    """Monthly climatology (12 values per field, January first)."""

    tmax_c: tuple[float, ...]
    tmin_c: tuple[float, ...]
    rain_mm: tuple[float, ...]
    solar_mj_m2_d: tuple[float, ...]
    frost_days: tuple[float, ...]
    source: str

    @property
    def annual_rain_mm(self) -> float:
        return float(sum(self.rain_mm))

    @property
    def mean_temp_c(self) -> float:
        return float(sum((a + b) / 2 for a, b in zip(self.tmax_c, self.tmin_c)) / 12)


@dataclass(frozen=True)
class Pilot:
    key: str
    name: str
    region: str                 # TOW map regional collection
    landscape: str
    tile: str                   # 5 km OS tile, named by its south-west 1 km square
    lon: float                  # tile centre (WGS84)
    lat: float
    bbox_wsen: tuple[float, float, float, float]
    p_conifer: float = 0.08     # a priori share of conifer crowns (no open leaf-type data)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def origin(self) -> tuple[float, float]:
        """South-west corner of the tile in British National Grid metres."""
        e, n = _LETTERS[self.tile[:2]]
        return (e * 100000 + int(self.tile[2:4]) * 1000, n * 100000 + int(self.tile[4:6]) * 1000)

    @property
    def bbox_bng(self) -> tuple[float, float, float, float]:
        x, y = self.origin
        return (x, y, x + TILE_M, y + TILE_M)

    @property
    def climate(self) -> Climate:
        return load_climate(self.key)


def haduk_path(key: str) -> Path:
    return DATA_DIR / f"haduk_{key}.json"


@lru_cache(maxsize=32)
def load_climate(key: str) -> Climate:
    path = haduk_path(key)
    if not path.exists():
        raise FileNotFoundError(f"{path.name} is missing; run scripts/extract_pilots.py")
    d = json.loads(path.read_text())
    return Climate(tmax_c=tuple(d["tmax_c"]), tmin_c=tuple(d["tmin_c"]), rain_mm=tuple(d["rain_mm"]),
                   solar_mj_m2_d=tuple(d["solar_mj_m2_d"]), frost_days=tuple(d["frost_days"]),
                   source=d["source"])


PILOTS: dict[str, Pilot] = {p.key: p for p in (
    Pilot("breckland", "Breckland farmland", "Eastern",
          "Dry arable Brecks beside Thetford Forest: Scots pine rows, shelterbelts, field trees",
          "TL7580", 0.6083, 52.4117, (0.5703, 52.3901, 0.6464, 52.4333), 0.35,
          ("Shares its edge with DT4's Thetford window: tests the DT4/DT6 boundary.",)),
    Pilot("fens", "Cambridgeshire Fens", "Eastern",
          "Open fen arable along the Great Ouse washes: willows, poplars, farmstead trees",
          "TL4075", 0.0920, 52.3770, (0.0542, 52.3552, 0.1298, 52.3988),
          notes=("Flown twice by the NLP (2019 and 2021).",)),
    Pilot("mid_devon", "Exe valley, mid-Devon", "South_West",
          "Pastoral Devon with hedgebanks, field oaks and riparian trees", "SX9095",
          -3.5257, 50.7671, (-3.5604, 50.7442, -3.4910, 50.7900)),
    Pilot("somerset_levels", "Somerset Levels", "South_West",
          "Grazing marsh and rhynes: pollard willows and lines of trees", "ST3535",
          -2.8946, 51.1333, (-2.9299, 51.1106, -2.8593, 51.1561)),
    Pilot("herefordshire", "Wye valley, Herefordshire", "West_Midlands",
          "Mixed farming in the Welsh Marches: orchards, field and hedgerow oaks", "SO5040",
          -2.6945, 52.0788, (-2.7306, 52.0561, -2.6584, 52.1015)),
    Pilot("leicestershire", "Soar valley, Leicestershire", "East_Midlands",
          "Urban fringe of Leicester and Midlands clay farmland", "SK6005",
          -1.0774, 52.6616, (-1.1148, 52.6394, -1.0399, 52.6838),
          notes=("Flown twice by the NLP (2018 and 2022).",)),
    Pilot("vale_of_york", "Vale of York", "Yorkshire_and_Humber",
          "Flat arable and Derwent floodplain: hedgerow trees and farm copses", "SE6045",
          -1.0499, 53.9199, (-1.0884, 53.8977, -1.0113, 53.9420)),
    Pilot("cheshire", "Cheshire plain near Chester", "North_West",
          "Dairy pasture with marl pits and many field oaks", "SJ4065",
          -2.8623, 53.2014, (-2.8992, 53.1787, -2.8253, 53.2242)),
    Pilot("oxford", "Oxford and the Thames", "South_East",
          "City, parks and colleges, and Thames floodplain meadows", "SP5005",
          -1.2407, 51.7637, (-1.2773, 51.7415, -1.2041, 51.7860),
          notes=("Urban pilot; flown twice by the NLP (2020 and 2023).",)),
    Pilot("tyne_valley", "Tyne valley near Hexham", "North_East",
          "Upland-fringe pasture: riparian alders, field ash and sycamore", "NY9065",
          -2.1188, 55.0020, (-2.1578, 54.9795, -2.0797, 55.0245), 0.15),
)}


def get(key: str) -> Pilot:
    try:
        return PILOTS[key]
    except KeyError:
        raise ValueError(f"unknown pilot {key!r}; known: {sorted(PILOTS)}") from None
