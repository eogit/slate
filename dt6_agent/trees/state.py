"""Calibrated and learned productivity per site and growth model, optionally saved to JSON.

Same design as DT4's and DT8's ``ParameterStore``.

* The **calibrated baseline** of a pilot comes from ``data/calibration_lidar.json`` (written by
  ``scripts/calibrate_pilots.py``): the median and robust spread of the crown-by-crown lidar
  calibration of each growth model. The crown-level posteriors themselves are recomputed on
  demand by :func:`crown_fit` (about a second per pilot and model) and cached.
* A **learned** value for a site is a shift in ``theta`` from ``assimilate_heights``; every
  projection of that site adds it to each crown's calibrated ``theta``. ``reset_parameters``
  removes it.

A site is any name; it is tied to the pilot it was learned in, so the same site name in
another pilot starts from that pilot's baseline. With a path (``DT6_STATE_FILE``) every change
is written atomically and reloaded at start-up.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from .pilots import DATA_DIR

CALIBRATION_FILE = DATA_DIR / "calibration_lidar.json"


@lru_cache(maxsize=1)
def calibration() -> dict:
    """The shipped lidar calibration summary (empty if it has not been generated yet)."""
    if not CALIBRATION_FILE.exists():
        return {}
    return json.loads(CALIBRATION_FILE.read_text())


def baseline(pilot: str, model: str) -> dict:
    cal = calibration().get("pilots", {}).get(pilot, {}).get("models", {}).get(model, {})
    s = cal.get("calibration")
    if not s or not s.get("n"):
        raise KeyError(f"no lidar calibration for {model} in {pilot}; run "
                       f"scripts/calibrate_pilots.py")
    return {"theta": s["theta_median"],
            "theta_sd": max((s["theta_p75"] - s["theta_p25"]) / 1.349, 1e-6),
            "age_median": s["age_median"], "theta_name": s["theta_name"],
            "prior": cal.get("prior")}


def fit_path(pilot: str) -> Path:
    return DATA_DIR / f"fit_{pilot}.npz"


@lru_cache(maxsize=64)
def crown_fit(pilot: str, model: str):
    """Crown-by-crown calibration of a pilot (cached): ``(model, inventory, fit, prior)``.

    Loads the shipped posteriors (``data/fit_<pilot>.npz``, written by
    ``scripts/calibrate_pilots.py``) when they match the inventory, otherwise refits.
    """
    import numpy as np

    from . import calibration as cal
    from . import inventory, make_model

    m = make_model(model, pilot)
    inv = inventory.load(pilot)
    path = fit_path(pilot)
    if path.exists():
        d = np.load(path)
        if f"{model}__theta" in d.files and np.array_equal(d["tow_id"], inv.tow_id):
            fields = {f: d[f"{model}__{f}"].astype(float if f != "n_obs" else int)
                      for f in cal.CrownFit.__dataclass_fields__}
            return m, inv, cal.CrownFit(**fields), tuple(float(x) for x in d[f"{model}__prior"])
    fit, prior = cal.calibrate(m, inv)
    return m, inv, fit, prior


@lru_cache(maxsize=64)
def height_bank(pilot: str, model: str):
    from .scenario import HeightBank

    return HeightBank(crown_fit(pilot, model)[0])


class ParameterStore:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._sites: dict[str, dict] = {}
        if self.path and self.path.exists():
            self._sites = json.loads(self.path.read_text()).get("sites", {})

    def _entry(self, site: str, pilot: str, model: str):
        e = self._sites.get(site, {}).get(model)
        return e if e and e.get("pilot") == pilot else None

    def get(self, site: str, pilot: str, model: str) -> dict:
        base = baseline(pilot, model)
        with self._lock:
            e = self._entry(site, pilot, model)
        shift = e["theta_shift"] if e else 0.0
        return {**base, "theta_shift": shift, "theta": base["theta"] + shift,
                "learned": bool(e)}

    def theta_shift(self, site: str, pilot: str, model: str) -> float:
        with self._lock:
            e = self._entry(site, pilot, model)
        return float(e["theta_shift"]) if e else 0.0

    def source(self, site: str, pilot: str, model: str) -> str:
        e = self._entry(site, pilot, model)
        if e:
            return f"learned {e['updated']} ({e['note']})"
        return f"calibrated baseline: crown-by-crown EA lidar calibration in {pilot}"

    def set(self, site: str, pilot: str, model: str, theta_shift: float, note: str = "") -> None:
        with self._lock:
            self._sites.setdefault(site, {})[model] = dict(
                pilot=pilot, theta_shift=float(theta_shift), note=note,
                updated=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            self._save()

    def reset(self, site: str, model: str | None = None) -> None:
        with self._lock:
            if model is None:
                self._sites.pop(site, None)
            else:
                self._sites.get(site, {}).pop(model, None)
            self._save()

    def sites(self) -> list[str]:
        return sorted(self._sites)

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump({"sites": self._sites}, f, indent=2)
        os.replace(tmp, self.path)
