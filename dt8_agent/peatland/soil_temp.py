"""Air-to-soil temperature transfer function (Section 3b of the standalone CH4 notebook).

Empirical model of Dolschak, Gartner & Berger (2015), Modeling Earth Systems and Environment 1:32.
It converts a daily mean air-temperature series into soil temperature at a chosen depth, treating
the soil as a store that relaxes towards an "environmental" temperature, with a slower
air-temperature memory for the phase lag and weaker coupling when the soil is cold or freezing.

No UK-calibrated set has been published; recalibrate against paired air and soil temperature from a
nearby COSMOS-UK station with :func:`fit_tsoil_params` before relying on derived soil temperatures.
"""

from __future__ import annotations

import numpy as np

TSOIL_PARAMS = {
    # Dolschak et al. (2015) Table 2, depth 10 cm. lambdas [-] per day, T0/T1/T_corr [degC], pc [-].
    "open_sod_10cm": dict(lam_max=0.7111, lam_shift=0.0974, lam_frost=0.0009, lam_thaw=0.1094,
                          T0=-0.8, T1=7.3, T_corr=118.1, pc_corr=0.012, pc_air=0.495),
    "temperate_forest_10cm": dict(lam_max=0.3949, lam_shift=0.0244, lam_frost=0.0130,
                                  lam_thaw=0.1374, T0=1.6, T1=6.2, T_corr=7.9, pc_corr=0.151,
                                  pc_air=0.500),
}
TSOIL_DEFAULT = "open_sod_10cm"

TSOIL_BOUNDS = dict(lam_max=(0.05, 1.0), lam_shift=(0.005, 0.2), lam_frost=(0.0, 0.1),
                    lam_thaw=(0.005, 0.7), T0=(-4.0, 3.0), T1=(3.0, 14.0), T_corr=(-20.0, 450.0),
                    pc_corr=(0.0, 0.4), pc_air=(0.05, 0.7))


def air_to_soil_temperature(Tair, p=None, T_init=8.0, spinup=150):
    """Daily soil temperature [degC] from daily mean air temperature [degC] (Eqs 1-8).

    The first ``spinup`` days of the series are recycled as spin-up, as in the paper.
    """
    p = TSOIL_PARAMS[TSOIL_DEFAULT] if p is None else p
    Tair = np.asarray(Tair, float)
    forcing = np.concatenate([Tair[:spinup], Tair])
    pc_shift = 1.0 - p["pc_air"] - p["pc_corr"]
    k_shift = np.exp(-p["lam_shift"])
    Ts = Tsh = T_init
    out = np.empty(len(forcing))
    for t, ta in enumerate(forcing):
        Tsh = ta + (Tsh - ta) * k_shift
        Tenv = p["pc_air"] * ta + pc_shift * Tsh + p["pc_corr"] * p["T_corr"]
        dT = Tenv - Ts
        lam_min = p["lam_thaw"] if dT > 0 else p["lam_frost"]
        if Ts <= p["T0"]:
            lam = lam_min
        elif Ts >= p["T1"]:
            lam = p["lam_max"]
        else:
            x = (Ts - p["T0"]) / (p["T1"] - p["T0"])
            lam = lam_min + (p["lam_max"] - lam_min) * (3 * x * x - 2 * x ** 3)
        Ts = Tenv - dT * np.exp(-lam)
        out[t] = Ts
    return out[spinup:]


def nse(sim, obs):
    sim, obs = np.asarray(sim, float), np.asarray(obs, float)
    return float(1 - np.sum((sim - obs) ** 2) / np.sum((obs - obs.mean()) ** 2))


def fit_tsoil_params(Tair, Tsoil_obs, p0=None, n_iter=3000, seed=0):
    """Calibrate the transfer function to paired daily air/soil temperature by maximising NSE.

    Bounded Nelder-Mead in normalised parameter space; NaN in ``Tsoil_obs`` are skipped.
    Returns (parameters, NSE).
    """
    keys = list(TSOIL_BOUNDS)
    lo = np.array([TSOIL_BOUNDS[k][0] for k in keys])
    hi = np.array([TSOIL_BOUNDS[k][1] for k in keys])
    p0 = TSOIL_PARAMS[TSOIL_DEFAULT] if p0 is None else p0
    Tsoil_obs = np.asarray(Tsoil_obs, float)
    ok = ~np.isnan(Tsoil_obs)

    def to_p(u):
        p = dict(zip(keys, (lo + np.clip(u, 0, 1) * (hi - lo)).tolist()))
        if p["pc_air"] + p["pc_corr"] > 0.98:
            p["pc_corr"] = 0.98 - p["pc_air"]
        return p

    def cost(u):
        return 1 - nse(air_to_soil_temperature(Tair, to_p(u))[ok], Tsoil_obs[ok])

    rng = np.random.default_rng(seed)
    n = len(keys)
    u0 = np.clip((np.array([p0[k] for k in keys]) - lo) / (hi - lo), 0, 1)
    simplex = [u0] + [np.clip(u0 + 0.1 * np.eye(n)[i] * rng.choice([-1, 1]), 0, 1)
                      for i in range(n)]
    f = [cost(s) for s in simplex]
    for _ in range(n_iter):
        order = np.argsort(f)
        simplex = [simplex[i] for i in order]
        f = [f[i] for i in order]
        centroid = np.mean(simplex[:-1], axis=0)
        xr = np.clip(centroid + (centroid - simplex[-1]), 0, 1)
        fr = cost(xr)
        if fr < f[0]:
            xe = np.clip(centroid + 2 * (centroid - simplex[-1]), 0, 1)
            fe = cost(xe)
            simplex[-1], f[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < f[-2]:
            simplex[-1], f[-1] = xr, fr
        else:
            xc = np.clip(centroid + 0.5 * (simplex[-1] - centroid), 0, 1)
            fc = cost(xc)
            if fc < f[-1]:
                simplex[-1], f[-1] = xc, fc
            else:
                simplex = [simplex[0]] + [simplex[0] + 0.5 * (s - simplex[0]) for s in simplex[1:]]
                f = [f[0]] + [cost(s) for s in simplex[1:]]
        if np.std(f) < 1e-9:
            break
    best = simplex[int(np.argmin(f))]
    return to_p(best), 1 - min(f)
