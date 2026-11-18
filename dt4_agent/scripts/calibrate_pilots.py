"""Calibrate both growth models to Biomass CCI v7 for every species group of every pilot.

Writes ``dt4_agent/forest/data/calibration_cci_v7.json``, the calibrated baseline the DT4
server starts from. For each landscape it holds the forest composition from the inventory
(:mod:`forest.inventory`) and, for every species group with at least ``MIN_PIXELS`` NFI
woodland pixels, for each growth model (yield curves and 3-PG):

* ``calibration``: the pixel-by-pixel fit on all 18 CCI years (2005-2012, 2015-2024), with
  stand ages fixed from the Forestry England planting year where it is recorded. Its median
  productivity and spread are the species' baseline parameters in that landscape;
* ``validation``: the same fit on 2005-2017 only, with 2018-2024 held out to measure how well
  each model predicts years it has not seen (the comparison of the two models);
* ``validation_free_age``: a sensitivity run that ignores the recorded planting years and
  fits age from CCI alone, as DT4 did before the inventory was added (summary only).

Productivity is fitted to CCI v7 only. For the yield-curve model the CCI-calibrated yield
class is compared with Forestry England's (``fe_yield_class_check``) as an independent check.

Deterministic (fixed pixel sample and seed), so the tests can check that rerunning it
reproduces the shipped file. Runs in about two minutes:

    python dt4_agent/scripts/calibrate_pilots.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from forest import GROWTH_MODELS, MODEL_VERSION, make_model  # noqa: E402
from forest import calibration, cci, inventory, landscapes  # noqa: E402
from forest.state import CALIBRATION_FILE  # noqa: E402

N_SAMPLE = 2000
SEED = 0
FIT_END = 2017
MIN_PIXELS = 300
SUMMARY_KEYS = ("theta_median", "theta_p25", "theta_p75", "theta_at_grid_edge_frac",
                "age_median_last_cci_year", "holdout", "fe_yield_class_check")


def _round(x):
    if isinstance(x, float):
        return round(x, 4)
    if isinstance(x, list):
        return [_round(v) for v in x]
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    return x


def run(keys=None) -> dict:
    out = {"_meta": {"model_version": MODEL_VERSION, "cci_version": cci.CCI_VERSION,
                     "n_sample": N_SAMPLE, "seed": SEED, "validation_fit_end": FIT_END,
                     "min_pixels": MIN_PIXELS, "saturation_mg_ha": cci.SATURATION_MG_HA,
                     "citation": cci.CITATION, "inventory_citation": inventory.NFI_CITATION}}
    for key in keys or landscapes.LANDSCAPES:
        ls = landscapes.get(key)
        cube = cci.load(key)
        inv = inventory.load(key)
        fit_v = [y for y in cube.years if y <= FIT_END]
        hold_v = [y for y in cube.years if y > FIT_END]
        comp = inventory.composition(inv, cube.woodland, cube.pixel_area_ha(), cube.years[-1])
        entry = {"dominant_species": ls.species, "woodland_source": cube.woodland_source,
                 "woodland_pixels": int(cube.woodland.sum()), "composition": comp,
                 "species": {}}
        for row in comp:
            code = row["species"]
            mask = cube.woodland & (inv.species == code)
            if mask.sum() < MIN_PIXELS:
                continue
            entry["species"][code] = {}
            for name in GROWTH_MODELS:
                model = make_model(name, code, ls)
                kw = dict(n_sample=N_SAMPLE, seed=SEED, fe_yield_class=inv.fe_yield_class)
                free = calibration.calibrate(model, cube, mask, fit_years=fit_v,
                                             holdout_years=hold_v, **kw)
                entry["species"][code][name] = {
                    "calibration": calibration.calibrate(
                        model, cube, mask, planting_year=inv.planting_year, **kw),
                    "validation": calibration.calibrate(
                        model, cube, mask, fit_years=fit_v, holdout_years=hold_v,
                        planting_year=inv.planting_year, **kw),
                    "validation_free_age": {k: free[k] for k in SUMMARY_KEYS if k in free},
                }
            print(f"  {key} {code}: done", flush=True)
        out[key] = entry
    return _round(out)


def main() -> None:
    result = run()
    CALIBRATION_FILE.write_text(json.dumps(result, indent=1) + "\n")
    print("wrote", CALIBRATION_FILE)


if __name__ == "__main__":
    main()
