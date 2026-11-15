"""Aggregate the Malek et al. (2024) 100 m livestock maps onto DT2's 1 km British National Grid.

Source: Malek, Ž., Romanchuk, Z., Yashchun, O. and See, L. (2024). *Spatial distribution of
cattle, sheep and goat density, and grazed areas for the European Union and the United
Kingdom* (v1). Zenodo, https://doi.org/10.5281/zenodo.13734518, CC BY 4.0. Densities for
about 2020 in livestock units per hectare (LSU/ha, the unit of the record's legend) on a
100 m grid in EPSG:3035, allocated to Corine Land Cover forage classes.

Each 100 m pixel holds density x 1 ha = LSU. Pixel centres are transformed to British National
Grid and the LSU summed into the 1 km cell that contains them, so totals are conserved.

The ``cattle_other`` layer (cattle kept indoors, fed from forage areas) contains blocks of
implausible density, up to 854 LSU/ha, that fill whole kilometre squares (for example around
Bodmin Moor). They look like an allocation artefact: a regional herd spread over very little
forage area. Densities above ``CAP_LSU_HA`` are therefore clipped before summing and the raw
sum is kept alongside so the effect can be checked. The cap is an assumption recorded in the
README; England's housed-and-grazing cattle are rescaled to the June Survey head counts anyway,
so the cap only changes *where* cattle are, not how many.

Output: ``livestock/data/malek_lsu_1km.npz`` (float32 LSU per 1 km cell).

    python dt2_agent/scripts/extract_malek_livestock.py /path/to/zenodo_13734518/
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from livestock.grid import GRID  # noqa: E402

LAYERS = ("cattle_grazing", "cattle_other", "cattle_seminatural", "sheep_goats_other",
          "sheep_goat_seminatural", "grazing_probability")
CAP_LSU_HA = 5.0
OUT = HERE.parent / "livestock" / "data" / "malek_lsu_1km.npz"


def aggregate(path: Path, cap: float | None = None, mean: bool = False) -> np.ndarray:
    """Sum (or average, for probabilities) one 100 m layer into the 1 km BNG grid."""
    import rasterio
    from pyproj import Transformer
    from rasterio.windows import from_bounds

    to3035 = Transformer.from_crs(27700, 3035, always_xy=True)
    to27700 = Transformer.from_crs(3035, 27700, always_xy=True)
    x0, y0, x1, y1 = GRID.bounds()
    xs, ys = to3035.transform([x0, x0, x1, x1], [y0, y1, y0, y1])
    with rasterio.open(path) as r:
        w = from_bounds(min(xs), min(ys), max(xs), max(ys), r.transform)
        w = w.round_offsets().round_lengths()
        a = r.read(1, window=w, boundless=True, fill_value=0).astype("f8")
        wt = r.window_transform(w)
    a[~np.isfinite(a) | (a < 0) | (a > 1e6)] = 0.0
    if cap is not None:
        a = np.minimum(a, cap)
    rows, cols = np.nonzero(a)
    px, py = wt * (cols + 0.5, rows + 0.5)
    bx, by = to27700.transform(px, py)
    i = ((GRID.y1 - by) // GRID.res).astype(int)
    j = ((bx - GRID.x0) // GRID.res).astype(int)
    ok = (i >= 0) & (i < GRID.ny) & (j >= 0) & (j < GRID.nx)
    out = np.zeros(GRID.shape)
    np.add.at(out, (i[ok], j[ok]), a[rows[ok], cols[ok]])
    if mean:  # 100 pixels of 1 ha in a 1 km cell
        out /= 100.0
    return out.astype(np.float32)


def main(src: str) -> None:
    src = Path(src)
    arrays = {}
    for name in LAYERS:
        if name == "grazing_probability":
            arrays[name] = aggregate(src / f"{name}.tif", mean=True)
        elif name == "cattle_other":
            arrays[name] = aggregate(src / f"{name}.tif", cap=CAP_LSU_HA)
            arrays["cattle_other_raw"] = aggregate(src / f"{name}.tif")
        else:
            arrays[name] = aggregate(src / f"{name}.tif")
        print(name, float(arrays[name].sum()))
    np.savez_compressed(OUT, cap_lsu_ha=CAP_LSU_HA, **arrays)
    print("wrote", OUT)


if __name__ == "__main__":
    main(sys.argv[1])
