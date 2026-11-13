"""Validation against the CEH / UK Peatland Inventory report (notebook Section 9).

Compares the twin with the report's water-table laws (Eq. 1 for CO2, Eq. 3 for CH4), the
N2O switch-on near 20 cm (Fig. 3.9), and the Tier-2 emission factors for the end-member
categories the twin represents. Pure computation: returns numbers, plots nothing.
"""

from __future__ import annotations

import numpy as np

from . import ch4 as _ch4
from . import n2o as _n2o
from .co2 import CO2C_TO_CO2, CROPS, GC_TO_TCHA_YR, simulate

WTD_CM = (5, 10, 20, 30, 40, 50, 68, 80)

TIER2 = dict(
    cropland_co2_t=27.06,         # t CO2 ha-1 yr-1, cropland on deep peat
    rewetted_fen_ch4_kg=111.0,    # kg CH4 ha-1 yr-1 at WTDe ~ 11.5 cm
    cropland_ch4_kg=1.96,         # kg CH4 ha-1 yr-1 at ~68 cm
    cropland_n2o_kg=16.28,        # kg N2O-N ha-1 yr-1
    intensive_grass_n2o_kg=7.39,  # kg N2O-N ha-1 yr-1
    report_co2_slope=0.4917,      # t CO2 ha-1 yr-1 per cm (Eq. 1)
)


def eq1_co2(wtd_cm):
    """Report Eq. 1: CO2 (t ha-1 yr-1) against effective water-table depth (cm)."""
    return 0.4917 * np.asarray(wtd_cm, float) - 6.34


def eq3_ch4(wtd_cm):
    """Report Eq. 3: CH4 (kg ha-1 yr-1) against water-table depth (cm)."""
    return 445.3 * 0.5 ** ((np.asarray(wtd_cm, float) + 5) / 6.31)


def validate(ch4_params, n2o_params, co2_pars=None, wtd_cm=WTD_CM):
    """Return the model-versus-inventory comparison as plain Python numbers."""
    wc = np.asarray(wtd_cm, float)
    mod_co2 = np.array([_ch4.annual_nee(w / 100, co2_pars=co2_pars) * CO2C_TO_CO2 for w in wc])
    mod_ch4 = np.array([_ch4.annual_ch4(w / 100, ch4_params) for w in wc])
    mod_n2o = np.array([_n2o.n2o_at_wtd(w / 100, n2o_params, co2_pars=co2_pars) for w in wc])
    croplands = [c for c in CROPS if c != "Grass"]
    co2_kw = {} if co2_pars is None else {k: co2_pars[k] for k in ("eps_max", "k_peat", "Q10_h")
                                          if k in co2_pars}
    crop_co2 = float(np.mean([simulate(c, **co2_kw)["NEE"].mean() * GC_TO_TCHA_YR * CO2C_TO_CO2
                              for c in croplands]))
    return dict(
        water_table_profile=[
            dict(wtd_cm=float(w), co2_model_t=float(a), co2_report_eq1_t=float(eq1_co2(w)),
                 ch4_model_kg=float(b), ch4_report_eq3_kg=float(eq3_ch4(w)),
                 n2o_model_kg_n=float(c))
            for w, a, b, c in zip(wc, mod_co2, mod_ch4, mod_n2o)
        ],
        co2_slope_model=float(np.polyfit(wc, mod_co2, 1)[0]),
        co2_slope_report=TIER2["report_co2_slope"],
        cropland_co2_model_t=crop_co2,
        cropland_co2_tier2_t=TIER2["cropland_co2_t"],
        ch4_rewetted_model_kg=_ch4.annual_ch4(0.115, ch4_params),
        ch4_rewetted_tier2_kg=TIER2["rewetted_fen_ch4_kg"],
        ch4_cropland_model_kg=_ch4.annual_ch4(0.68, ch4_params),
        ch4_cropland_tier2_kg=TIER2["cropland_ch4_kg"],
        n2o_cropland_model_kg_n=float(np.mean([_n2o.annual_n2o(c, n2o_params, co2_pars)
                                               for c in croplands])),
        n2o_cropland_tier2_kg_n=TIER2["cropland_n2o_kg"],
        n2o_grass_model_kg_n=_n2o.annual_n2o("Grass", n2o_params, co2_pars),
        n2o_grass_tier2_kg_n=TIER2["intensive_grass_n2o_kg"],
        n2o_rewetted_model_kg_n=_n2o.n2o_at_wtd(0.10, n2o_params, co2_pars=co2_pars),
    )
