r"""CO2 module: GPP, autotrophic and heterotrophic respiration, NEE for drained peat under crops.

A tractable reduction of JULES-CROP (copied from ``peatland_pignn.py`` and
``peatland_crop_validation.py``):

  GPP  = eps_max * PAR * (1 - exp(-k_ext*LAI)) * exp(-((Tair-T_opt)/T_sig)^2) * beta
  Ra   = Rpm + Rpg,  Rpm = r_m * C_veg * Q10_p**((Tair-Tref)/10),  Rpg = 0.25*max(GPP-Rpm, 0)
  Rh   = (k_peat*C_peat + k_res*C_res) * Q10_h**((Tsoil-Tref)/10) * fW(WTD)
         fW = clip(a_w + b_w*WTD, 0, 1)     (near-linear; Evans et al. 2021 / CEH Eq. 1)
  NEE  = Ra + Rh - GPP                       (positive = source to the atmosphere)

Dead plant material enters through the fast residue pool ``C_res``, which decomposes at rate
``k_res`` inside :func:`het_resp`. In the notebook configuration ``C_res`` is held at its
climatological mean (45 g C m-2). :func:`crop_step` holds the prognostic version (harvest
residue pulse and first-order decay) used by the spatial PI-GNN.

Units: fluxes g C m-2 d-1; annual budgets t C ha-1 yr-1.
"""

from __future__ import annotations

import numpy as np

TREF = 25.0          # reference temperature for Q10 terms [degC]
GAMMA_G = 0.25       # JULES growth-respiration fraction
GC_TO_TCHA = 1e-2    # g C m-2 -> t C ha-1
GC_TO_TCHA_YR = 365 * 1e-2   # mean g C m-2 d-1 -> t C ha-1 yr-1
CO2C_TO_CO2 = 44.0 / 12.0
DOY = np.arange(1, 366)


# --------------------------------------------------------------------------- #
# optimiser (shared by the self-learning of every gas)
# --------------------------------------------------------------------------- #
class RMSProp:
    def __init__(self, lr=0.01, decay=0.9, eps=1e-8):
        self.lr, self.decay, self.eps = lr, decay, eps
        self._c = {}

    def step(self, name, value, grad, scale=1.0):
        c = self.decay * self._c.get(name, 0.0) + (1 - self.decay) * grad ** 2
        self._c[name] = c
        return value - self.lr * scale * grad / (np.sqrt(c) + self.eps)


# --------------------------------------------------------------------------- #
# physics flux functions; each returns flux + partial derivatives wrt learnables
# --------------------------------------------------------------------------- #
def gpp_flux(p, LAI, PAR, Tair, beta):
    """Big-leaf LUE GPP. Learnable: eps_max, T_opt, k_ext."""
    fapar = 1.0 - np.exp(-p["k_ext"] * LAI)
    APAR = PAR * fapar
    fT = np.exp(-((Tair - p["T_opt"]) / p["T_sig"]) ** 2)
    GPP = p["eps_max"] * APAR * fT * beta
    d = {
        "eps_max": APAR * fT * beta,
        "T_opt": GPP * (2 * (Tair - p["T_opt"]) / p["T_sig"] ** 2),
        "k_ext": p["eps_max"] * fT * beta * PAR * (LAI * np.exp(-p["k_ext"] * LAI)),
    }
    return GPP, d


def plant_resp(p, GPP, C_veg, Tair):
    """JULES maintenance + growth respiration. Learnable: r_m, Q10_p."""
    q = p["Q10_p"] ** ((Tair - TREF) / 10.0)
    Rpm = p["r_m"] * C_veg * q
    active = (GPP > Rpm).astype(float)
    Rpg = GAMMA_G * np.maximum(GPP - Rpm, 0.0)
    Ra = Rpm + Rpg
    dRpm_drm = C_veg * q
    dRpm_dQ = p["r_m"] * C_veg * ((Tair - TREF) / 10.0) * p["Q10_p"] ** ((Tair - TREF) / 10.0 - 1)
    fac = 1.0 - GAMMA_G * active
    return Ra, {"r_m": dRpm_drm * fac, "Q10_p": dRpm_dQ * fac}


def het_resp(p, C_peat, C_res, Tsoil, WTD):
    """RothC/Q10 peat + residue oxidation gated by the water table.

    With ``b_w`` in ``p`` the water-table factor is the near-linear capped form
    fW = clip(a_w + b_w*WTD, 0, 1); otherwise the saturating form with ``k_w``.
    """
    fT = p["Q10_h"] ** ((Tsoil - TREF) / 10.0)
    substrate = p["k_peat"] * C_peat + p["k_res"] * C_res
    dfT_dQ = ((Tsoil - TREF) / 10.0) * p["Q10_h"] ** ((Tsoil - TREF) / 10.0 - 1)
    if "b_w" in p:
        lin = p["a_w"] + p["b_w"] * WTD
        fW = np.clip(lin, 0.0, 1.0)
        dfW = np.where((lin > 0.0) & (lin < 1.0), WTD, 0.0)
        wkey, wgrad = "b_w", substrate * fT * dfW
    else:
        fW = p["a_w"] + (1 - p["a_w"]) * WTD / (WTD + p["k_w"])
        dfW_dkw = (1 - p["a_w"]) * (-WTD / (WTD + p["k_w"]) ** 2)
        wkey, wgrad = "k_w", substrate * fT * dfW_dkw
    Rh = substrate * fT * fW
    return Rh, {"k_peat": C_peat * fT * fW, "Q10_h": substrate * fW * dfT_dQ, wkey: wgrad}


def crop_step(state, Tair, doy, NPP, params):
    """Advance prognostic crop and residue (dead plant) pools one day (JULES-CROP style).

    At harvest 25 % of vegetation carbon enters the fast residue pool ``C_res``, which then
    decays at ``res_turnover`` per day; its CO2 release is computed in :func:`het_resp`.
    """
    sow, harv = params["sow_doy"], params["harv_doy"]
    Tbase, gdd_mat, LAI_max = params["Tbase"], params["gdd_mature"], params["LAI_max"]
    growing = (doy >= sow) & (doy <= harv)
    just_sown = doy == sow
    state["GDD"] = np.where(just_sown, 0.0, state["GDD"])
    state["C_veg"] = np.where(just_sown, 1.0, state["C_veg"])
    dgdd = np.where(growing, np.maximum(Tair - Tbase, 0.0), 0.0)
    state["GDD"] = state["GDD"] + dgdd
    DVI = 2.0 * state["GDD"] / gdd_mat
    shape = np.where(growing & (DVI < 2.0), np.sin(np.pi * np.clip(DVI, 0.0, 2.0) / 2.0), 0.0)
    state["LAI"] = LAI_max * np.clip(shape, 0.0, 1.0)
    state["C_veg"] = np.where(growing, np.maximum(state["C_veg"] + np.maximum(NPP, 0) * 0.7, 1.0),
                              state["C_veg"])
    just_harv = doy == harv
    state["C_res"] = np.where(just_harv, state["C_res"] + 0.25 * state["C_veg"], state["C_res"])
    state["C_veg"] = np.where(just_harv, 1.0, state["C_veg"])
    state["LAI"] = np.where(just_harv, 0.0, state["LAI"])
    state["GDD"] = np.where(just_harv, 0.0, state["GDD"])
    state["C_res"] = np.maximum(state["C_res"] * (1 - params["res_turnover"]), 0.0)
    return state


# --------------------------------------------------------------------------- #
# UK-Fen regional climatology and crop phenology (peatland_crop_validation.py)
# --------------------------------------------------------------------------- #
def climate():
    d = DOY
    Tair = 10.5 + 6.7 * np.sin(2 * np.pi * (d - 115) / 365)
    Tsoil = 10.0 + 7.0 * np.sin(2 * np.pi * (d - 128) / 365)
    PAR = np.clip(5.6 + 4.8 * np.sin(2 * np.pi * (d - 172) / 365), 0.4, None)
    WTD = 0.55 + 0.35 * np.clip(np.sin(2 * np.pi * (d - 172) / 365), 0, None)
    beta = np.clip(0.95 - 0.25 * np.clip(np.sin(2 * np.pi * (d - 172) / 365), 0, None), 0.55, 1.0)
    return dict(Tair=Tair, Tsoil=Tsoil, PAR=PAR, WTD=WTD, beta=beta)


# sow, peak, harv in day of year; LAImax peak green area; base = year-round cover
CROPS = {
    "WW":      dict(peak=148, width=62, sow=1,   harv=220, LAImax=6.0, base=0.2),
    "Beet":    dict(peak=193, width=82, sow=95,  harv=305, LAImax=5.0, base=0.0),
    "Maize":   dict(peak=190, width=60, sow=130, harv=290, LAImax=4.6, base=0.0),
    "Potato":  dict(peak=200, width=52, sow=105, harv=260, LAImax=4.0, base=0.0),
    "Grass":   dict(peak=128, width=110, sow=1,  harv=365, LAImax=3.2, base=1.4),
    "Lettuce": dict(peak=168, width=100, sow=90, harv=275, LAImax=3.0, base=0.0),
    "Celery":  dict(peak=195, width=80, sow=120, harv=290, LAImax=3.0, base=0.0),
    "Leek":    dict(peak=212, width=78, sow=150, harv=330, LAImax=2.8, base=0.0),
    "Cabbage": dict(peak=200, width=95, sow=120, harv=330, LAImax=3.2, base=0.2),
    "Linseed": dict(peak=162, width=45, sow=95,  harv=215, LAImax=2.5, base=0.0),
}
CROP_NAMES = {"WW": "winter wheat", "Beet": "sugar beet", "Grass": "grassland (perennial)"}


def lai_curve(cp):
    d = DOY.astype(float)
    bump = cp["LAImax"] * np.exp(-0.5 * ((d - cp["peak"]) / cp["width"]) ** 2)
    inwin = (d >= cp["sow"]) & (d <= cp["harv"])
    return np.where(inwin, bump, 0.0) + cp["base"]


# fixed constants; a_w/b_w give the near-linear peat-oxidation water-table response
FIXED = dict(T_opt=18.0, k_ext=0.50, T_sig=12.0, a_w=0.245, b_w=0.89, k_res=0.020,
             r_m=4.0e-3, Q10_p=2.0, k_w=0.30)
C_PEAT = 1.2e5      # g C m-2
C_RES = 45.0        # g C m-2, residue (dead plant) pool, climatological mean

# learnable CO2 parameters as used throughout the notebook
DEFAULT_CO2 = dict(eps_max=1.6, k_peat=1.2e-4, Q10_h=2.3)


def simulate(crop, eps_max=1.6, k_peat=1.2e-4, Q10_h=2.3, WTD=None):
    """Daily CO2 fluxes for one crop year (g C m-2 d-1). ``WTD`` overrides the climatology."""
    cl = climate()
    LAI = lai_curve(CROPS[crop])
    wtd = cl["WTD"] if WTD is None else np.asarray(WTD, float)
    photo = dict(FIXED, eps_max=eps_max)
    resp = dict(FIXED, k_peat=k_peat, Q10_h=Q10_h)
    GPP, _ = gpp_flux(photo, LAI, cl["PAR"], cl["Tair"], cl["beta"])
    C_veg = 40.0 * LAI
    Ra, _ = plant_resp(resp, GPP, C_veg, cl["Tair"])
    Rh, _ = het_resp(resp, np.full(365, C_PEAT), np.full(365, C_RES), cl["Tsoil"], wtd)
    Reco = Ra + Rh
    return dict(GPP=GPP, Ra=Ra, Rh=Rh, Reco=Reco, NEE=Reco - GPP, LAI=LAI, WTD=wtd)


def annual_budget(sim):
    """Annual means of a :func:`simulate` result in t C ha-1 yr-1."""
    return {k: float(sim[k].mean() * GC_TO_TCHA_YR) for k in ("GPP", "Ra", "Rh", "Reco", "NEE")}
