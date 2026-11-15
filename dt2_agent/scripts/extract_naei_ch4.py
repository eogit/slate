"""Cut the NAEI 1 km agricultural methane map to DT2's grid (independent validation data).

Source: National Atmospheric Emissions Inventory, gridded emissions, methane, SNAP sector 10
(agriculture), https://naei.energysecurity.gov.uk/data/maps/download-gridded-emissions,
Open Government Licence. Units: tonnes CH4 per 1 km cell per year. The NAEI distributes the
inventory's livestock emissions with agricultural census data, so it is a census-based map
made independently of the Malek et al. livestock layers that DT2 uses. Sector 10 also contains
pigs, poultry and other livestock, which DT2 does not model (about 5 % of the total).

    python dt2_agent/scripts/extract_naei_ch4.py 10agriculturech424_2020.asc 2020
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from livestock.grid import GRID  # noqa: E402


def main(asc: str, year: str) -> None:
    import rasterio
    from rasterio.windows import from_bounds
    with rasterio.open(asc) as r:
        w = from_bounds(*GRID.bounds(), r.transform)
        a = r.read(1, window=w, boundless=True, fill_value=0).astype("f4")
    a[a < 0] = 0
    assert a.shape == GRID.shape
    out = HERE.parent / "livestock" / "data" / f"naei_ch4_agriculture_{year}.npz"
    np.savez_compressed(out, t_ch4=a, year=int(year))
    print("wrote", out, float(a.sum()))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
