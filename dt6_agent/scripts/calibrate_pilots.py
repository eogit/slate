"""Calibrate both growth models to repeat EA lidar heights in every pilot tile.

Writes ``dt6_agent/trees/data/calibration_lidar.json``, the calibrated baseline the DT6 server
starts from. For each pilot it holds:

* ``inventory``: the TOW objects by class (count, trees, canopy area, AGB), lidar epochs and
  the median observed height growth between the first and last epoch;
* for each growth model (``size_age`` and ``crown_lue``):
  - ``calibration``: the crown-by-crown fit on all epochs with the pilot's own empirical
    theta prior, iterated from the objects seen on two or more dates;
  - ``prior``: that empirical prior (mean, SD);
  - ``validation``: the latest epoch held out, two-fold by object, forecast compared with a
    persistence (no-growth) baseline.

It also writes ``trees/data/fit_<pilot>.npz``: the crown-by-crown posteriors (theta, its SD,
age, its SD, number of observations, current growth, height-drop events) of both models and
the empirical prior, which the server loads instead of refitting tens of thousands of crowns
on its first call. ``--fits-only`` rewrites just those files.

Only lidar heights are used for calibration; the TOW map defines which trees exist.
Deterministic (no random sampling), so the tests can check that rerunning it reproduces the
shipped file. Runs in about 15-20 minutes for all ten pilots (one CPU):

    python dt6_agent/scripts/calibrate_pilots.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from trees import GROWTH_MODELS, MODEL_VERSION, make_model  # noqa: E402
from trees import calibration, inventory, pilots  # noqa: E402
from trees.state import CALIBRATION_FILE, fit_path  # noqa: E402

import numpy as np  # noqa: E402


def _round(x):
    if isinstance(x, float):
        return round(x, 4)
    if isinstance(x, (list, tuple)):
        return [_round(v) for v in x]
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    return x


def save_fit(key: str, fits: dict) -> None:
    """Write the crown posteriors of every model of a pilot (float32, compressed)."""
    arrays = {}
    for name, (fit, prior) in fits.items():
        for field, v in fit.as_dict().items():
            arrays[f"{name}__{field}"] = v.astype(np.float32 if v.dtype.kind == "f" else np.int16)
        arrays[f"{name}__prior"] = np.asarray(prior, float)
    arrays["tow_id"] = inventory.load(key).tow_id
    np.savez_compressed(fit_path(key), **arrays)


def fits_only(keys=None) -> None:
    for key in keys or pilots.PILOTS:
        inv = inventory.load(key)
        save_fit(key, {name: calibration.calibrate(make_model(name, key), inv)
                       for name in GROWTH_MODELS})
        print(f"wrote {fit_path(key).name}")


def run(keys=None, save_fits: bool = False) -> dict:
    out = {"_meta": {"model_version": MODEL_VERSION, "citation": inventory.CITATION,
                     "sigma_first_return_m": calibration.SIGMA_FZ,
                     "sigma_last_return_m": calibration.SIGMA_LZ,
                     "height_drop_event_m": calibration.DROP_M},
           "pilots": {}}
    for key in keys or pilots.PILOTS:
        if not inventory.crowns_path(key).exists():
            print(f"{key}: no crowns file, skipped")
            continue
        inv = inventory.load(key)
        p = pilots.get(key)
        entry = {"name": p.name, "landscape": p.landscape, "tile": p.tile,
                 "epochs": inv.epoch_year.tolist(), "p_conifer": p.p_conifer,
                 "inventory": inventory.summary(inv),
                 "observed_growth": calibration.observed_growth(inv), "models": {}}
        fits = {}
        for name in GROWTH_MODELS:
            m = make_model(name, key)
            fit, prior = calibration.calibrate(m, inv)
            fits[name] = (fit, prior)
            entry["models"][name] = {"calibration": calibration.summarise(fit, m),
                                     "prior": list(prior),
                                     "validation": calibration.validate(m, inv)}
            v = entry["models"][name]["validation"]
            print(f"{key:16s} {name:9s} theta {entry['models'][name]['calibration']['theta_median']:.3f} "
                  f"hold-out n={v.get('n')} rmse {v.get('model', {}).get('rmse_m', float('nan')):.2f} "
                  f"vs persistence {v.get('persistence', {}).get('rmse_m', float('nan')):.2f}")
        out["pilots"][key] = entry
        if save_fits:
            save_fit(key, fits)
    return _round(out)


def main(argv=None):
    argv = list(argv or [])
    if "--fits-only" in argv:
        argv.remove("--fits-only")
        fits_only(argv or None)
        return
    res = run(argv or None, save_fits=True)
    CALIBRATION_FILE.write_text(json.dumps(res, indent=1) + "\n")
    print(f"wrote {CALIBRATION_FILE}")


if __name__ == "__main__":
    main(sys.argv[1:])
