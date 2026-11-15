"""Rasterise the Living England habitat map (Phase 4) onto DT2's 1 km British National Grid.

Living England (Natural England, Open Government Licence) is a satellite-derived broad
habitat map of England: about 6.9 million segments, each labelled with one of ~17 habitat
classes (``A_pred``) and a model probability (``A_prob``). DT2 uses it as the ancillary
grassland map: where the grass is, and whether it is improved or semi-natural.

The segments are read from Natural England's public ArcGIS feature service without geometry,
only their centroid, class and area, 2,000 at a time in OBJECTID order. Each segment's area is
added to the 1 km cell that contains its centroid. Segments are 0.5-3 ha, so assigning whole
segments by centroid moves at most a few per cent of a cell's area across its edges.

Output: ``livestock/data/living_england_1km.npz`` with one float32 array per class (hectares
in each 1 km cell; at most 100) on the grid in ``livestock/grid.py``.

    python dt2_agent/scripts/extract_living_england.py            # about 10 minutes
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from livestock.grid import GRID  # noqa: E402

SERVICE = ("https://services.arcgis.com/JJzESW51TqeY9uat/arcgis/rest/services/"
           "Living_England_Habitat_Map_Phase4/FeatureServer/0/query")
PAGE = 2000
OUT = HERE.parent / "livestock" / "data" / "living_england_1km.npz"


def _get(lo: int, hi: int, tries: int = 6) -> list[dict]:
    q = urllib.parse.urlencode({
        "where": f"OBJECTID>{lo} AND OBJECTID<={hi}", "outFields": "A_pred,Shape__Area",
        "returnGeometry": "false", "returnCentroid": "true", "outSR": "27700",
        "resultRecordCount": PAGE, "f": "json"})
    for k in range(tries):
        try:
            with urllib.request.urlopen(SERVICE + "?" + q, timeout=120) as r:
                d = json.load(r)
            if "features" in d:
                return d["features"]
        except Exception:  # network hiccup: back off and retry
            pass
        time.sleep(2 ** k)
    raise RuntimeError(f"page {lo}-{hi} failed")


def main(n_max: int = 6_905_076, workers: int = 8) -> None:
    layers: dict[str, np.ndarray] = {}
    ny, nx = GRID.shape
    pages = [(lo, lo + PAGE) for lo in range(0, n_max, PAGE)]
    done = 0
    with ThreadPoolExecutor(workers) as ex:
        for feats in ex.map(lambda p: _get(*p), pages):
            for f in feats:
                c = f.get("centroid")
                if not c:
                    continue
                cls = f["attributes"]["A_pred"] or "Unclassified"
                i, j = GRID.index(c["x"], c["y"])
                if 0 <= i < ny and 0 <= j < nx:
                    if cls not in layers:
                        layers[cls] = np.zeros(GRID.shape, np.float32)
                    layers[cls][i, j] += f["attributes"]["Shape__Area"] / 1e4
            done += 1
            if done % 200 == 0:
                print(f"{done}/{len(pages)} pages", flush=True)
    np.savez_compressed(OUT, classes=np.array(sorted(layers)),
                        ha=np.stack([layers[k] for k in sorted(layers)]))
    print("wrote", OUT, sorted(layers))


if __name__ == "__main__":
    main()
