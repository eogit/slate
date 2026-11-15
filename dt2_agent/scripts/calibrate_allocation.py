"""Regenerate ``livestock/data/calibration_naei_2020.json`` (about one minute).

    python dt2_agent/scripts/calibrate_allocation.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from livestock import calibration  # noqa: E402

if __name__ == "__main__":
    res = calibration.calibrate()
    calibration.save(res)
    print("chosen", res["chosen"])
    print("hold-out", res["holdout"])
    for k, v in res["reference_holdout"].items():
        print(k, v)
