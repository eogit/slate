"""DT4 forest biomass twin: server-safe model package.

Modules
-------
``cci``          ESA Biomass CCI v7 cubes for the pilot landscapes, area statistics, change.
``landscapes``   pilot landscapes (Thetford, Kielder): window, species, soils, climate.
``species``      species parameters (yield-curve shape, wood conversion, 3-PG).
``yield_curves`` empirical growth: Chapman-Richards curves indexed by yield class.
``threepg``      process-based growth: the 3-PG model.
``management``   regimes (no intervention, thin and fell, clearfell, continuous cover).
``disturbance``  wind, fire, biotic and drought events, prescribed or stochastic.
``carbon``       living, dead and harvested-wood-product carbon pools.
``scenario``     the yearly engine that combines growth, management, disturbance, carbon.
``calibration``  pixel-by-pixel calibration of either growth model to CCI v7.
``assimilation`` ensemble Kalman filter that learns a site's productivity from AGB data.
``change``       significance of AGB change and EBCF impact (pressure) attribution.
``state``        calibrated and learned productivity per site, optionally persisted.

Nothing here plots, prints or writes files (except ``state`` when given a path): every
function returns its result, so the package is safe inside an MCP server.
"""

from __future__ import annotations

from functools import lru_cache

MODEL_VERSION = "0.1.0"
GROWTH_MODELS = ("yield_curve", "3pg")


def make_model(name: str, species: str, landscape):
    """Build a growth model by name for a species in a landscape (climate for 3-PG)."""
    from .threepg import ThreePGModel
    from .yield_curves import YieldCurveModel

    if name == "yield_curve":
        return YieldCurveModel(species, landscape)
    if name == "3pg":
        return ThreePGModel(species, landscape)
    raise ValueError(f"unknown growth model {name!r}; known: {GROWTH_MODELS}")


@lru_cache(maxsize=32)
def curve_bank(name: str, species: str, landscape_key: str):
    """Cached lookup table of unthinned AGB curves used by the Kalman filter."""
    from . import landscapes
    from .assimilation import CurveBank

    return CurveBank(make_model(name, species, landscapes.get(landscape_key)))
