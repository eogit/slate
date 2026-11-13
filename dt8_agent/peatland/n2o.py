r"""N2O module: peat-N mineralisation plus fertiliser N, gated by temperature and water table.

Copied from ``peatland_n2o.py``:

    N_min = mgmt * Rh / (C:N)_peat              (Rh from the CO2 model)
    f_T   = Q10_n2o**((Tsoil-25)/10)
    f_W   = sigmoid((WTD-W_thr)/W_rate) * exp(-max(WTD-W_dry, 0)/W_tail)
    N2O   = (ef_peat*N_min + ef_fert*N_fert) * f_T * f_W        [mg N2O-N m-2 d-1]

It reads Rh from the CO2 model and feeds nothing back, so it is diagnostic: it cannot change
the CO2 or CH4 predictions (see :func:`decouple_check`).

The emission fractions are calibrated to the zero-fertiliser background (4.6 kg N2O-N ha-1
yr-1, Tiemeyer et al. 2020) and the UK Tier-2 cropland mean (16.28 kg N2O-N ha-1 yr-1).
:func:`calibrate` returns the calibrated parameter set instead of mutating module state.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from .co2 import C_PEAT, C_RES, CROPS, DEFAULT_CO2, FIXED, RMSProp, climate, het_resp, simulate

MGD_TO_KGHAYR = 3.65
GWP_N2O = 273.0
N2ON_TO_N2O = 44.0 / 28.0
LEARNABLE = ("ef_peat", "Q10_n2o")

# fertiliser N (kg N ha-1 yr-1, typical UK Fenland practice) and peat-mineralisation factor
CROP_N = {
    "WW":      dict(Nfert=200, mgmt=1.00),
    "Beet":    dict(Nfert=120, mgmt=1.00),
    "Maize":   dict(Nfert=150, mgmt=1.00),
    "Potato":  dict(Nfert=200, mgmt=1.00),
    "Grass":   dict(Nfert=200, mgmt=0.55),
    "Lettuce": dict(Nfert=180, mgmt=1.00),
    "Celery":  dict(Nfert=280, mgmt=1.00),
    "Leek":    dict(Nfert=230, mgmt=1.00),
    "Cabbage": dict(Nfert=280, mgmt=1.00),
    "Linseed": dict(Nfert=70,  mgmt=1.00),
}

# uncalibrated constants (ef_peat, ef_fert filled in by calibrate())
PARN = dict(CN_peat=18.0, Q10_n2o=2.5,
            W_thr=0.22, W_rate=0.055, W_dry=1.0, W_tail=0.6,
            ef_peat=1.0, ef_fert=0.01)


def nfert_daily(crop, nfert=None):
    """Annual fertiliser N spread over the growing season, in g N m-2 d-1."""
    cp = CROPS[crop]
    d = np.arange(1, 366)
    sow = cp["sow"]
    centre = sow + 35
    w = np.exp(-0.5 * ((d - centre) / 28) ** 2) + 0.5 * np.exp(-0.5 * ((d - centre - 45) / 25) ** 2)
    w = np.where((d >= sow) & (d <= cp["harv"]), w, 0.0)
    w = w / (w.sum() + 1e-9)
    total = CROP_N[crop]["Nfert"] if nfert is None else nfert
    return total * w * 0.1


def n2o_flux(p, Tsoil, WTD, Rh_gC, Nfert_gN, mgmt):
    """Net N2O flux (mg N2O-N m-2 d-1) and gradients for the learnable ef_peat, Q10_n2o."""
    N_min = mgmt * Rh_gC / p["CN_peat"]
    fT = p["Q10_n2o"] ** ((Tsoil - 25.0) / 10.0)
    f_on = 1.0 / (1.0 + np.exp(-(WTD - p["W_thr"]) / p["W_rate"]))
    f_dry = np.exp(-np.maximum(WTD - p["W_dry"], 0.0) / p["W_tail"])
    fW = f_on * f_dry
    src = p["ef_peat"] * N_min + p["ef_fert"] * Nfert_gN
    n2o = src * fT * fW * 1000.0
    d = {"ef_peat": N_min * fT * fW * 1000.0,
         "Q10_n2o": src * fW * ((Tsoil - 25.0) / 10.0) * p["Q10_n2o"] ** ((Tsoil - 25.0) / 10.0 - 1)
         * 1000.0}
    return n2o, d


@lru_cache(maxsize=64)
def _rh_cached(crop, eps_max, k_peat, Q10_h):
    rh = simulate(crop, eps_max, k_peat, Q10_h)["Rh"]
    rh.setflags(write=False)
    return rh


def rh_daily(crop, co2_pars=None):
    """Daily heterotrophic respiration for a crop from the CO2 model (g C m-2 d-1)."""
    cp = dict(DEFAULT_CO2, **(co2_pars or {}))
    return _rh_cached(crop, float(cp["eps_max"]), float(cp["k_peat"]), float(cp["Q10_h"]))


def daily_n2o(crop, p, co2_pars=None, nfert=None):
    cl = climate()
    n2o, _ = n2o_flux(p, cl["Tsoil"], cl["WTD"], rh_daily(crop, co2_pars),
                      nfert_daily(crop, nfert), CROP_N[crop]["mgmt"])
    return n2o


def annual_n2o_drivers(crop, p, Tsoil, WTD, Rh, nfert=None):
    """Annual N2O (kg N2O-N ha-1 yr-1) for a crop with explicit daily Tsoil, WTD and Rh."""
    v, _ = n2o_flux(p, np.asarray(Tsoil, float), np.asarray(WTD, float), np.asarray(Rh, float),
                    nfert_daily(crop, nfert), CROP_N[crop]["mgmt"])
    return float(v.mean() * MGD_TO_KGHAYR)


def annual_n2o(crop, p, co2_pars=None, nfert=None):
    """Annual N2O (kg N2O-N ha-1 yr-1) under the regional climatology."""
    return float(daily_n2o(crop, p, co2_pars, nfert).mean() * MGD_TO_KGHAYR)


def n2o_at_wtd(meanWTD, p, crop="Potato", co2_pars=None, lo=-0.15):
    """Annual N2O (kg N2O-N ha-1 yr-1) for a crop at a prescribed mean water table.

    ``lo`` caps how far above the surface the daily water table may rise: the notebook uses
    -0.15 m for the inventory comparison (Section 9) and 0.02 m for the scenario (Section 8).
    """
    from .ch4 import wtd_series  # local import keeps n2o free of a hard CH4 dependency

    cp = dict(DEFAULT_CO2, **(co2_pars or {}))
    cl = climate()
    WTD = wtd_series(meanWTD, lo)
    resp = dict(FIXED, k_peat=cp["k_peat"], Q10_h=cp["Q10_h"])
    Rh, _ = het_resp(resp, np.full(365, C_PEAT), np.full(365, C_RES), cl["Tsoil"],
                     np.maximum(WTD, 0.02))
    v, _ = n2o_flux(p, cl["Tsoil"], WTD, Rh, nfert_daily(crop), CROP_N[crop]["mgmt"])
    return float(v.mean() * MGD_TO_KGHAYR)


def calibrate(background_target=4.6, cropland_mean_target=16.28, ref_crop="Celery", base=None):
    """Return (params, ef_peat, ef_fert, effective EF1) anchored to the IPCC/UK Tier-2 targets."""
    base = dict(PARN if base is None else base)
    croplands = [c for c in CROPS if CROP_N[c]["mgmt"] >= 1.0]
    bg_unit = annual_n2o(ref_crop, dict(base, ef_peat=1.0, ef_fert=0.0))
    ef_peat = background_target / bg_unit
    bg = np.mean([annual_n2o(c, dict(base, ef_peat=ef_peat, ef_fert=0.0)) for c in croplands])
    fert_unit = np.mean([annual_n2o(c, dict(base, ef_peat=ef_peat, ef_fert=1.0))
                         for c in croplands]) - bg
    ef_fert = (cropland_mean_target - bg) / fert_unit
    eff_ef1 = (cropland_mean_target - bg) / np.mean([CROP_N[c]["Nfert"] for c in croplands])
    return dict(base, ef_peat=float(ef_peat), ef_fert=float(ef_fert)), float(ef_peat), \
        float(ef_fert), float(eff_ef1)


def calibrated_params():
    return calibrate()[0]


def decouple_check(ch4_params):
    """Confirm that running N2O leaves CO2 (NEE) and CH4 predictions bit-identical."""
    from .ch4 import annual_ch4

    co2_before = [round(simulate(c)["NEE"].mean(), 10) for c in CROPS]
    ch4_before = round(annual_ch4(0.5, ch4_params), 10)
    p = calibrated_params()
    _ = {c: annual_n2o(c, p) for c in CROPS}
    co2_after = [round(simulate(c)["NEE"].mean(), 10) for c in CROPS]
    ch4_after = round(annual_ch4(0.5, ch4_params), 10)
    return co2_before == co2_after, ch4_before == ch4_after


def make_synthetic(true_p, seed=1, rng=None):
    """Per-crop daily synthetic N2O: true model + heteroscedastic noise."""
    rng = np.random.default_rng(seed) if rng is None else rng
    obs = {}
    for c in CROPS:
        truth = daily_n2o(c, true_p)
        obs[c] = truth + rng.normal(0, 0.15 * np.abs(truth) + 0.3)
    return obs


def self_learn_n2o(obs, prior, epochs=25, scale_ef=None, seed=1, rng=None):
    """Stream daily N2O observations through RMSProp; return Polyak-averaged parameters.

    Pass the generator used by :func:`make_synthetic` as ``rng`` to reproduce the original
    module, which drew the noise and the shuffling from one stream.
    """
    rng = np.random.default_rng(seed) if rng is None else rng
    cl = climate()
    p = dict(prior)
    opt = RMSProp(lr=0.01)
    avg = {k: prior[k] for k in LEARNABLE}
    beta = 0.99
    scale_ef = scale_ef or prior["ef_peat"]
    rh = {c: rh_daily(c) for c in obs}
    nf = {c: nfert_daily(c) for c in obs}
    stream = [(c, d) for c in obs for d in range(len(obs[c]))]
    hist = {k: [] for k in LEARNABLE}
    for _ in range(epochs):
        rng.shuffle(stream)
        for c, d in stream:
            n2o, g = n2o_flux(p, cl["Tsoil"][d], cl["WTD"][d], rh[c][d], nf[c][d],
                              CROP_N[c]["mgmt"])
            e = obs[c][d] - n2o
            p["ef_peat"] = float(np.clip(opt.step("ep", p["ef_peat"], -(e * g["ef_peat"]),
                                                  scale_ef), 1e-4, 1.0))
            p["Q10_n2o"] = float(np.clip(opt.step("q", p["Q10_n2o"], -(e * g["Q10_n2o"]), 2.0),
                                         1.2, 5.0))
            for k in avg:
                avg[k] = beta * avg[k] + (1 - beta) * p[k]
        for k in avg:
            hist[k].append(float(avg[k]))
    learned = dict(prior)
    learned.update(avg)
    return learned, hist
