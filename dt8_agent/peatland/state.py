"""Parameter state for the DT8 twin, optionally persisted to a JSON file.

The original modules kept learned parameters in module globals, so a restart lost them and
two callers could overwrite each other. Here each gas has a calibrated baseline and a current
(learned) parameter set, kept per site so different fields can learn independently. If a path
is given the state is written atomically after every change and reloaded at start-up.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import ch4 as _ch4
from . import n2o as _n2o
from .co2 import DEFAULT_CO2

GASES = ("co2", "ch4", "n2o")


def baseline():
    """Calibrated parameters in the notebook configuration."""
    return {"co2": dict(DEFAULT_CO2),
            "ch4": _ch4.calibrated_params(),
            "n2o": _n2o.calibrated_params()}


class ParameterStore:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._baseline = baseline()
        self._sites: dict[str, dict] = {}
        if self.path and self.path.exists():
            self._sites = json.loads(self.path.read_text()).get("sites", {})

    def baseline(self, gas: str) -> dict:
        return dict(self._baseline[gas])

    def get(self, gas: str, site: str = "default") -> dict:
        with self._lock:
            entry = self._sites.get(site, {}).get(gas)
            return dict(entry["params"]) if entry else dict(self._baseline[gas])

    def source(self, gas: str, site: str = "default") -> str:
        entry = self._sites.get(site, {}).get(gas)
        return f"learned {entry['updated']} ({entry['note']})" if entry else "calibrated baseline"

    def set(self, gas: str, params: dict, site: str = "default", note: str = "") -> None:
        with self._lock:
            self._sites.setdefault(site, {})[gas] = dict(
                params={k: float(v) for k, v in params.items()},
                updated=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                note=note)
            self._save()

    def reset(self, site: str = "default", gas: str | None = None) -> None:
        with self._lock:
            if gas is None:
                self._sites.pop(site, None)
            else:
                self._sites.get(site, {}).pop(gas, None)
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
