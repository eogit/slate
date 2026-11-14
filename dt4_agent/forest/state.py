"""Calibrated and learned productivity per site and growth model, optionally saved to JSON.

Same design as DT8's ``ParameterStore``. Every site has, for each growth model
(``yield_curve`` and ``3pg``), a productivity (``theta``) with an uncertainty
(``theta_sd``):

* the **calibrated baseline** comes from ``data/calibration_cci_v7.json``, written by
  ``scripts/calibrate_pilots.py``: the median and spread of the pixel-by-pixel CCI v7
  calibration of each species group in each pilot landscape (site id = landscape key, e.g.
  ``kielder``). Any other site id starts from its landscape's baseline;
* **learned** values replace the baseline for one site and species when ``assimilate_agb``
  runs the Kalman filter there; ``reset_parameters`` goes back to the baseline.

Species default to the landscape's dominant species (Corsican pine at Thetford, Sitka spruce
at Kielder).

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


def calibrated_species(landscape: str) -> list[str]:
    """Species groups with a CCI v7 calibration in a landscape, largest area first."""
    return list(calibration().get(landscape, {}).get("species", {}))


def _dominant(landscape: str) -> str:
    from .landscapes import get

    return get(landscape).species


def baseline(landscape: str, model: str, species: str | None = None) -> dict:
    """Calibrated productivity of one species group in a landscape for one growth model."""
    species = species or _dominant(landscape)
    cal = (calibration().get(landscape, {}).get("species", {}).get(species, {})
           .get(model, {}).get("calibration"))
    if not cal:
        raise KeyError(f"no CCI calibration for {species} in {landscape} ({model}); run "
                       f"scripts/calibrate_pilots.py")
    # theta_sd is the robust spread of productivity across the species' stands
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

    @staticmethod
    def _key(model: str, species: str) -> str:
        return f"{model}/{species}"

    def _entry(self, site: str, landscape: str, model: str, species: str):
        entry = self._sites.get(site, {}).get(self._key(model, species))
        return entry if entry and entry.get("landscape") == landscape else None

    def get(self, site: str, landscape: str, model: str, species: str | None = None) -> dict:
        species = species or _dominant(landscape)
        with self._lock:
            entry = self._entry(site, landscape, model, species)
            if entry:
                return dict(entry["params"])
        return baseline(landscape, model, species)

    def source(self, site: str, landscape: str, model: str, species: str | None = None) -> str:
        species = species or _dominant(landscape)
        entry = self._entry(site, landscape, model, species)
        if entry:
            return f"learned {entry['updated']} ({entry['note']})"
        return (f"calibrated baseline: Biomass CCI v7 pixel calibration of {species} in "
                f"{landscape}")

    def set(self, site: str, landscape: str, model: str, params: dict, note: str = "",
            species: str | None = None) -> None:
        species = species or _dominant(landscape)
        with self._lock:
            self._sites.setdefault(site, {})[self._key(model, species)] = dict(
                landscape=landscape, species=species, params=dict(params), note=note,
                updated=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            self._save()

    def reset(self, site: str, model: str | None = None) -> None:
        with self._lock:
            if model is None:
                self._sites.pop(site, None)
            else:
                entries = self._sites.get(site, {})
                for k in [k for k in entries if k.split("/")[0] == model]:
                    entries.pop(k)
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
