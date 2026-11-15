"""Per-site learned livestock scaling factors, optionally persisted to a JSON file.

A site's factors multiply the number of cattle (``cattle``) and of sheep and goats (``sheep``)
that DT2 places in the site's cells. They start at 1 (the June Survey totals placed by the
calibrated allocation) and change only through assimilation. Each factor carries its posterior
standard deviation. Set ``DT2_STATE_FILE`` to keep them across server restarts; the file is
written atomically after every change, as in DT8.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

BASELINE = {"cattle": 1.0, "sheep": 1.0, "cattle_sd": 0.3, "sheep_sd": 0.3}


class ParameterStore:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._sites: dict[str, dict] = {}
        if self.path and self.path.exists():
            self._sites = json.loads(self.path.read_text()).get("sites", {})

    def get(self, site: str = "default") -> dict:
        with self._lock:
            e = self._sites.get(site)
            return dict(e["params"]) if e else dict(BASELINE)

    def source(self, site: str = "default") -> str:
        e = self._sites.get(site)
        return f"learned {e['updated']} ({e['note']})" if e else "June Survey 2020 totals (no site learning)"

    def set(self, params: dict, site: str = "default", note: str = "") -> None:
        with self._lock:
            self._sites[site] = dict(
                params={k: float(v) for k, v in params.items()},
                updated=datetime.now(timezone.utc).isoformat(timespec="seconds"), note=note)
            self._save()

    def reset(self, site: str = "default") -> None:
        with self._lock:
            self._sites.pop(site, None)
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
