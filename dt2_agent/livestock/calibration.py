"""Calibrate and validate DT2's livestock allocation against the NAEI 1 km methane map.

What is calibrated
------------------
Not the emission factors (they are the inventory's, fixed) and not the head counts (the June
Survey's). Only *where* animals are put: the weight of Malek's housed-cattle layer
(``alpha_other``), the size of the blocks inside which Living England redistributes livestock
(``block_km``, 0 = Malek as it is) and the weight of semi-natural grassland for cattle
(``acn_weight``).

Against what
------------
The NAEI 2020 map of agricultural methane (SNAP 10), which the inventory agency distributes with
agricultural census data. It is independent of Malek et al. and of Living England. It contains
pigs, poultry, horses and deer, which DT2 does not model, so skill is measured with Pearson's r
(pattern) and the ratio of totals, not with absolute errors cell by cell.

Hold-out
--------
England is split into a checkerboard of 20 km blocks. Configurations are ranked by r at 1 km on
the calibration squares; the chosen one is then scored on the other squares at 1, 5, 10 and 20 km.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np

from .grid import GRID
from .maps import DATA, AllocationConfig, _blocks, layers
from .model import emissions_grid

CALIBRATION_FILE = DATA / "calibration_naei_2020.json"
CHECKER_KM = 20
SCALES_KM = (1, 5, 10, 20)

GRID_SEARCH = {
    "alpha_other": (0.0, 0.1, 0.25, 0.5, 1.0),
    "block_km": (0, 5, 10, 20),
    "acn_weight": (0.0, 0.5, 1.0),
}


def checkerboard() -> np.ndarray:
    """True on calibration squares, False on hold-out squares."""
    r, c = np.indices(GRID.shape)
    return ((r // CHECKER_KM + c // CHECKER_KM) % 2) == 0


def total_ch4(cfg: AllocationConfig, mask: np.ndarray | None = None) -> np.ndarray:
    eng = layers()["england"] if mask is None else mask
    g = emissions_grid(cfg, eng, {})
    return sum(d["enteric"] + d["manure"] for d in g.values())


def skill(pred: np.ndarray, mask: np.ndarray, scales=SCALES_KM) -> dict:
    """r and total ratio of DT2 against NAEI over the masked cells, at several cell sizes."""
    naei = layers()["naei_ch4_t"]
    out = {}
    for k in scales:
        a = _blocks(np.where(mask, pred, 0.0), k).ravel()
        b = _blocks(np.where(mask, naei, 0.0), k).ravel()
        n = _blocks(mask.astype(float), k).ravel()
        ok = n >= 0.5 * k * k     # blocks mostly inside the mask
        if ok.sum() < 3:
            out[f"r_{k}km"] = None
            continue
        out[f"r_{k}km"] = float(np.corrcoef(a[ok], b[ok])[0, 1])
    out["dt2_t_ch4"] = float(np.where(mask, pred, 0.0).sum())
    out["naei_t_ch4"] = float(np.where(mask, naei, 0.0).sum())
    out["ratio_dt2_to_naei"] = out["dt2_t_ch4"] / out["naei_t_ch4"] if out["naei_t_ch4"] else None
    return out


def calibrate() -> dict:
    """Grid search on the calibration squares; score the best on the hold-out squares."""
    eng = layers()["england"]
    cal, val = eng & checkerboard(), eng & ~checkerboard()
    trials = []
    for a, k, w in itertools.product(*GRID_SEARCH.values()):
        if k == 0 and w != GRID_SEARCH["acn_weight"][0]:
            continue        # acn_weight has no effect without refinement
        cfg = AllocationConfig(alpha_other=a, block_km=k, acn_weight=w)
        pred = total_ch4(cfg)
        trials.append({"config": cfg.__dict__, "calibration": skill(pred, cal, (1,))})
    best = max(trials, key=lambda t: t["calibration"]["r_1km"])
    cfg = AllocationConfig(**best["config"])
    pred = total_ch4(cfg)
    malek = total_ch4(AllocationConfig(alpha_other=1.0, block_km=0))
    malek_grazing = total_ch4(AllocationConfig(alpha_other=0.0, block_km=0))
    return {
        "chosen": best["config"],
        "holdout": skill(pred, val),
        "calibration": skill(pred, cal),
        "england": skill(pred, eng),
        "reference_holdout": {
            "malek_all_layers_no_living_england": skill(malek, val),
            "malek_grazing_layers_no_living_england": skill(malek_grazing, val),
        },
        "trials": trials,
        "method": ("grid search of alpha_other x block_km x acn_weight, ranked by Pearson r at "
                   f"1 km on a {CHECKER_KM} km checkerboard of England; scored on the other "
                   "squares"),
    }


def save(result: dict, path: Path = CALIBRATION_FILE) -> None:
    path.write_text(json.dumps(result, indent=1))


def load(path: Path = CALIBRATION_FILE) -> dict:
    return json.loads(path.read_text())


def calibrated_config() -> AllocationConfig:
    """The shipped calibrated configuration (defaults if the file is missing)."""
    try:
        return AllocationConfig(**load()["chosen"])
    except FileNotFoundError:
        return AllocationConfig()
