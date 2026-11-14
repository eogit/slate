"""Extract ESA Biomass CCI v7.0 above-ground biomass for the DT4 pilot landscapes.

This is the only script in DT4 that touches the network. It reads the 100 m GeoTIFF tiles
straight from the CEDA archive with HTTP range requests (GDAL ``/vsicurl/``), cuts out a
window around each pilot landscape for every year in v7.0 (2005-2012 and 2015-2024), and
writes one compressed ``.npz`` cube per landscape to ``dt4_agent/forest/data/``. The server
and the tests only ever read those cubes, so DT4 runs offline and gives the same answer
every time.

Usage (needs ``rasterio`` and network access to dap.ceda.ac.uk)::

    pip install rasterio
    python dt4_agent/scripts/extract_cci_pilots.py                 # both pilots
    python dt4_agent/scripts/extract_cci_pilots.py --pilot thetford

To add a landscape, add an entry to ``forest.landscapes.LANDSCAPES`` (bounding box, CCI
tile, dominant species, climate) and run the script again.

Data citation: Santoro, M.; Cartus, O. (2026): ESA Biomass Climate Change Initiative
(Biomass_cci): Global datasets of forest above-ground biomass for the years 2005-2012 and
2015-2024, v7.0. NERC EDS Centre for Environmental Data Analysis. Catalogue record:
https://catalogue.ceda.ac.uk/uuid/6429d1aafe1e43b9b414e4a5a7f8b903. Licence: ESA CCI
Biomass terms and conditions v2 (free and open, attribution required).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from forest.cci import CCI_VERSION, CCI_YEARS, DATA_DIR  # noqa: E402
from forest.landscapes import LANDSCAPES  # noqa: E402

BASE = ("https://dap.ceda.ac.uk/neodc/esacci/biomass/data/agb/maps/v7.0/geotiff/"
        "{year}/{tile}_ESACCI-BIOMASS-L4-{var}-MERGED-100m-{year}-fv7.0.tif")


def extract(key: str) -> Path:
    """Download one landscape's AGB and SD cube and save it as ``<key>_cci_v7.npz``."""
    import rasterio
    from rasterio.windows import from_bounds

    ls = LANDSCAPES[key]
    west, south, east, north = ls.bbox
    agb, sd = [], []
    transform = None
    for year in CCI_YEARS:
        layers = []
        for var in ("AGB", "AGB_SD"):
            url = "/vsicurl/" + BASE.format(year=year, tile=ls.cci_tile, var=var)
            with rasterio.open(url) as src:
                win = from_bounds(west, south, east, north, src.transform)
                win = win.round_offsets().round_lengths()
                layers.append(src.read(1, window=win))
                transform = src.window_transform(win)
        agb.append(layers[0])
        sd.append(layers[1])
        print(f"{key} {year}: {layers[0].shape}", flush=True)
    out = DATA_DIR / f"{key}_cci_v{CCI_VERSION}.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out,
        agb=np.stack(agb).astype(np.uint16),       # Mg ha-1, (year, row, col)
        agb_sd=np.stack(sd).astype(np.uint16),     # Mg ha-1, one standard deviation
        years=np.array(CCI_YEARS, dtype=np.int16),
        transform=np.array(transform[:6], dtype=np.float64),  # affine, EPSG:4326
        bbox=np.array(ls.bbox, dtype=np.float64),
        source=np.array(BASE.replace("{year}", "YYYY").format(tile=ls.cci_tile, var="AGB")),
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pilot", choices=sorted(LANDSCAPES), action="append",
                    help="Landscape to extract (repeatable). Default: all.")
    args = ap.parse_args()
    os.environ.setdefault("CURL_CA_BUNDLE", os.environ.get("SSL_CERT_FILE", ""))
    for key in args.pilot or sorted(LANDSCAPES):
        print("wrote", extract(key))


if __name__ == "__main__":
    main()
