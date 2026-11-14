"""Calibrate both growth models to Biomass CCI v7 for every pilot landscape.

Writes ``dt4_agent/forest/data/calibration_cci_v7.json``, the calibrated baseline the DT4
server starts from. For each landscape and growth model (yield curves and 3-PG) it holds:

* ``calibration``: the pixel-by-pixel fit on all 18 CCI years (2005-2012, 2015-2024); its
  median productivity and spread are the site's baseline parameters;
* ``validation``: the same fit on 2005-2017 only, with 2018-2024 held out to measure how
  well each model predicts years it has not seen (the comparison of the two models).

Deterministic (fixed pixel sample and seed), so the tests can check that rerunning it
reproduces the shipped file. Runs in about 15 seconds:

    python dt4_agent/scripts/calibrate_pilots.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from forest import GROWTH_MODELS, MODEL_VERSION, make_model  # noqa: E402
from forest import calibration, cci, landscapes  # noqa: E402
from forest.state import CALIBRATION_FILE  # noqa: E402

N_SAMPLE = 2000
SEED = 0
FIT_END = 2017


def _round(x):
    if isinstance(x, float):
        return round(x, 4)
    if isinstance(x, list):
        return [_round(v) for v in x]
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    return x


def run() -> dict:
    out = {"_meta": {"model_version": MODEL_VERSION, "cci_version": cci.CCI_VERSION,
                     "n_sample": N_SAMPLE, "seed": SEED, "validation_fit_end": FIT_END,
                     "citation": cci.CITATION}}
    for key, ls in landscapes.LANDSCAPES.items():
        cube = cci.load(key)
        fit_v = [y for y in cube.years if y <= FIT_END]
        hold_v = [y for y in cube.years if y > FIT_END]
        out[key] = {}
        for name in GROWTH_MODELS:
            model = make_model(name, ls.species, ls)
            out[key][name] = {
                "calibration": calibration.calibrate(model, cube, n_sample=N_SAMPLE, seed=SEED),
                "validation": calibration.calibrate(model, cube, fit_years=fit_v,
                                                    holdout_years=hold_v,
                                                    n_sample=N_SAMPLE, seed=SEED),
            }
    return _round(out)


def main() -> None:
    result = run()
    CALIBRATION_FILE.write_text(json.dumps(result, indent=1) + "\n")
    print("wrote", CALIBRATION_FILE)


if __name__ == "__main__":
    main()
