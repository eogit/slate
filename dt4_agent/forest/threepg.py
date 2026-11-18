"""Process-based growth: the 3-PG model (Landsberg & Waring 1997; Sands & Landsberg 2002).

3-PG (Physiological Principles Predicting Growth) runs on a monthly time step. Absorbed
light drives gross primary production through a canopy quantum efficiency that is reduced by
temperature, frost, vapour-pressure deficit, soil water, nutrition and stand age. A fixed
fraction of GPP becomes NPP, which is partitioned between roots, foliage and stems; foliage
falls as litter, roots turn over, and trees die by self-thinning. This implementation follows
the equations of 3-PGpjs (Sands 2010) closely and keeps their parameter names
(:mod:`forest.species`), with three simplifications:

* one even-aged cohort; no separate branch-and-bark pool (the stem pool ``WS`` includes
  branches and bark, which matches the ESA CCI definition of AGB);
* soil water is a single bucket filled by rain and emptied by Penman-Monteith transpiration
  and canopy interception; there is no drainage below the root zone except overflow;
* deciduous species (oak) intercept light with a monthly leaf-on fraction instead of an
  explicit leaf-flush and leaf-fall model.

**Calibrated parameter.** The fertility rating ``FR`` (0-1) scales nutrition, which sets both
the quantum efficiency and root partitioning. It is the 3-PG counterpart of yield class and
is the parameter DT4 calibrates to Biomass CCI v7 per landscape.

The model is vectorised over ensemble members: every state variable is a numpy array, so one
call simulates many members (or many fertility ratings) at once.
"""

from __future__ import annotations

import math

import numpy as np

from . import species as sp
from .landscapes import DAYS_IN_MONTH, Landscape

# physical constants as in 3-PGpjs
MOL_PAR_PER_MJ = 2.3     # mol PAR per MJ of global radiation
G_DM_PER_MOL_C = 24.0    # g dry matter per mol C
QA, QB = -90.0, 0.8      # net radiation = QA + QB * global radiation (W/m2)
E20 = 2.2                # rate of change of saturated VP with T at 20 C
RHO_AIR = 1.2            # kg/m3
LAMBDA = 2_460_000.0     # latent heat of vaporisation, J/kg
VPD_CONV = 0.000622      # mbar to kg/kg

# soil texture constants (SWconst, SWpower) from 3-PGpjs
SOIL = {"sand": (0.70, 9.0), "sandy_loam": (0.60, 7.0), "clay_loam": (0.50, 5.0),
        "clay": (0.40, 3.0)}

LEAF_ON = np.array([0, 0, 0, 0.3, 1, 1, 1, 1, 1, 0.6, 0.1, 0], dtype=float)  # deciduous

# seedling pools at planting (t DM/ha)
PLANT_WF, PLANT_WR, PLANT_WS = 0.5, 0.25, 0.5


def _sat_vp(t):
    """Saturated vapour pressure (mbar) at temperature t (C)."""
    return 6.1078 * np.exp(17.269 * t / (237.3 + t))


def day_length_s(latitude: float, month_index: int) -> float:
    """Mean day length (s) in the middle of a month at a latitude (3-PGpjs formula)."""
    doy = 30.4 * month_index + 15.0
    sin_lat = math.sin(math.radians(latitude))
    cos_lat = math.cos(math.radians(latitude))
    sin_dec = 0.4 * math.sin(0.0172 * (doy - 80.0))
    cosh = -0.0145 / cos_lat / math.sqrt(1 - sin_dec ** 2) - sin_lat * sin_dec / cos_lat / math.sqrt(1 - sin_dec ** 2)
    cosh = min(1.0, max(-1.0, cosh))
    return 86400.0 * math.acos(cosh) / math.pi


class ThreePGModel:
    """3-PG stand model, monthly inside an annual ``step``, vectorised over members.

    State: ``age`` (years), ``WF``, ``WR``, ``WS`` (foliage, root, stem pools in t DM/ha),
    ``N`` (stems/ha), ``ASW`` (available soil water, mm) and ``FR`` (fertility rating).
    """

    name = "3pg"
    productivity_name = "fertility_rating"
    productivity_unit = "dimensionless, 0 (very poor) to 1 (no nutrient limitation)"

    def __init__(self, species: str, landscape: Landscape, climate_shift_c: float = 0.0,
                 rain_factor: float = 1.0):
        self.species = species
        self.sp = sp.get(species)
        self.p = dict(self.sp.threepg)
        self.landscape = landscape
        c = landscape.climate
        self.tmax = np.array(c.tmax_c, dtype=float) + climate_shift_c
        self.tmin = np.array(c.tmin_c, dtype=float) + climate_shift_c
        self.tav = 0.5 * (self.tmax + self.tmin)
        self.rain = np.array(c.rain_mm, dtype=float) * rain_factor
        self.rad = np.array(c.solar_mj_m2_d, dtype=float)
        self.frost = np.array(c.frost_days, dtype=float)
        self.vpd = 0.5 * (_sat_vp(self.tmax) - _sat_vp(self.tmin))  # mbar
        self.daylen = np.array([day_length_s(landscape.latitude, m) for m in range(12)])
        self.swconst, self.swpower = SOIL[landscape.soil_class]
        self.max_asw = landscape.max_asw_mm
        # temperature and frost modifiers depend only on climate
        p = self.p
        t = self.tav
        ft = ((t - p["Tmin"]) / (p["Topt"] - p["Tmin"])) * (
            (p["Tmax"] - t) / (p["Tmax"] - p["Topt"])) ** ((p["Tmax"] - p["Topt"]) / (p["Topt"] - p["Tmin"]))
        self.fT = np.where((t <= p["Tmin"]) | (t >= p["Tmax"]), 0.0, np.nan_to_num(ft))
        self.fFrost = 1.0 - p["kF"] * self.frost / np.array(DAYS_IN_MONTH, dtype=float)
        self.fVPD = np.exp(-p["CoeffCond"] * self.vpd)

    # ------------------------------------------------------------------ setup
    def theta_grid(self) -> np.ndarray:
        return np.round(np.arange(0.0, 1.0001, 0.05), 2)

    def theta_default(self) -> float:
        return 0.5

    def _planted(self, theta) -> dict:
        theta = np.atleast_1d(np.asarray(theta, dtype=float))
        n = theta.size
        return {"age": np.zeros(n), "WF": np.full(n, PLANT_WF), "WR": np.full(n, PLANT_WR),
                "WS": np.full(n, PLANT_WS), "N": np.full(n, self.p["stems_planted"]),
                "ASW": np.full(n, self.max_asw), "FR": theta.copy()}

    def init(self, age, theta, agb0=None) -> dict:
        """Plant and grow to ``age`` (spin-up). If ``agb0`` is given, scale pools to it."""
        age = np.atleast_1d(np.asarray(age, dtype=float))
        theta = np.atleast_1d(np.asarray(theta, dtype=float))
        n = max(age.size, theta.size, 1 if agb0 is None else np.atleast_1d(agb0).size)
        age = np.broadcast_to(age, (n,))
        state = self._planted(np.broadcast_to(theta, (n,)))
        target = np.floor(age).astype(int)
        for yr in range(int(target.max()) if n else 0):
            grow = target > yr
            if not grow.any():
                break
            snap = {k: v.copy() for k, v in state.items()}
            self.step(state)
            for k in state:  # members that reached their age stop growing
                state[k] = np.where(grow, state[k], snap[k])
        if agb0 is not None:
            scale = np.where(state["WS"] > 1e-9,
                             np.broadcast_to(np.asarray(agb0, dtype=float), (n,)) / np.maximum(state["WS"], 1e-9), 1.0)
            for k in ("WS", "WF", "WR"):
                state[k] = state[k] * scale
        return state

    def agb(self, state) -> np.ndarray:
        return state["WS"].copy()

    # ------------------------------------------------------------------ dynamics
    def step(self, state, year_index: int = 0) -> dict:
        """Run 12 months. Returns annual litterfall and mortality (t DM/ha/yr) per member."""
        p = self.p
        litter = np.zeros_like(state["WS"])
        mortality = np.zeros_like(state["WS"])
        pfs_power = math.log(p["pFS20"] / p["pFS2"]) / math.log(10.0)
        pfs_const = p["pFS2"] / 2.0 ** pfs_power
        m = p["m0"] + (1.0 - p["m0"]) * state["FR"]
        f_nutr = 1.0 - (1.0 - p["fN0"]) * (1.0 - state["FR"]) ** p["fNn"]
        for mo in range(12):
            age = state["age"]
            days = DAYS_IN_MONTH[mo]
            N = np.maximum(state["N"], 1.0)
            # canopy
            sla = p["SLA1"] + (p["SLA0"] - p["SLA1"]) * np.exp(-math.log(2.0) * (age / p["tSLA"]) ** 2)
            lai = state["WF"] * sla * 0.1
            if p["deciduous"]:
                lai = lai * LEAF_ON[mo]
            can_cover = np.minimum(1.0, (age + 0.01) / p["fullCanAge"])
            light_int = (1.0 - np.exp(-p["k"] * lai / np.maximum(can_cover, 1e-6))) * can_cover
            # modifiers
            f_age = 1.0 / (1.0 + ((age / p["MaxAge"]) / p["rAge"]) ** p["nAge"])
            f_sw = 1.0 / (1.0 + ((1.0 - state["ASW"] / self.max_asw) / self.swconst) ** self.swpower)
            phys = np.minimum(self.fVPD[mo], f_sw) * f_age
            alpha_c = p["alphaCx"] * f_nutr * self.fT[mo] * max(self.fFrost[mo], 0.0) * phys
            # production
            rad_month = self.rad[mo] * days                       # MJ/m2/month
            apar = rad_month * light_int * MOL_PAR_PER_MJ          # mol/m2/month
            gpp = alpha_c * apar * G_DM_PER_MOL_C / 100.0          # t DM/ha/month
            npp = gpp * p["Y"]
            # water balance: interception + Penman-Monteith transpiration
            intcptn = p["MaxIntcptn"] * np.minimum(1.0, lai / p["LAImaxIntcptn"])
            rain_in = self.rain[mo] * (1.0 - intcptn)
            g_c = p["MaxCond"] * phys * np.minimum(1.0, lai / p["LAIgcx"])
            net_rad = QA + QB * (self.rad[mo] * 1e6 / self.daylen[mo])
            def_term = RHO_AIR * LAMBDA * (VPD_CONV * self.vpd[mo]) * p["BLcond"]
            div = g_c * (1.0 + E20) + p["BLcond"]
            transp = np.maximum(g_c * (E20 * net_rad + def_term) / div / LAMBDA, 0.0)  # kg/m2/s
            transp_mm = transp * self.daylen[mo] * days
            asw = state["ASW"] + rain_in
            transp_mm = np.minimum(transp_mm, asw)
            state["ASW"] = np.clip(asw - transp_mm, 0.0, self.max_asw)
            # partitioning
            dbh = (np.maximum(state["WS"], 1e-9) * 1000.0 / N / p["aS"]) ** (1.0 / p["nS"])
            pfs = pfs_const * dbh ** pfs_power
            p_r = p["pRx"] * p["pRn"] / (p["pRn"] + (p["pRx"] - p["pRn"]) * phys * m)
            p_s = (1.0 - p_r) / (1.0 + pfs)
            p_f = 1.0 - p_r - p_s
            # turnover
            if p["deciduous"]:
                gamma_f = 1.0 / 12.0
            else:
                kg = 12.0 * math.log(1.0 + p["gammaF1"] / p["gammaF0"]) / p["tgammaF"]
                gamma_f = p["gammaF1"] * p["gammaF0"] / (
                    p["gammaF0"] + (p["gammaF1"] - p["gammaF0"]) * np.exp(-kg * age / 12.0))
            lit = gamma_f * state["WF"]
            root_loss = p["gammaR"] * state["WR"]
            state["WF"] = state["WF"] + npp * p_f - lit
            state["WR"] = state["WR"] + npp * p_r - root_loss
            state["WS"] = state["WS"] + npp * p_s
            litter += lit
            # self-thinning (-3/2 power law)
            dead_s = self._self_thin(state)
            mortality += dead_s
            state["age"] = age + 1.0 / 12.0
        return {"litterfall": litter, "mortality": mortality}

    def _self_thin(self, state) -> np.ndarray:
        """Kill trees until mean stem mass is under the self-thinning line. Returns dead WS."""
        p = self.p
        N = np.maximum(state["N"], 1.0)
        wsmax = p["wSx1000"] * (1000.0 / N) ** p["thinPower"]
        avws = state["WS"] * 1000.0 / N
        over = avws > wsmax
        dead_ws = np.zeros_like(N)
        if not over.any():
            return dead_ws
        ws = state["WS"]
        # 3-PGpjs getMortality: Newton iteration for the surviving stems n (thousands/ha)
        # solving wSx1000 * n**(1-thinPower) = x1*n + (1-mS)*WS with x1 = 1000*mS*WS/N
        n = N / 1000.0
        x1 = 1000.0 * p["mS"] * ws / N
        for _ in range(20):
            x2 = p["wSx1000"] * n ** (1.0 - p["thinPower"])
            fN = x2 - x1 * n - (1.0 - p["mS"]) * ws
            dfN = (1.0 - p["thinPower"]) * x2 / n - x1
            n = np.clip(n - fN / np.where(np.abs(dfN) > 1e-12, dfN, -1e-12), 1e-3, N / 1000.0)
        n = np.where(over, n * 1000.0, N)
        del_n = N - n
        dead_ws = np.where(over, p["mS"] * ws / N * del_n, 0.0)
        state["WF"] = state["WF"] - np.where(over, p["mF"] * state["WF"] / N * del_n, 0.0)
        state["WR"] = state["WR"] - np.where(over, p["mR"] * state["WR"] / N * del_n, 0.0)
        state["WS"] = ws - dead_ws
        state["N"] = n
        return dead_ws

    # ------------------------------------------------------------------ management
    def remove(self, state, fraction, rejuvenate: bool = False) -> np.ndarray:
        """Harvest ``fraction`` (0-1) of stems and pools. Returns removed AGB (t DM/ha)."""
        f = np.clip(np.broadcast_to(np.asarray(fraction, dtype=float), state["WS"].shape), 0, 1)
        removed = state["WS"] * f
        for k in ("WS", "WF", "WR"):
            state[k] = state[k] * (1.0 - f)
        state["N"] = np.maximum(state["N"] * (1.0 - f), 1.0)
        if rejuvenate:  # regeneration in gaps: effective age falls with the share removed
            state["age"] = state["age"] * (1.0 - f)
        return removed

    def replant(self, state, mask) -> None:
        mask = np.asarray(mask, dtype=bool)
        fresh = self._planted(state["FR"])
        for k in ("age", "WF", "WR", "WS", "N"):
            state[k] = np.where(mask, fresh[k], state[k])

    def agb_table(self, thetas, max_age: int = 200) -> np.ndarray:
        """AGB of unthinned stands, shape (len(thetas), max_age + 1), ages 0..max_age."""
        state = self._planted(np.asarray(thetas, dtype=float))
        out = np.empty((state["WS"].size, max_age + 1))
        out[:, 0] = state["WS"]
        for a in range(1, max_age + 1):
            self.step(state)
            out[:, a] = state["WS"]
        return out
