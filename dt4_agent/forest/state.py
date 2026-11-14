"""Calibrated and learned productivity per site and growth model, optionally saved to JSON.

Same design as DT8's ``ParameterStore``. Every site has, for each growth model
(``yield_curve`` and ``3pg``), a productivity (``theta``) with an uncertainty
(``theta_sd``):

* the **calibrated baseline** comes from ``data/calibration_cci_v7.json``, written by
  ``scripts/calibrate_pilots.py``: the median and spread of the pixel-by-pixel CCI v7
  calibration of each pilot landscape (site id = landscape key, e.g. ``kielder``). Any other
  site id starts from its landscape's baseline;
* **learned** values replace the baseline for one site when ``assimilate_agb`` runs the
  Kalman filter there; ``reset_parameters`` goes back to the baseline.

With a path (``DT4_STATE_FILE``) every change is written atomically and reloaded at start-up.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
CALIBRATION_FILE = DATA_DIR / "calibration_cci_v7.json"
MODELS = ("yield_curve", "3pg")


@lru_cache(maxsize=1)
def calibration() -> dict:
    """The shipped CCI v7 calibration (empty if it has not been generated yet)."""
    if not CALIBRATION_FILE.exists():
        return {}
    return json.loads(CALIBRATION_FILE.read_text())


def baseline(landscape: str, model: str) -> dict:
    """Calibrated productivity of a landscape for one model: theta, theta_sd and context."""
    cal = calibration().get(landscape, {}).get(model, {}).get("calibration")
    if not cal:
        raise KeyError(f"no CCI calibration for {landscape}/{model}; run "
                       f"scripts/calibrate_pilots.py")
    # theta_sd is the robust spread of productivity across the landscape's stands
    # (interquartile range / 1.349), so ensembles span typical stands, not the extremes.
    return {"theta": cal["theta_median"],
            "theta_sd": max((cal["theta_p75"] - cal["theta_p25"]) / 1.349, 1e-6),
            "age_median": cal["age_median_last_cci_year"],
            "age_ref_year": cal["last_cci_year"],
            "species": cal["species"]}


class ParameterStore:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._sites: dict[str, dict] = {}
        if self.path and self.path.exists():
            self._sites = json.loads(self.path.read_text()).get("sites", {})

    def get(self, site: str, landscape: str, model: str) -> dict:
        with self._lock:
            entry = self._sites.get(site, {}).get(model)
            if entry and entry.get("landscape") == landscape:
                return dict(entry["params"])
        return baseline(landscape, model)

    def source(self, site: str, landscape: str, model: str) -> str:
        entry = self._sites.get(site, {}).get(model)
        if entry and entry.get("landscape") == landscape:
            return f"learned {entry['updated']} ({entry['note']})"
        return f"calibrated baseline: Biomass CCI v7 pixel calibration of {landscape}"

    def set(self, site: str, landscape: str, model: str, params: dict, note: str = "") -> None:
        with self._lock:
            self._sites.setdefault(site, {})[model] = dict(
                landscape=landscape, params=dict(params), note=note,
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
