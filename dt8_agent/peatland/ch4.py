r"""CH4 module, in the configuration of Section 14 of the standalone CH4 notebook.

Source: ``peatland_ch4_model_with_litter_extension.ipynb`` (the standalone methane submodel of the
peatland twin), Sections 1-10 and the Section 14 extension (methane from vegetation killed by
flooding). The plant-functional-type extension of Section 15 and the model intercomparison of
Section 11 are not included.

Governing equations (WTD positive downward, metres; W = max(WTD, 0)):

    f_anox = exp(-W/z_p)        f_ox = 1 - exp(-W/z_o)
    S = 1 + c_s*LAI             f_T = Q10_CH4**((Tsoil-Tref)/10)
    P = k_prod * S * f_T * f_anox
    f_plant = p_aer * LAI/(LAI + k_lai)
    E = P*[f_plant + (1-f_plant)*(1-f_ox)]        U = u_atm*f_ox
    F_CH4 = E - U                                 (positive = emission)

Section 14 adds a labile litter pool L [g C m-2] fed by flood-intolerant vegetation killed by
standing water, whose decomposition yields extra CH4 on the same escape pathways:

    dL/dt = m_max*min(max(-WTD,0)/h_kill, 1)*c_B*LAI - k_L*Q10_L**((Tsoil-10)/10)*L
    P_L   = Y_CH4 * 16/12 * k_L*Q10_L**((Tsoil-10)/10)*L

Units: mg CH4 m-2 d-1 in the code; annual kg CH4 ha-1 yr-1; SI conversions provided.
"""

from __future__ import annotations

import numpy as np

from .co2 import (
    C_PEAT,
    C_RES,
    FIXED,
    GC_TO_TCHA_YR,
    RMSProp,
    climate,
    gpp_flux,
    het_resp,
    plant_resp,
)
from .co2 import CROPS as CO2_CROPS
from .co2 import lai_curve as co2_lai_curve

# --------------------------------------------------------------------------- #
# 1. units
# --------------------------------------------------------------------------- #
M_CH4 = 16.04e-3                       # kg mol-1
SECONDS_PER_DAY = 86400.0
DAYS_PER_YEAR = 365.0
MGD_TO_KGHAYR = 3.65                   # mg m-2 d-1 -> kg ha-1 yr-1
MGD_TO_KG_M2_S = 1e-6 / SECONDS_PER_DAY
MGD_TO_MOL_M2_S = MGD_TO_KG_M2_S / M_CH4
MGD_TO_NMOL_M2_S = MGD_TO_MOL_M2_S * 1e9
GWP_CH4 = 27.0                         # IPCC AR6 GWP100, non-fossil
CO2C_TO_CO2 = 44.0 / 12.0

# --------------------------------------------------------------------------- #
# 2. parameters
# --------------------------------------------------------------------------- #
TREF = 25.0
C_SUBSTRATE = 0.6
FIXED_CH4 = dict(z_p=0.14, z_o=0.12, p_aer=0.45, k_lai=2.0, u_atm=0.45)
TRUE_CH4 = dict(k_prod=4.6, Q10_CH4=3.6, **FIXED_CH4)   # k_prod placeholder, see calibrated_params
LEARNABLE = ("k_prod", "Q10_CH4")
WTD_ANCHOR, CH4_ANCHOR = 0.115, 110.0                    # m, kg CH4 ha-1 yr-1 (rewetted fen)

# --------------------------------------------------------------------------- #
# 3. drivers
# --------------------------------------------------------------------------- #
DOY = np.arange(1, 366)


def soil_temperature(doy=DOY):
    """UK Fens soil-temperature climatology [degC]: mean 10, amplitude 7, peak ~ early August."""
    return 10.0 + 7.0 * np.sin(2 * np.pi * (np.asarray(doy) - 128) / 365)


def air_temperature(doy=DOY):
    """UK Fens daily mean air-temperature climatology [degC]."""
    return 10.5 + 6.7 * np.sin(2 * np.pi * (np.asarray(doy) - 115) / 365)


def water_table(mean_wtd, doy=DOY, drawdown_amp=0.30, lo=-0.15, hi=1.6):
    """Daily water-table depth [m, positive below surface] for an annual mean depth [m]."""
    drawdown = drawdown_amp * np.clip(np.sin(2 * np.pi * (np.asarray(doy) - 172) / 365), 0, None)
    return np.clip(mean_wtd + drawdown - 0.10, lo, hi)


def wtd_series(meanWTD, lo=-0.15):
    """Alias of :func:`water_table` used by the coupled three-gas code."""
    return water_table(meanWTD, lo=lo)


# 14 land-cover classes of the twin (green LAI phenology)
CROPS = {
    "Upland_grass":   dict(peak=195, width=60,  sow=1,   harv=365, LAImax=1.5, base=0.5),
    "Grass_grazed":   dict(peak=140, width=100, sow=1,   harv=365, LAImax=1.8, base=1.2),
    "Grass_ungrazed": dict(peak=150, width=75,  sow=1,   harv=365, LAImax=3.5, base=1.0),
    "Winter_cereal":  dict(peak=145, width=45,  sow=1,   harv=215, LAImax=5.5, base=0.0,
                           autumn_sow=280, winter_lai=0.6),
    "Spring_cereal":  dict(peak=170, width=30,  sow=75,  harv=235, LAImax=4.5, base=0.0),
    "Maize":          dict(peak=215, width=40,  sow=125, harv=290, LAImax=4.0, base=0.0),
    "OSR":            dict(peak=110, width=35,  sow=1,   harv=200, LAImax=4.5, base=0.0,
                           autumn_sow=240, winter_lai=1.2),
    "Peas":           dict(peak=165, width=28,  sow=75,  harv=215, LAImax=4.0, base=0.0),
    "Potato":         dict(peak=195, width=35,  sow=110, harv=265, LAImax=4.0, base=0.0),
    "Beet":           dict(peak=215, width=55,  sow=90,  harv=300, LAImax=5.0, base=0.0),
    "Lettuce":        dict(peak=168, width=100, sow=90,  harv=275, LAImax=3.0, base=0.0),
    "Flax":           dict(peak=170, width=28,  sow=95,  harv=205, LAImax=4.5, base=0.0),
    "Linseed":        dict(peak=175, width=35,  sow=95,  harv=240, LAImax=2.8, base=0.0),
    "Fallow":         dict(peak=190, width=70,  sow=1,   harv=365, LAImax=1.5, base=0.3),
}
CROP_LABELS = {"Upland_grass": "Upland peatland grassland", "Grass_grazed": "Grassland, grazed",
               "Grass_ungrazed": "Grassland, ungrazed", "Winter_cereal": "Winter wheat / barley",
               "Spring_cereal": "Spring wheat / barley", "Maize": "Maize", "OSR": "Oilseed rape",
               "Peas": "Peas", "Potato": "Potato", "Beet": "Sugar beet", "Lettuce": "Lettuce",
               "Flax": "Flax", "Linseed": "Linseed", "Fallow": "Fallow land",
               "reed": "Reed / sedge (paludiculture, calibration canopy)"}
VEGETATION = ("reed",) + tuple(CROPS)

# Section 14 applies flood-kill litter only to flood-intolerant vegetation (sown grassland, arable
# crops, Phalaris). The notebook decides this from a site's species list; for the generic classes
# this mapping is used. Upland rough grazing and natural-regeneration fallow are treated as
# wetland-tolerant, and so is the reed calibration canopy, which keeps k_prod unchanged.
FLOOD_INTOLERANT_CLASSES = frozenset(
    {"Grass_grazed", "Grass_ungrazed", "Winter_cereal", "Spring_cereal", "Maize", "OSR", "Peas",
     "Potato", "Beet", "Lettuce", "Flax", "Linseed"})
FLOOD_INTOLERANT_SPECIES = ["phalaris", "lolium", "poa ", "poa)", "agrostis", "holcus",
                            "anthoxanthum", "maize", "barley", "wheat"]


def is_flood_intolerant(veg):
    """True for a flood-intolerant class code, or a species list naming flood-intolerant taxa."""
    if veg in FLOOD_INTOLERANT_CLASSES:
        return True
    if veg in CROPS or veg == "reed":
        return False
    t = str(veg).lower() + " "
    return any(k in t for k in FLOOD_INTOLERANT_SPECIES)


def lai_curve(cp, doy=DOY):
    d = np.asarray(doy).astype(float)
    g = np.exp(-0.5 * ((d - cp["peak"]) / cp["width"]) ** 2)
    if "autumn_sow" in cp:
        wl = cp["winter_lai"]
        spring = np.where(d < cp["peak"], wl + (cp["LAImax"] - wl) * g, cp["LAImax"] * g)
        lai = np.where(d <= cp["harv"], spring, 0.0)
        lai = lai + np.where(d >= cp["autumn_sow"],
                             wl * np.clip((d - cp["autumn_sow"]) / 45.0, 0, 1), 0.0)
        return lai + cp["base"]
    in_season = (d >= cp["sow"]) & (d <= cp["harv"])
    return np.where(in_season, cp["LAImax"] * g, 0.0) + cp["base"]


def veg_lai(veg="reed", doy=DOY):
    """Green LAI for 'reed', one of the 14 CH4 land-cover classes, or a coupled-twin crop code."""
    doy = np.asarray(doy)
    if veg == "reed":
        return 0.8 + 2.7 * np.exp(-0.5 * ((doy - 200) / 70) ** 2)
    if veg in CROPS:
        return lai_curve(CROPS[veg], doy)
    if veg in CO2_CROPS:                      # coupled-twin crop codes (e.g. "WW", "Grass")
        return co2_lai_curve(CO2_CROPS[veg])
    raise KeyError(f"unknown vegetation class {veg!r}; use 'reed' or one of {list(CROPS)}")


# --------------------------------------------------------------------------- #
# 4. flux function
# --------------------------------------------------------------------------- #
def substrate(LAI):
    return 1.0 + C_SUBSTRATE * LAI


def ch4_flux(p, Tsoil, WTD, LAI):
    """Net CH4 flux [mg m-2 d-1] and diagnostics, including gradients wrt k_prod and Q10_CH4."""
    S = substrate(LAI)
    Weff = np.maximum(WTD, 0.0)
    f_anox = np.exp(-Weff / p["z_p"])
    f_ox = 1.0 - np.exp(-Weff / p["z_o"])
    f_plant = p["p_aer"] * LAI / (LAI + p["k_lai"])
    Tfac = p["Q10_CH4"] ** ((Tsoil - TREF) / 10.0)
    P = p["k_prod"] * S * Tfac * f_anox
    escape = f_plant + (1.0 - f_plant) * (1.0 - f_ox)
    emis = P * escape
    uptake = p["u_atm"] * f_ox
    net = emis - uptake
    grad = {"k_prod": emis / p["k_prod"],
            "Q10_CH4": emis * ((Tsoil - TREF) / 10.0) / p["Q10_CH4"]}
    return net, dict(grad=grad, P=P, emis=emis, uptake=uptake, S=S, Tfac=Tfac,
                     f_ox=f_ox, f_anox=f_anox, f_plant=f_plant)


def daily_ch4(p, Tsoil, WTD, LAI):
    return ch4_flux(p, np.asarray(Tsoil, float), np.asarray(WTD, float), np.asarray(LAI, float))[0]


# --------------------------------------------------------------------------- #
# 6. annual budget and calibration
# --------------------------------------------------------------------------- #
def annual_ch4(mean_wtd, p, veg="reed"):
    """Annual net CH4 [kg CH4 ha-1 yr-1] of the base model (no litter pool)."""
    net, _ = ch4_flux(p, soil_temperature(), water_table(mean_wtd), veg_lai(veg))
    return float(net.mean() * MGD_TO_KGHAYR)


def calibrated_params(target_kg=CH4_ANCHOR, wtd_m=WTD_ANCHOR):
    """TRUE_CH4 with k_prod anchored to the rewetted-fen factor (reed at 11.5 cm -> 110 kg)."""
    base = annual_ch4(wtd_m, dict(TRUE_CH4, k_prod=1.0, u_atm=0.0))
    return dict(TRUE_CH4, k_prod=target_kg / base)


# --------------------------------------------------------------------------- #
# 7. validation against the UK Peatland Inventory
# --------------------------------------------------------------------------- #
TIER2_CLASSES = [("Near-natural fen", 2.6, 143.25), ("Rewetted fen", 11.5, 111.44),
                 ("Extensive grassland", 37.0, 35.91), ("Intensive grassland", 43.0, 29.03),
                 ("Cropland", 68.0, 1.96)]


def inventory_eq3(wtd_cm):
    """UK Inventory Eq. 3: CH4 [kg ha-1 yr-1] = 445.3 * 0.5**((WTD_cm + 5)/6.31)."""
    return 445.3 * 0.5 ** ((np.asarray(wtd_cm, float) + 5) / 6.31)


def skill(model, ref):
    model, ref = np.asarray(model, float), np.asarray(ref, float)
    return dict(bias=float(np.mean(model - ref)),
                rmse=float(np.sqrt(np.mean((model - ref) ** 2))),
                r=float(np.corrcoef(model, ref)[0, 1]),
                nse=float(1 - np.sum((model - ref) ** 2) / np.sum((ref - ref.mean()) ** 2)))


def inventory_validation(p):
    """Section 7: skill against Eq. 3 (5-70 cm and 20-70 cm) and the five Tier-2 classes."""
    w_cm = np.arange(5, 71, 5)
    m_curve = np.array([annual_ch4(w / 100, p) for w in w_cm])
    r_curve = inventory_eq3(w_cm)
    tab = [dict(peat_class=c, wtd_cm=w, ef_tier2=ef, model=annual_ch4(w / 100, p))
           for c, w, ef in TIER2_CLASSES]
    return dict(
        eq3_5_70cm=skill(m_curve, r_curve),
        eq3_20_70cm=skill(m_curve[w_cm >= 20], r_curve[w_cm >= 20]),
        tier2_classes=skill([t["model"] for t in tab], [t["ef_tier2"] for t in tab]),
        tier2_table=tab,
        curve=[dict(wtd_cm=float(w), model=float(m), eq3=float(r))
               for w, m, r in zip(w_cm, m_curve, r_curve)])


# --------------------------------------------------------------------------- #
# 9. user driver series, SI outputs, peat-depth / SOC validity flags
# --------------------------------------------------------------------------- #
WASTED_PEAT_DEPTH = 0.40     # m, UK 'wasted' peat (Evans et al., 2023)
SOC_MIN_PCT = 12.0           # % organic C, default organic-soil threshold


def validity_flags(WTD, peat_depth_m=None, SOC_pct=None, soc_min_pct=SOC_MIN_PCT):
    """Per-day flags (True = outside calibrated conditions). Flags never change the flux."""
    flags = {}
    if peat_depth_m is not None:
        D = np.broadcast_to(np.asarray(peat_depth_m, float), np.shape(WTD))
        flags["flag_wasted_peat"] = D < WASTED_PEAT_DEPTH
        flags["flag_wt_below_peat"] = np.asarray(WTD) > D
    if SOC_pct is not None:
        flags["flag_low_SOC"] = np.broadcast_to(np.asarray(SOC_pct, float) < soc_min_pct,
                                                np.shape(WTD))
    return flags


def f_anox_peat_capped(WTD, peat_depth, z_p):
    """Sensitivity option (off by default): production confined to anoxic peat above its base."""
    W = np.maximum(WTD, 0.0)
    D = np.asarray(peat_depth, float)
    return np.where(D > W, np.exp(-W / z_p) - np.exp(-D / z_p), 0.0)


def ch4_flux_peat_capped(p, Tsoil, WTD, LAI, peat_depth):
    """As :func:`ch4_flux` with the peat-capped anoxic factor (hypothesis test only)."""
    net, d = ch4_flux(p, Tsoil, WTD, LAI)
    f_anox = np.asarray(d["f_anox"], float)
    scale = np.divide(f_anox_peat_capped(WTD, peat_depth, p["z_p"]), f_anox,
                      out=np.zeros_like(f_anox), where=f_anox > 0)
    emis = d["emis"] * scale
    return emis - d["uptake"], dict(d, emis=emis, P=d["P"] * scale)


def to_si(flux_mg_m2_d):
    f = np.asarray(flux_mg_m2_d, float)
    return dict(kg_m2_s=f * MGD_TO_KG_M2_S, mol_m2_s=f * MGD_TO_MOL_M2_S,
                nmol_m2_s=f * MGD_TO_NMOL_M2_S)


def run_ch4(p, WTD, LAI, Tsoil=None, Tair=None, tsoil_params=None, peat_depth_m=None,
            SOC_pct=None, peat_capped=False, litter=None, flood_intolerant=False, L0=0.0):
    """Run CH4 on daily driver arrays (Section 9, with the optional Section 14 litter pool).

    Needs ``Tsoil`` or ``Tair`` (converted with the air-to-soil transfer function). Returns a dict
    of daily arrays in code units and SI, validity flags, and the litter pool at the end.
    """
    from .soil_temp import air_to_soil_temperature

    WTD = np.asarray(WTD, float)
    LAI = np.asarray(LAI, float)
    if Tsoil is None:
        if Tair is None:
            raise ValueError("give Tsoil or Tair")
        Tsoil = air_to_soil_temperature(Tair, tsoil_params)
    Tsoil = np.asarray(Tsoil, float)
    if peat_capped:
        if peat_depth_m is None:
            raise ValueError("peat_capped needs peat_depth_m")
        net, d = ch4_flux_peat_capped(p, Tsoil, WTD, LAI, peat_depth_m)
    else:
        net, d = ch4_flux(p, Tsoil, WTD, LAI)
    E_L, L_end = np.zeros_like(net), L0
    if litter is not None and flood_intolerant:
        E_L, L_end = litter_ch4(p, litter, Tsoil, WTD, LAI, L0)
    total = net + E_L
    return dict(Tsoil=Tsoil, production=d["P"], emission=d["emis"], uptake=d["uptake"],
                litter_emission=E_L, net=total, f_anox=d["f_anox"], f_ox=d["f_ox"],
                f_plant=d["f_plant"], si=to_si(total),
                flags=validity_flags(WTD, peat_depth_m, SOC_pct), litter_pool_end=float(L_end))


# --------------------------------------------------------------------------- #
# 10. self-learning
# --------------------------------------------------------------------------- #
def make_synthetic(p_true, seed=1):
    """Twelve plots across a drainage gradient (mean WTD 0.08-1.05 m), reed canopy, with noise."""
    rng = np.random.default_rng(seed)
    obs = []
    for w0 in np.linspace(0.08, 1.05, 12):
        WTD = water_table(w0, lo=0.03)
        Ts, LAI = soil_temperature(), veg_lai("reed")
        f, _ = ch4_flux(p_true, Ts, WTD, LAI)
        obs.append(dict(w0=float(w0), WTD=WTD, Tsoil=Ts, LAI=LAI,
                        ch4=f + rng.normal(0, 0.10 * np.abs(f) + 0.5)))
    return obs


def self_learn_ch4(obs, prior, epochs=20, lr=0.006, polyak=0.99, seed=0, scale_k=None):
    """RMSProp on the innovation of each observed day, Polyak-averaged estimate.

    ``scale_k`` is the typical magnitude of k_prod (the notebook uses the calibrated value).
    Returns (learned parameters, history starting with the prior).
    """
    SCALE = dict(k_prod=scale_k or prior["k_prod"], Q10_CH4=2.0)
    BOUNDS = dict(k_prod=(0.2, 1000.0), Q10_CH4=(1.2, 6.0))
    p, opt = dict(prior), RMSProp(lr=lr)
    avg = {k: prior[k] for k in LEARNABLE}
    hist = {k: [float(prior[k])] for k in LEARNABLE}
    order = [(s, d) for s in obs for d in range(len(s["ch4"]))]
    rng = np.random.default_rng(seed)
    for _ in range(epochs):
        rng.shuffle(order)
        for s, d in order:
            f, info = ch4_flux(p, s["Tsoil"][d], s["WTD"][d], s["LAI"][d])
            innov = s["ch4"][d] - f
            for k in LEARNABLE:
                p[k] = float(np.clip(opt.step(k, p[k], -innov * info["grad"][k], SCALE[k]),
                                     *BOUNDS[k]))
            for k in LEARNABLE:
                avg[k] = polyak * avg[k] + (1 - polyak) * p[k]
        for k in LEARNABLE:
            hist[k].append(float(avg[k]))
    learned = dict(prior)
    learned.update(avg)
    return learned, hist


# --------------------------------------------------------------------------- #
# 14. methane from vegetation killed by flooding (labile litter pool)
# --------------------------------------------------------------------------- #
LITTER = dict(Y_ch4=0.5, kL=float(np.log(2) / 365.0), Q10_L=3.0, TREF_L=10.0, cB=60.0,
              m_max=0.01, h_kill=0.10)


def litter_ch4(p, pl, Tsoil, WTD, LAI, L0=0.0):
    """Extra CH4 from the flood-killed litter pool [mg CH4 m-2 d-1] and the pool at the end.

    Daily explicit step (k_L*dt << 1, stable). Pathways and oxidation as in the base model.
    """
    WTD = np.asarray(WTD, float)
    LAI = np.asarray(LAI, float)
    Tsoil = np.asarray(Tsoil, float)
    W = np.maximum(WTD, 0.0)
    f_ox = 1.0 - np.exp(-W / p["z_o"])
    f_plant = p["p_aer"] * LAI / (LAI + p["k_lai"])
    L, E = float(L0), np.zeros(len(Tsoil))
    for d in range(len(Tsoil)):
        kill = pl["m_max"] * min(max(-WTD[d], 0.0) / pl["h_kill"], 1.0) * pl["cB"] * LAI[d]
        dec = pl["kL"] * pl["Q10_L"] ** ((Tsoil[d] - pl["TREF_L"]) / 10.0) * L
        L += kill - dec
        P_L = pl["Y_ch4"] * dec * (16.0 / 12.0) * 1000.0
        E[d] = P_L * (f_plant[d] + (1 - f_plant[d]) * (1 - f_ox[d]))
    return E, L


def litter_annual(p, pl, Tsoil, WTD, LAI, prior_years=3):
    """Litter CH4 [kg ha-1 yr-1] in the year after ``prior_years`` years of the same regime."""
    L = 0.0
    for _ in range(prior_years):
        _, L = litter_ch4(p, pl, Tsoil, WTD, LAI, L)
    E, L_end = litter_ch4(p, pl, Tsoil, WTD, LAI, L)
    return float(E.mean() * MGD_TO_KGHAYR), float(L), float(L_end)


def annual_ch4_components(mean_wtd, p, veg="reed", litter=LITTER, years_since_rewetting=3):
    """Annual base and flood-litter CH4 [kg ha-1 yr-1] for a vegetation class and mean WTD.

    ``years_since_rewetting`` is the number of complete years the water regime has run before the
    simulated year (0 = first year after rewetting, pool starts empty; 3 = the notebook's spin-up
    for an established regime). Litter applies only to flood-intolerant vegetation.
    """
    Ts, WTD, LAI = soil_temperature(), water_table(mean_wtd), veg_lai(veg)
    base = float(ch4_flux(p, Ts, WTD, LAI)[0].mean() * MGD_TO_KGHAYR)
    lit, L_start, L_end = 0.0, 0.0, 0.0
    intolerant = is_flood_intolerant(veg)
    if litter is not None and intolerant:
        lit, L_start, L_end = litter_annual(p, litter, Ts, WTD, LAI, years_since_rewetting)
    return dict(base=base, litter=lit, total=base + lit, flood_intolerant=intolerant,
                litter_pool_start=L_start, litter_pool_end=L_end)


# --------------------------------------------------------------------------- #
# coupled twin: CO2 (NEE) response to the water table (peatland_methane.py)
# --------------------------------------------------------------------------- #
CO2_PARS = dict(k_peat=1.2e-4, Q10_h=2.3, eps_max=1.45)


def annual_nee(meanWTD, veg="reed", co2_pars=None):
    """Annual NEE [t C ha-1 yr-1] at a mean water table, with waterlogging stress on GPP."""
    cp = dict(CO2_PARS, **(co2_pars or {}))
    cl = climate()
    WTD = water_table(meanWTD)
    LAI = veg_lai(veg)
    photo = dict(FIXED, eps_max=cp["eps_max"])
    resp = dict(FIXED, k_peat=cp["k_peat"], Q10_h=cp["Q10_h"])
    GPP, _ = gpp_flux(photo, LAI, cl["PAR"], cl["Tair"], cl["beta"])
    GPP = GPP * np.clip((WTD + 0.05) / 0.25, 0.40, 1.0)
    Ra, _ = plant_resp(resp, GPP, 40 * LAI, cl["Tair"])
    Rh, _ = het_resp(resp, np.full(365, C_PEAT), np.full(365, C_RES), cl["Tsoil"],
                     np.maximum(WTD, 0.02))
    return float(((Ra + Rh) - GPP).mean() * GC_TO_TCHA_YR)
