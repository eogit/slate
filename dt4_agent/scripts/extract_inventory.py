"""Extract the forest inventory for the DT4 pilot landscapes onto the CCI v7 100 m grid.

Two open Forestry Commission datasets (Open Government Licence v3.0) are read from the
Forestry Commission open data ArcGIS services:

* **National Forest Inventory (NFI) woodland map GB 2024**: woodland and interpreted open-area
  polygons with their interpreted forest type (``IFT_IOA``: Conifer, Broadleaved, Mixed, Felled,
  Young trees, Windblow, ...). DT4 uses it as the woodland mask.
* **Forestry England sub-compartment database**: the stand records of the public forest estate,
  which covers most of Thetford and Kielder. Each sub-compartment has its main species
  (``spis``), planting year (``plyr``) and Forestry England's yield class (``yldc``).

The NFI field-plot data with tree species are not public, so species come from the
sub-compartment database; where a pixel has no sub-compartment, its species group is inferred
from the NFI forest type (see ``forest.inventory``).

Each polygon layer is rasterised onto the landscape's CCI grid (a pixel takes the polygon that
contains its centre) and saved as ``dt4_agent/forest/data/<landscape>_inventory.npz``. Needs
network access to services2.arcgis.com and ``rasterio``:

    pip install rasterio
    python dt4_agent/scripts/extract_inventory.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from forest import cci  # noqa: E402
from forest.inventory import inventory_path  # noqa: E402
from forest.landscapes import LANDSCAPES  # noqa: E402

FC = "https://services2.arcgis.com/mHXjwgl3OARRqqD4/arcgis/rest/services"
NFI = "National_Forest_Inventory_GB_2024"
FE = "Forestry_England_Subcompartments"
PAGE = 2000


def fetch(service: str, bbox, fields: str) -> list[dict]:
    """All features of a layer intersecting the bbox, as GeoJSON-like dicts in EPSG:4326."""
    out, offset = [], 0
    while True:
        params = {"where": "1=1", "geometry": ",".join(str(v) for v in bbox),
                  "geometryType": "esriGeometryEnvelope", "inSR": "4326", "outSR": "4326",
                  "spatialRel": "esriSpatialRelIntersects", "outFields": fields,
                  "returnGeometry": "true", "f": "json", "resultOffset": offset,
                  "resultRecordCount": PAGE, "orderByFields": "OBJECTID" if service == FE else "FID"}
        url = f"{FC}/{service}/FeatureServer/0/query?" + urllib.parse.urlencode(params)
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=180) as r:
                    data = json.load(r)
                break
            except OSError:
                time.sleep(2 ** attempt)
        else:
            raise RuntimeError(f"could not fetch {service} at offset {offset}")
        if "error" in data:
            raise RuntimeError(f"{service}: {data['error']}")
        for f in data["features"]:
            rings = (f.get("geometry") or {}).get("rings")
            if rings:
                out.append({"geometry": {"type": "Polygon", "coordinates": rings},
                            "attributes": f["attributes"]})
        if not data.get("exceededTransferLimit") and len(data["features"]) < PAGE:
            return out
        offset += len(data["features"])


def _rasterize(features, values, shape, transform):
    from rasterio.features import rasterize
    from rasterio.transform import Affine

    shapes = [(f["geometry"], int(v)) for f, v in zip(features, values) if v is not None]
    if not shapes:
        return np.zeros(shape, dtype=np.int32)
    return rasterize(shapes, out_shape=shape, transform=Affine(*transform), fill=0,
                     dtype="int32", all_touched=False)


def extract(key: str) -> Path:
    ls = LANDSCAPES[key]
    cube = cci.load(key)
    shape, tr = cube.shape, cube.transform

    nfi = fetch(NFI, ls.bbox, "IFT_IOA,CATEGORY")
    ift_names = sorted({f["attributes"]["IFT_IOA"] or "Unknown" for f in nfi})
    ift = _rasterize(nfi, [ift_names.index(f["attributes"]["IFT_IOA"] or "Unknown") + 1 for f in nfi],
                     shape, tr)
    wood = _rasterize(nfi, [1 if f["attributes"]["CATEGORY"] == "Woodland" else 2 for f in nfi],
                      shape, tr)

    fe = fetch(FE, ls.bbox, "spis,plyr,yldc,luse")
    sp_names = sorted({f["attributes"]["spis"] for f in fe if f["attributes"]["spis"]})
    spis = _rasterize(fe, [sp_names.index(f["attributes"]["spis"]) + 1 if f["attributes"]["spis"] else None
                           for f in fe], shape, tr)
    plyr = _rasterize(fe, [f["attributes"]["plyr"] or None for f in fe], shape, tr)
    yldc = _rasterize(fe, [f["attributes"]["yldc"] or None for f in fe], shape, tr)
    in_fe = _rasterize(fe, [1 for _ in fe], shape, tr)

    out = inventory_path(key)
    np.savez_compressed(
        out,
        nfi_ift=ift.astype(np.int16),                  # 0 = outside NFI polygons, else index+1
        nfi_ift_names=np.array(ift_names),
        nfi_woodland=(wood == 1),
        fe_present=(in_fe == 1),                       # inside a Forestry England sub-compartment
        fe_species=spis.astype(np.int16),              # 0 = none recorded, else index+1
        fe_species_names=np.array(sp_names),
        fe_planting_year=plyr.astype(np.int16),        # 0 = none
        fe_yield_class=yldc.astype(np.int16),          # 0 = none
        transform=np.array(tr, dtype=np.float64),
        source=np.array(f"{FC}/{NFI} and {FC}/{FE}"),
        n_features=np.array([len(nfi), len(fe)]),
    )
    print(f"{key}: {len(nfi)} NFI polygons, {len(fe)} sub-compartments -> {out.name}")
    return out


def main() -> None:
    for key in sorted(LANDSCAPES):
        extract(key)


if __name__ == "__main__":
    main()
