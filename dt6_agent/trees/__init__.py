"""DT6 trees-outside-woodland twin: server-safe model package.

Modules
-------
``pilots``        the ten pilot tiles (5 km x 5 km), their HadUK-Grid climate and conifer prior.
``inventory``     every Trees Outside Woodland object of a pilot with its lidar heights.
``allometry``     crown-based biomass (Jucker et al. 2017), root:shoot and carbon.
``growth_curves`` empirical growth: a size-age height curve indexed by site index.
``crown_lue``     process-based growth: a single-tree crown light-use-efficiency model.
``calibration``   crown-by-crown calibration of either model to repeat EA lidar heights.
``carbon``        living, deadwood, firewood and litter carbon pools.
``scenario``      ensembles: baseline growth, ash dieback and new planting.
``change``        significant canopy-height reductions and EBCF impact attribution.
``assimilation``  ensemble Kalman filter that learns productivity and age from new heights.
``state``         calibrated and learned productivity per site, optionally persisted.

Nothing here plots, prints or writes files (except ``state`` when given a path): every
function returns its result, so the package is safe inside an MCP server.
"""

from __future__ import annotations

MODEL_VERSION = "0.1.0"
GROWTH_MODELS = ("size_age", "crown_lue")


def make_model(name: str, pilot_key: str):
    """Build a growth model by name for a pilot (its climate and conifer share)."""
    from . import pilots
    from .crown_lue import CrownLUEModel
    from .growth_curves import SizeAgeModel

    p = pilots.get(pilot_key)
    if name == "size_age":
        return SizeAgeModel(p.p_conifer)
    if name == "crown_lue":
        return CrownLUEModel(p.p_conifer, p.climate)
    raise ValueError(f"unknown growth model {name!r}; known: {GROWTH_MODELS}")
