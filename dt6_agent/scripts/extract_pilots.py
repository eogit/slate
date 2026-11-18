"""Extract the DT6 pilot data: TOW crowns, their lidar heights over time, and climate.

For each pilot tile (``trees.pilots``) this script

1. reads every feature of the **National Trees Outside Woodland map** (Forest Research 2025,
   OGL v3) in the tile from its OGC API Features service. Features labelled "NFI OHC"
   (canopy overhanging NFI woodland, which the TOW report says is not strictly TOW) are
   dropped: they belong to DT4;
2. downloads Environment Agency lidar (OGL) for the tile from the EA survey download service:
   the latest National LIDAR Programme (NLP) first-return DSM and DTM, the NLP last-return
   DSM of every NLP year, and up to ``MAX_OLD_EPOCHS`` earlier "LIDAR Tiles" DSMs (the
   oldest and the most recent survey before the NLP, 1 m or 2 m). All are put on one 1 m grid
   (finer data take the maximum of each metre, 2 m data are repeated);
3. measures, for every TOW object: the first-return canopy height (maximum of first-return
   DSM minus DTM), the number of tree tops (local maxima at least 5 m apart), crown area,
   and for every epoch the last-return height (maximum of that epoch's DSM minus the NLP DTM)
   with the fraction of the object covered and the flight date. Old EA surveys only offer
   last-return DSMs, so growth is always measured last-return against last-return;
4. extracts the HadUK-Grid 1991-2020 monthly climate of the tile, as DT4 does.

The NLP DTM is used as the ground for every epoch: farmland ground does not move in 20 years,
and one ground removes the interpolation differences between old and new terrain models.

Writes ``dt6_agent/trees/data/<pilot>_crowns.npz`` and ``haduk_<pilot>.json``. Downloads
about 0.2-0.5 GB per pilot (deleted after use). Needs network access to
environment.data.gov.uk and services.arcgis.com, plus ``rasterio``, ``scipy`` and ``pyproj``:

    pip install rasterio scipy pyproj
    python dt6_agent/scripts/extract_pilots.py [pilot ...]
"""

from __future__ import annotations

import io
import json
import math
import re
import shutil
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import warnings

import numpy as np

warnings.filterwarnings("ignore", category=RuntimeWarning)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from trees import pilots as P  # noqa: E402

TOW = ("https://environment.data.gov.uk/spatialdata/national-trees-outside-woodland-map/ogc/"
       "features/v1/collections/FR_TOW_V1_{region}/items")
SEARCH = "https://environment.data.gov.uk/backend/catalog/api/tiles/collections/survey/search"
TILE_URL = "https://environment.data.gov.uk/tiles/collections/survey/{product}/{year}/{res}/{tile}"
CRS27700 = "http://www.opengis.net/def/crs/EPSG/0/27700"
MAX_OLD_EPOCHS = 2
MIN_COVER = 0.8          # share of an object's pixels an epoch must cover to count
MAX_PLAUSIBLE_M = 45.0   # heights above this are birds, wires or artefacts
TOP_WINDOW_M = 5         # tree tops: local maxima in a 5 m window
CLASSES = ("Lone Tree", "Group of Trees", "Small Woodland")

# HadUK-Grid portal (same services and method as DT4's extract_haduk_climate.py)
PORTAL = "https://services.arcgis.com/Lq3V5RFuTBC9I7kv/ArcGIS/rest/services"
LAYERS = {"tas": ("Monthly_Temperature_Observations_1991_2020", 0),
          "pr": ("Monthly_Precipitation_Observations_1991_2020", 0),
          "tmax": ("Monthly_Max_Temperature_Observations_1991_2020", 8),
          "tmin": ("Monthly_Min_Temperature_Observations_1991_2020", 6),
          "airfrost": ("Annual_Count_of_Airfrost_Days_1991_2020", 0)}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _get(url, data=None, headers=None, timeout=600):
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, data=data, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except OSError:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"could not fetch {url}")


# --------------------------------------------------------------------------- #
# TOW map
# --------------------------------------------------------------------------- #
def fetch_tow(pilot) -> list[dict]:
    x0, y0, x1, y1 = pilot.bbox_bng
    url = TOW.format(region=pilot.region) + "?" + urllib.parse.urlencode({
        "f": "json", "limit": 10000, "bbox": f"{x0},{y0},{x1},{y1}", "bbox-crs": CRS27700,
        "crs": CRS27700})
    feats = []
    while url:
        d = json.loads(_get(url))
        feats += d["features"]
        url = next((l["href"] for l in d.get("links", []) if l.get("rel") == "next"), None)
    return [f for f in feats if f["properties"]["woodland_type"] in CLASSES]


# --------------------------------------------------------------------------- #
# lidar
# --------------------------------------------------------------------------- #
def catalogue(pilot) -> list[dict]:
    w, s, e, n = pilot.bbox_wsen
    dx, dy = 0.15 * (e - w), 0.15 * (n - s)    # inset, so neighbouring tiles barely touch it
    poly = {"type": "Polygon", "coordinates": [[[w + dx, s + dy], [e - dx, s + dy], [e - dx, n - dy],
                                                 [w + dx, n - dy], [w + dx, s + dy]]]}
    r = json.loads(_get(SEARCH, json.dumps(poly).encode(), {"Content-Type": "application/geo+json"}))
    return [x for x in r["results"] if x["tile"]["id"] == pilot.tile]


def choose_epochs(cat) -> dict:
    nlp = sorted({int(x["year"]["id"]) for x in cat if x["product"]["id"] == "national_lidar_programme_dsm"})
    old = {}
    for x in cat:
        if x["product"]["id"] == "lidar_tiles_dsm" and x["resolution"]["id"] in ("1", "2"):
            y = int(x["year"]["id"])
            if y < nlp[0]:
                old[y] = min(old.get(y, "2"), x["resolution"]["id"])
    years = sorted(old)
    pick = sorted({years[0], years[-1]})[:MAX_OLD_EPOCHS] if years else []
    return {"nlp": nlp, "old": [(y, old[y]) for y in pick]}


def _download(product, year, res, tile, workdir: Path) -> list[Path]:
    blob = _get(TILE_URL.format(product=product, year=year, res=res, tile=tile))
    out = workdir / f"{product}_{year}"
    out.mkdir(exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".tif")]
        z.extractall(out, members=names)
    return [out / n for n in names]


def _date_of(name: str) -> float:
    m = re.findall(r"(\d{8})", name)
    d = m[-2] if len(m) >= 2 else m[-1]
    y, mo, da = int(d[:4]), int(d[4:6]), int(d[6:8])
    return y + (mo - 1) / 12 + (da - 1) / 365


def _to_grid(paths, origin, kind_filter=None):
    """Mosaic GeoTIFFs onto the tile's 1 m grid (max of finer cells). Returns value, date."""
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject

    n = int(P.TILE_M)
    x0, y0 = origin
    dst_tr = from_origin(x0, y0 + P.TILE_M, 1.0, 1.0)
    val = np.full((n, n), np.nan, dtype=np.float32)
    date = np.full((n, n), np.nan, dtype=np.float32)
    for p in paths:
        if kind_filter and not re.match(kind_filter, p.name):
            continue
        with rasterio.open(p) as src:
            tmp = np.full((n, n), np.nan, dtype=np.float32)
            res = abs(src.transform.a)
            reproject(source=rasterio.band(src, 1), destination=tmp, src_transform=src.transform,
                      src_crs=src.crs or "EPSG:27700", src_nodata=src.nodata, dst_transform=dst_tr,
                      dst_crs="EPSG:27700", dst_nodata=np.nan,
                      resampling=Resampling.max if res < 1 else Resampling.nearest)
        new = np.isfinite(tmp) & ~np.isfinite(val)
        val = np.where(new, tmp, np.fmax(val, tmp))
        date = np.where(new, _date_of(p.name), date)
    return val, date


# --------------------------------------------------------------------------- #
# per-object statistics
# --------------------------------------------------------------------------- #
def _labels(feats, origin):
    from rasterio.features import rasterize
    from rasterio.transform import from_origin

    n = int(P.TILE_M)
    tr = from_origin(origin[0], origin[1] + P.TILE_M, 1.0, 1.0)
    shapes = [(f["geometry"], i + 1) for i, f in enumerate(feats)]
    return rasterize(shapes, out_shape=(n, n), transform=tr, fill=0, dtype="int32", all_touched=False)


def _stats(values, labels, idx):
    from scipy import ndimage

    ok = np.isfinite(values) & (values < MAX_PLAUSIBLE_M)
    v = np.where(ok, values, -np.inf)
    mx = ndimage.maximum(v, labels, idx)
    npx = ndimage.sum(np.ones_like(labels, dtype=np.float32), labels, idx)
    cover = ndimage.sum(ok.astype(np.float32), labels, idx) / np.maximum(npx, 1)
    mx = np.where((cover >= MIN_COVER) & np.isfinite(mx), mx, np.nan)
    return np.asarray(mx, dtype=np.float32), np.asarray(cover, dtype=np.float32)


def extract(key: str) -> Path:
    from pyproj import Transformer
    from scipy import ndimage

    pilot = P.get(key)
    feats = fetch_tow(pilot)
    cat = catalogue(pilot)
    ep = choose_epochs(cat)
    work = Path(tempfile.mkdtemp(prefix=f"dt6_{key}_"))
    try:
        latest = ep["nlp"][-1]
        dtm, _ = _to_grid(_download("national_lidar_programme_dtm", latest, 1, pilot.tile, work), pilot.origin)
        fz, fz_date = _to_grid(_download("national_lidar_programme_first_return_dsm", latest, 1,
                                         pilot.tile, work), pilot.origin)
        labels = _labels(feats, pilot.origin)
        idx = np.arange(1, len(feats) + 1)
        chm_fz = fz - dtm
        h_fz, cover_fz = _stats(chm_fz, labels, idx)
        smooth = ndimage.uniform_filter(np.nan_to_num(chm_fz, nan=0.0), 3)
        tops = (smooth == ndimage.maximum_filter(smooth, TOP_WINDOW_M)) & (smooth > 3.0) & (labels > 0)
        n_tops = ndimage.sum(tops.astype(np.float32), labels, idx).astype(np.int32)
        area = ndimage.sum(np.ones_like(labels, dtype=np.float32), labels, idx).astype(np.float32)
        fz_dates = ndimage.mean(np.nan_to_num(fz_date, nan=latest + 0.5), labels, idx)
        del fz, smooth, tops

        epochs = [(y, "lidar_tiles_dsm", r) for y, r in ep["old"]] + \
                 [(y, "national_lidar_programme_dsm", 1) for y in ep["nlp"]]
        h_lz, cov_lz, dates = [], [], []
        for y, prod, res in epochs:
            paths = _download(prod, y, res, pilot.tile, work)
            dsm, d = _to_grid(paths, pilot.origin, kind_filter=r"^DSM")
            h, c = _stats(dsm - dtm, labels, idx)
            dd = ndimage.mean(np.nan_to_num(d, nan=y + 0.5), labels, idx)
            h_lz.append(h)
            cov_lz.append(c)
            dates.append(np.where(np.isfinite(h), dd, np.nan).astype(np.float32))
            shutil.rmtree(work / f"{prod}_{y}", ignore_errors=True)
            print(f"  {key} epoch {y} ({prod}): {np.isfinite(h).sum()} of {len(h)} objects covered", flush=True)

        tr = Transformer.from_crs(27700, 4326, always_xy=True)
        cx = np.array([np.mean(np.array(_ring(f))[:, 0]) for f in feats])
        cy = np.array([np.mean(np.array(_ring(f))[:, 1]) for f in feats])
        lon, lat = tr.transform(cx, cy)
        props = [f["properties"] for f in feats]
        out = P.DATA_DIR / f"{key}_crowns.npz"
        np.savez_compressed(
            out,
            tow_id=np.array([p["tow_id"] for p in props]),
            tow_class=np.array([CLASSES.index(p["woodland_type"]) for p in props], dtype=np.int8),
            tow_area_m2=np.array([p["tow_area_m"] for p in props], dtype=np.float32),
            tow_maxht=np.array([p["maxht"] or np.nan for p in props], dtype=np.float32),
            tow_survey_year=np.array([p["lidar_survey_year"] or 0 for p in props], dtype=np.int16),
            x=cx.astype(np.float32), y=cy.astype(np.float32),
            lon=np.asarray(lon, dtype=np.float32), lat=np.asarray(lat, dtype=np.float32),
            area_m2=area, n_tops=n_tops, h_fz=h_fz, cover_fz=cover_fz,
            fz_date=np.asarray(fz_dates, dtype=np.float32),
            epoch_year=np.array([e[0] for e in epochs], dtype=np.int16),
            epoch_product=np.array([e[1] for e in epochs]),
            h_lz=np.stack(h_lz, 1), cover_lz=np.stack(cov_lz, 1), date_lz=np.stack(dates, 1),
            tile=np.array(pilot.tile), source=np.array(f"{TOW} ; {TILE_URL}"),
        )
        print(f"{key}: {len(feats)} TOW objects, epochs {[e[0] for e in epochs]} -> {out.name}", flush=True)
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _ring(f):
    g = f["geometry"]
    c = g["coordinates"]
    return c[0][0] if g["type"] == "MultiPolygon" else c[0]


# --------------------------------------------------------------------------- #
# climate
# --------------------------------------------------------------------------- #
def _query(service, layer, bbox):
    params = {"where": "1=1", "geometry": ",".join(str(v) for v in bbox),
              "geometryType": "esriGeometryEnvelope", "inSR": "4326",
              "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
              "returnGeometry": "false", "f": "json"}
    d = json.loads(_get(f"{PORTAL}/{service}/FeatureServer/{layer}/query?" + urllib.parse.urlencode(params)))
    if "error" in d:
        raise RuntimeError(f"{service}: {d['error']}")
    return [f["attributes"] for f in d["features"]]


def _ra(lat, month):
    doy = [15, 46, 75, 105, 135, 162, 198, 228, 258, 288, 318, 344][month]
    phi = math.radians(lat)
    dr = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)
    dec = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(dec))))
    return 24 * 60 / math.pi * 0.0820 * dr * (ws * math.sin(phi) * math.sin(dec) +
                                              math.cos(phi) * math.cos(dec) * math.sin(ws))


def climate(key: str) -> dict:
    pilot = P.get(key)
    w, s, e, n = pilot.bbox_wsen
    bbox = (w - 0.02, s - 0.02, e + 0.02, n + 0.02)   # make sure 12 km cells are hit
    rows = {k: _query(svc, lid, bbox) for k, (svc, lid) in LAYERS.items()}
    mon = lambda p: [sum(c[f"{p}{m}"] for c in rows[p]) / len(rows[p]) for m in MONTHS]  # noqa: E731
    tas, pr, tx, tn = mon("tas"), mon("pr"), mon("tmax"), mon("tmin")
    shift = [t - (a + b) / 2 for t, a, b in zip(tas, tx, tn)]
    tmax = [a + s for a, s in zip(tx, shift)]
    tmin = [b + s for b, s in zip(tn, shift)]
    rad = [0.16 * math.sqrt(max(a - b, 0)) * _ra(pilot.lat, m) for m, (a, b) in enumerate(zip(tmax, tmin))]
    af = sum(c["airfrostDays"] for c in rows["airfrost"]) / len(rows["airfrost"])
    p = [0.5 * (1 + math.erf(-t / (3.0 * math.sqrt(2)))) for t in tmin]
    raw = [pi * d for pi, d in zip(p, DAYS)]
    fd = [min(r * af / sum(raw), d) if sum(raw) else 0.0 for r, d in zip(raw, DAYS)]
    r3 = lambda xs: [round(x, 3) for x in xs]  # noqa: E731
    return {"pilot": key, "period": "1991-2020", "tmax_c": r3(tmax), "tmin_c": r3(tmin),
            "tas_c": r3(tas), "rain_mm": r3(pr), "solar_mj_m2_d": r3(rad), "frost_days": r3(fd),
            "annual_airfrost_days": round(af, 3), "cells": {k: len(v) for k, v in rows.items()},
            "source": ("HadUK-Grid 1991-2020 monthly averages via the Met Office Climate Data "
                       "Portal (tas, rainfall, air frost ~2 km; Tmax/Tmin 12 km shifted to the "
                       "~2 km mean); radiation from Hargreaves-Samani (kRs 0.16)"),
            "licence": "Contains Met Office data licensed under the Open Government Licence v3.0"}


def main() -> None:
    keys = sys.argv[1:] or sorted(P.PILOTS)
    for key in keys:
        P.haduk_path(key).write_text(json.dumps(climate(key), indent=1) + "\n")
        extract(key)


if __name__ == "__main__":
    main()
