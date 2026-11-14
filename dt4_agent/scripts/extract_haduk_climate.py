"""Extract HadUK-Grid 1991-2020 monthly climate for the DT4 pilot landscapes.

Source: the Met Office Climate Data Portal, which serves HadUK-Grid long-term averages as open
ArcGIS feature services (Open Government Licence v3.0). The script queries every grid cell
that intersects a landscape's window and averages them:

* mean temperature (``tas``), rainfall and annual air-frost days: HadUK-Grid on the portal's
  fine grid (about 2 km);
* maximum and minimum temperature: HadUK-Grid 12 km. They are shifted so their midpoint equals
  the fine-grid mean temperature, which keeps the 12 km diurnal range and the fine-grid level.

HadUK-Grid has no radiation, so global radiation is estimated from the diurnal temperature
range with Hargreaves & Samani (1985), Rs = kRs * sqrt(Tmax - Tmin) * Ra, kRs = 0.16 (inland),
Ra = extraterrestrial radiation at the landscape's latitude (FAO-56 eq. 21). Monthly frost days
spread the annual air-frost count over the months in proportion to the chance that a day's
minimum falls below 0 C, taking daily minima as normal around the monthly mean minimum with a
3 C standard deviation.

Writes ``dt4_agent/forest/data/haduk_<landscape>.json``. Needs network access to
services.arcgis.com; the server only reads the JSON.

    python dt4_agent/scripts/extract_haduk_climate.py

The full HadUK-Grid (1 km, monthly series for each year, sunshine) is on CEDA and needs a CEDA
login; this script uses the portal so it runs without credentials.
"""

from __future__ import annotations

import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from forest.landscapes import DAYS_IN_MONTH, LANDSCAPES, haduk_path  # noqa: E402

PORTAL = "https://services.arcgis.com/Lq3V5RFuTBC9I7kv/ArcGIS/rest/services"
LAYERS = {  # field prefix: (service, layer id)
    "tas": ("Monthly_Temperature_Observations_1991_2020", 0),
    "pr": ("Monthly_Precipitation_Observations_1991_2020", 0),
    "tmax": ("Monthly_Max_Temperature_Observations_1991_2020", 8),
    "tmin": ("Monthly_Min_Temperature_Observations_1991_2020", 6),
    "airfrost": ("Annual_Count_of_Airfrost_Days_1991_2020", 0),
}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
KRS = 0.16
DAILY_TMIN_SD = 3.0


def query(service: str, layer: int, bbox) -> list[dict]:
    params = {"where": "1=1", "geometry": ",".join(str(v) for v in bbox),
              "geometryType": "esriGeometryEnvelope", "inSR": "4326",
              "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
              "returnGeometry": "false", "f": "json"}
    url = f"{PORTAL}/{service}/FeatureServer/{layer}/query?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=120) as r:
        data = json.load(r)
    if "error" in data:
        raise RuntimeError(f"{service}: {data['error']}")
    return [f["attributes"] for f in data["features"]]


def extraterrestrial_mj(lat_deg: float, month: int) -> float:
    """Mean daily extraterrestrial radiation (MJ m-2 d-1) mid-month, FAO-56 eq. 21."""
    doy = [15, 46, 75, 105, 135, 162, 198, 228, 258, 288, 318, 344][month]
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)
    dec = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(dec))))
    return 24 * 60 / math.pi * 0.0820 * dr * (
        ws * math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.sin(ws))


def frost_days(tmin, annual_total):
    p = [0.5 * (1 + math.erf((0 - t) / (DAILY_TMIN_SD * math.sqrt(2)))) for t in tmin]
    raw = [pi * d for pi, d in zip(p, DAYS_IN_MONTH)]
    scale = annual_total / sum(raw) if sum(raw) > 0 else 0.0
    return [min(r * scale, d) for r, d in zip(raw, DAYS_IN_MONTH)]


def extract(key: str) -> dict:
    ls = LANDSCAPES[key]
    rows = {k: query(svc, lid, ls.bbox) for k, (svc, lid) in LAYERS.items()}

    def monthly(prefix):
        cells = rows[prefix]
        return [sum(c[f"{prefix}{m}"] for c in cells) / len(cells) for m in MONTHS]

    tas, pr = monthly("tas"), monthly("pr")
    tmax12, tmin12 = monthly("tmax"), monthly("tmin")
    shift = [t - (a + b) / 2 for t, a, b in zip(tas, tmax12, tmin12)]
    tmax = [a + s for a, s in zip(tmax12, shift)]
    tmin = [b + s for b, s in zip(tmin12, shift)]
    rad = [KRS * math.sqrt(max(a - b, 0.0)) * extraterrestrial_mj(ls.latitude, m)
           for m, (a, b) in enumerate(zip(tmax, tmin))]
    af = sum(c["airfrostDays"] for c in rows["airfrost"]) / len(rows["airfrost"])
    r3 = lambda xs: [round(x, 3) for x in xs]  # noqa: E731
    return {
        "landscape": key,
        "period": "1991-2020",
        "tmax_c": r3(tmax), "tmin_c": r3(tmin), "tas_c": r3(tas), "rain_mm": r3(pr),
        "solar_mj_m2_d": r3(rad), "frost_days": r3(frost_days(tmin, af)),
        "annual_airfrost_days": round(af, 3),
        "cells": {k: len(v) for k, v in rows.items()},
        "source": ("HadUK-Grid 1991-2020 monthly averages via the Met Office Climate Data Portal "
                   "(tas, rainfall, air frost on the ~2 km grid; Tmax/Tmin 12 km shifted to the "
                   "~2 km mean); radiation from Hargreaves-Samani (kRs 0.16); monthly frost days "
                   "from the annual air-frost count"),
        "licence": "Contains Met Office data licensed under the Open Government Licence v3.0",
        "portal": PORTAL,
    }


def main() -> None:
    for key in sorted(LANDSCAPES):
        out = extract(key)
        haduk_path(key).write_text(json.dumps(out, indent=1) + "\n")
        print("wrote", haduk_path(key), out["cells"])


if __name__ == "__main__":
    main()
