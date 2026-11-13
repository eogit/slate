"""DT8 agent: the drained-peatland greenhouse-gas twin (CO2, CH4, N2O) as an MCP server.

The physics lives in the ``peatland`` package next to this file, a server-safe copy of the
three-gas twin from eogit/digital_twin in the configuration of ``peatland_digital_twin.ipynb``.
An orchestrator (or any MCP client) can launch it over stdio:

    python dt8_agent/dt8_server.py

Run with ``--http`` to serve over streamable HTTP instead (default port 8000).

Learned parameters are kept per site. Set ``DT8_STATE_FILE`` to a JSON path to persist them
across restarts; without it they live only for the lifetime of the server process.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from peatland import ch4 as m_ch4  # noqa: E402
from peatland import co2 as m_co2  # noqa: E402
from peatland import inventory as m_inv  # noqa: E402
from peatland import n2o as m_n2o  # noqa: E402
from peatland.state import ParameterStore  # noqa: E402

VERSION = "0.1.0"
SOURCE = ("CO2 and N2O: eogit/digital_twin peatland_pignn.py (main), peatland_crop_validation.py "
          "and peatland_n2o.py (peatland-ghg-twin). CH4: standalone CH4 notebook "
          "peatland_ch4_model_with_litter_extension.ipynb, Sections 1-10 and 14 "
          "(flood-killed litter pool); no plant-functional-type extension")
CLIMATE = "UK Fens regional daily climatology (synthetic seasonal drivers, one representative year)"

store = ParameterStore(os.environ.get("DT8_STATE_FILE") or None)

Crop = Literal["WW", "Beet", "Maize", "Potato", "Grass", "Lettuce", "Celery", "Leek",
               "Cabbage", "Linseed"]
Vegetation = Literal["reed", "Upland_grass", "Grass_grazed", "Grass_ungrazed", "Winter_cereal",
                     "Spring_cereal", "Maize", "OSR", "Peas", "Potato", "Beet", "Lettuce", "Flax",
                     "Linseed", "Fallow"]
YearsSinceRewetting = Annotated[int, Field(
    ge=0, le=10, description="Complete years the water regime has run before the simulated year; "
                             "0 = first year after rewetting (litter pool starts empty), 3 = "
                             "established regime (the notebook's spin-up).")]
Site = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$",
                            description="Site or field id; each site keeps its own learned "
                                        "parameters. Defaults to 'default'.")]
MeanWTD = Annotated[float, Field(ge=-0.10, le=1.20,
                                 description="Annual mean water-table depth in metres below "
                                             "the surface (positive = below ground).")]


class Provenance(BaseModel):
    model: str = "DT8 peatland three-gas twin " + VERSION
    source: str = SOURCE
    drivers: str = CLIMATE
    parameters: str = Field(description="Where the parameter set came from.")
    gwp100: str = "IPCC AR6: CH4 27 (non-fossil), N2O 273"


def _prov(site: str, *gases: str) -> Provenance:
    return Provenance(parameters="; ".join(f"{g}: {store.source(g, site)}" for g in gases))


def _co2_kw(site: str) -> dict:
    p = store.get("co2", site)
    return {k: p[k] for k in ("eps_max", "k_peat", "Q10_h")}


server = MCPServer(
    name="dt8",
    instructions=(
        "DT8 peatland agent: greenhouse-gas fluxes from drained agricultural peat (East Anglian "
        "Fens). Simulates CO2 (GPP, respiration, NEE), CH4 and N2O per crop or water-table "
        "depth, the combined balance in CO2-equivalents, water-table management scenarios and "
        "a comparison with the UK Peatland Inventory. Sign convention: positive = emission to "
        "the atmosphere. Scenario outputs are management responses, not observations."),
    version=VERSION,
)


# --------------------------------------------------------------------------- #
# catalogue
# --------------------------------------------------------------------------- #
class CropInfo(BaseModel):
    code: str
    name: str
    sow_doy: int
    harvest_doy: int
    peak_lai: float
    fertiliser_n_kg_ha_yr: float
    peat_mineralisation_factor: float


class CH4ClassInfo(BaseModel):
    code: str
    name: str
    flood_intolerant: bool = Field(description="Receives flood-killed litter under standing "
                                               "water (Section 14).")
    mean_lai: float
    peak_lai: float


class CropList(BaseModel):
    crops: list[CropInfo] = Field(description="Crops of the CO2 and N2O modules (simulate_co2, "
                                              "annual_n2o, ghg_balance).")
    ch4_vegetation: list[CH4ClassInfo] = Field(description="Land-cover classes of the CH4 module "
                                                           "(annual_ch4, water_table_scenario).")


@server.tool(description="List the crops (CO2, N2O) and land-cover classes (CH4) DT8 knows.")
def list_crops() -> CropList:
    return CropList(
        crops=[CropInfo(code=c, name=m_co2.CROP_NAMES.get(c, c.lower()), sow_doy=cp["sow"],
                        harvest_doy=cp["harv"], peak_lai=cp["LAImax"] + cp["base"],
                        fertiliser_n_kg_ha_yr=m_n2o.CROP_N[c]["Nfert"],
                        peat_mineralisation_factor=m_n2o.CROP_N[c]["mgmt"])
               for c, cp in m_co2.CROPS.items()],
        ch4_vegetation=[CH4ClassInfo(code=v, name=m_ch4.CROP_LABELS[v],
                                     flood_intolerant=m_ch4.is_flood_intolerant(v),
                                     mean_lai=float(m_ch4.veg_lai(v).mean()),
                                     peak_lai=float(m_ch4.veg_lai(v).max()))
                        for v in m_ch4.VEGETATION])


# --------------------------------------------------------------------------- #
# CO2
# --------------------------------------------------------------------------- #
class DailySeries(BaseModel):
    doy: list[int]
    gpp: list[float]
    ra: list[float]
    rh: list[float]
    reco: list[float]
    nee: list[float]
    lai: list[float]
    wtd_m: list[float]


class CO2Result(BaseModel):
    crop: str
    gpp_tc_ha_yr: float
    ra_tc_ha_yr: float = Field(description="Autotrophic (plant) respiration.")
    rh_tc_ha_yr: float = Field(description="Heterotrophic respiration: peat and dead plant "
                                           "residue decomposition.")
    reco_tc_ha_yr: float
    nee_tc_ha_yr: float = Field(description="Net ecosystem exchange, positive = CO2 source.")
    nee_t_co2_ha_yr: float
    parameters: dict[str, float]
    daily_g_c_m2_d: DailySeries | None = None
    provenance: Provenance


@server.tool(description=(
    "Simulate one year of CO2 fluxes (GPP, Ra, Rh, Reco, NEE) for a crop on drained peat. "
    "Optionally prescribe the annual mean water table and return the daily series."))
def simulate_co2(
    crop: Crop,
    mean_wtd_m: Annotated[float | None, Field(
        ge=0.0, le=1.2, description="Annual mean water-table depth (m). Omit to use the "
                                    "drained Fenland climatology (mean ~0.66 m).")] = None,
    include_daily: bool = False,
    site: Site = "default",
) -> CO2Result:
    kw = _co2_kw(site)
    wtd = None if mean_wtd_m is None else m_ch4.wtd_series(mean_wtd_m, lo=0.02)
    sim = m_co2.simulate(crop, WTD=wtd, **kw)
    ann = m_co2.annual_budget(sim)
    daily = None
    if include_daily:
        r = lambda a: [round(float(x), 4) for x in a]  # noqa: E731
        daily = DailySeries(doy=list(range(1, 366)), gpp=r(sim["GPP"]), ra=r(sim["Ra"]),
                            rh=r(sim["Rh"]), reco=r(sim["Reco"]), nee=r(sim["NEE"]),
                            lai=r(sim["LAI"]), wtd_m=r(sim["WTD"]))
    return CO2Result(crop=crop, gpp_tc_ha_yr=ann["GPP"], ra_tc_ha_yr=ann["Ra"],
                     rh_tc_ha_yr=ann["Rh"], reco_tc_ha_yr=ann["Reco"], nee_tc_ha_yr=ann["NEE"],
                     nee_t_co2_ha_yr=ann["NEE"] * m_co2.CO2C_TO_CO2, parameters=kw,
                     daily_g_c_m2_d=daily, provenance=_prov(site, "co2"))


# --------------------------------------------------------------------------- #
# CH4
# --------------------------------------------------------------------------- #
class CH4Result(BaseModel):
    vegetation: str
    mean_wtd_m: float
    ch4_kg_ha_yr: float = Field(description="Net CH4 including flood-killed litter, positive = "
                                            "emission.")
    ch4_base_kg_ha_yr: float = Field(description="Base model (production, oxidation, plant "
                                                 "transport, uptake).")
    ch4_litter_kg_ha_yr: float = Field(description="Extra CH4 from vegetation killed by standing "
                                                   "water (Section 14).")
    ch4_t_co2e_ha_yr: float
    flood_intolerant: bool
    litter_pool_g_c_m2: float = Field(description="Litter pool at the end of the year.")
    parameters: dict[str, float]
    provenance: Provenance


@server.tool(description=(
    "Annual net CH4 at a mean water-table depth for a land-cover class ('reed' for rewetted "
    "paludiculture, or one of 14 grassland/arable/fallow classes). Includes the Section 14 pool "
    "of flood-killed litter for flood-intolerant vegetation under standing water."))
def annual_ch4(mean_wtd_m: MeanWTD, vegetation: Vegetation = "reed",
               include_flood_litter: bool = True, years_since_rewetting: YearsSinceRewetting = 3,
               site: Site = "default") -> CH4Result:
    p = store.get("ch4", site)
    c = m_ch4.annual_ch4_components(mean_wtd_m, p, vegetation,
                                    m_ch4.LITTER if include_flood_litter else None,
                                    years_since_rewetting)
    return CH4Result(vegetation=vegetation, mean_wtd_m=mean_wtd_m, ch4_kg_ha_yr=c["total"],
                     ch4_base_kg_ha_yr=c["base"], ch4_litter_kg_ha_yr=c["litter"],
                     ch4_t_co2e_ha_yr=c["total"] * m_ch4.GWP_CH4 / 1000,
                     flood_intolerant=c["flood_intolerant"],
                     litter_pool_g_c_m2=c["litter_pool_end"], parameters=p,
                     provenance=_prov(site, "ch4"))


class CH4Daily(BaseModel):
    tsoil_c: list[float]
    net_mg_m2_d: list[float]
    production_mg_m2_d: list[float]
    emission_mg_m2_d: list[float]
    uptake_mg_m2_d: list[float]
    litter_emission_mg_m2_d: list[float]
    net_kg_m2_s: list[float]
    net_nmol_m2_s: list[float]


class CH4RunResult(BaseModel):
    days: int
    net_kg_ch4_m2_yr: float = Field(description="SI annual total (scaled to 365 days).")
    net_kg_ch4_ha_yr: float
    net_t_co2e_ha_yr: float
    mean_flux_kg_m2_s: float
    peak_flux_nmol_m2_s: float
    litter_pool_end_g_c_m2: float
    flag_fractions: dict[str, float] = Field(description="Fraction of days outside calibrated "
                                                         "conditions (flags do not change the "
                                                         "flux).")
    soil_temperature_source: str
    daily: CH4Daily | None = None
    provenance: Provenance


@server.tool(description=(
    "Run the CH4 model on your own daily drivers (dipwell or EO water table, Sentinel-2 LAI, soil "
    "or air temperature) and return annual totals in SI and inventory units, validity flags for "
    "shallow peat or low SOC, and optionally the daily series. Air temperature is converted to "
    "soil temperature with the Dolschak et al. (2015) transfer function."))
def run_ch4_drivers(
    wtd_m: Annotated[list[Annotated[float, Field(ge=-1.0, le=3.0)]],
                     Field(min_length=30, max_length=3660,
                           description="Daily water-table depth, m, positive below surface "
                                       "(multiply FLUXNET-CH4 WTD by -1).")],
    lai: Annotated[list[Annotated[float, Field(ge=0, le=12)]],
                   Field(min_length=30, max_length=3660, description="Daily green LAI.")],
    tsoil_c: Annotated[list[Annotated[float, Field(ge=-30, le=45)]] | None,
                       Field(description="Daily soil temperature (5-10 cm), degC.")] = None,
    tair_c: Annotated[list[Annotated[float, Field(ge=-40, le=50)]] | None,
                      Field(description="Daily mean air temperature, degC; used if tsoil_c is "
                                        "omitted.")] = None,
    tsoil_parameter_set: Literal["open_sod_10cm", "temperate_forest_10cm"] = "open_sod_10cm",
    peat_depth_m: Annotated[float | None, Field(ge=0, le=20)] = None,
    soc_pct: Annotated[float | None, Field(ge=0, le=60)] = None,
    peat_capped: Annotated[bool, Field(description="Hypothesis test: confine production to "
                                                   "anoxic peat above its base.")] = False,
    flood_intolerant: Annotated[bool, Field(description="Vegetation is killed by standing water "
                                                        "(grassland, arable, Phalaris): "
                                                        "enables the litter pool.")] = False,
    litter_pool_start_g_c_m2: Annotated[float, Field(ge=0, le=5000)] = 0.0,
    include_daily: bool = False,
    site: Site = "default",
) -> CH4RunResult:
    from peatland.soil_temp import TSOIL_PARAMS

    n = len(wtd_m)
    for name, arr in (("lai", lai), ("tsoil_c", tsoil_c), ("tair_c", tair_c)):
        if arr is not None and len(arr) != n:
            raise ValueError(f"{name} has {len(arr)} days, wtd_m has {n}")
    if tsoil_c is None and tair_c is None:
        raise ValueError("give tsoil_c or tair_c")
    if peat_capped and peat_depth_m is None:
        raise ValueError("peat_capped needs peat_depth_m")
    out = m_ch4.run_ch4(store.get("ch4", site), wtd_m, lai, Tsoil=tsoil_c, Tair=tair_c,
                        tsoil_params=TSOIL_PARAMS[tsoil_parameter_set],
                        peat_depth_m=peat_depth_m, SOC_pct=soc_pct, peat_capped=peat_capped,
                        litter=m_ch4.LITTER, flood_intolerant=flood_intolerant,
                        L0=litter_pool_start_g_c_m2)
    years = n / m_ch4.DAYS_PER_YEAR
    tot = float(out["si"]["kg_m2_s"].sum() * m_ch4.SECONDS_PER_DAY / years)
    daily = None
    if include_daily:
        r = lambda a: [float(f"{x:.6g}") for x in a]  # noqa: E731
        daily = CH4Daily(tsoil_c=r(out["Tsoil"]), net_mg_m2_d=r(out["net"]),
                         production_mg_m2_d=r(out["production"]),
                         emission_mg_m2_d=r(out["emission"]), uptake_mg_m2_d=r(out["uptake"]),
                         litter_emission_mg_m2_d=r(out["litter_emission"]),
                         net_kg_m2_s=r(out["si"]["kg_m2_s"]),
                         net_nmol_m2_s=r(out["si"]["nmol_m2_s"]))
    return CH4RunResult(
        days=n, net_kg_ch4_m2_yr=tot, net_kg_ch4_ha_yr=tot * 1e4,
        net_t_co2e_ha_yr=tot * 1e4 * m_ch4.GWP_CH4 / 1000,
        mean_flux_kg_m2_s=float(out["si"]["kg_m2_s"].mean()),
        peak_flux_nmol_m2_s=float(out["si"]["nmol_m2_s"].max()),
        litter_pool_end_g_c_m2=out["litter_pool_end"],
        flag_fractions={k: float(np.mean(v)) for k, v in out["flags"].items()},
        soil_temperature_source="observed" if tsoil_c is not None
        else f"air temperature via Dolschak et al. (2015), {tsoil_parameter_set}",
        daily=daily, provenance=_prov(site, "ch4"))


# --------------------------------------------------------------------------- #
# N2O
# --------------------------------------------------------------------------- #
class N2OResult(BaseModel):
    crop: str
    fertiliser_n_kg_ha_yr: float
    n2o_kg_n_ha_yr: float = Field(description="kg N2O-N per hectare per year.")
    n2o_t_co2e_ha_yr: float
    parameters: dict[str, float]
    provenance: Provenance


@server.tool(description=(
    "Annual N2O emission for a crop on drained peat (peat-N mineralisation plus fertiliser), "
    "under the Fenland water-table climatology. Optionally override the fertiliser rate."))
def annual_n2o(
    crop: Crop,
    fertiliser_n_kg_ha_yr: Annotated[float | None, Field(
        ge=0, le=500, description="Annual fertiliser N. Omit for the crop's typical "
                                  "Fenland rate.")] = None,
    site: Site = "default",
) -> N2OResult:
    p = store.get("n2o", site)
    kg = m_n2o.annual_n2o(crop, p, store.get("co2", site), fertiliser_n_kg_ha_yr)
    nf = m_n2o.CROP_N[crop]["Nfert"] if fertiliser_n_kg_ha_yr is None else fertiliser_n_kg_ha_yr
    return N2OResult(crop=crop, fertiliser_n_kg_ha_yr=nf, n2o_kg_n_ha_yr=kg,
                     n2o_t_co2e_ha_yr=kg * m_n2o.N2ON_TO_N2O * m_n2o.GWP_N2O / 1000,
                     parameters=p, provenance=_prov(site, "co2", "n2o"))


# --------------------------------------------------------------------------- #
# three-gas balance and water-table scenarios
# --------------------------------------------------------------------------- #
class GHGBalance(BaseModel):
    crop: str
    co2_t_co2e_ha_yr: float
    ch4_t_co2e_ha_yr: float
    n2o_t_co2e_ha_yr: float
    net_t_co2e_ha_yr: float
    provenance: Provenance


@server.tool(description=(
    "Full greenhouse-gas balance (CO2 + CH4 + N2O in t CO2e/ha/yr, AR6 GWP100) for a crop "
    "under the current drained Fenland water-table regime."))
def ghg_balance(crop: Crop, site: Site = "default") -> GHGBalance:
    kw = _co2_kw(site)
    sim = m_co2.simulate(crop, **kw)
    e_co2 = sim["NEE"].mean() * m_co2.GC_TO_TCHA_YR * m_co2.CO2C_TO_CO2
    cl = m_co2.climate()
    ch4_kg = m_ch4.daily_ch4(store.get("ch4", site), cl["Tsoil"], cl["WTD"],
                             sim["LAI"]).mean() * m_ch4.MGD_TO_KGHAYR
    e_ch4 = ch4_kg * m_ch4.GWP_CH4 / 1000
    e_n2o = (m_n2o.annual_n2o(crop, store.get("n2o", site), kw)
             * m_n2o.N2ON_TO_N2O * m_n2o.GWP_N2O / 1000)
    return GHGBalance(crop=crop, co2_t_co2e_ha_yr=float(e_co2), ch4_t_co2e_ha_yr=float(e_ch4),
                      n2o_t_co2e_ha_yr=float(e_n2o), net_t_co2e_ha_yr=float(e_co2 + e_ch4 + e_n2o),
                      provenance=_prov(site, "co2", "ch4", "n2o"))


class ScenarioPoint(BaseModel):
    mean_wtd_m: float
    co2_t_co2e_ha_yr: float
    ch4_t_co2e_ha_yr: float
    n2o_t_co2e_ha_yr: float
    net_t_co2e_ha_yr: float


class WaterTableScenario(BaseModel):
    evidence_role: str = Field("response / scenario", description="Living Earth EBCF role: a "
                               "modelled management response, not an observed state.")
    crop_for_n2o: str
    vegetation_for_co2_ch4: str
    points: list[ScenarioPoint]
    optimum_wtd_m: float = Field(description="Water table with the lowest net GHG emission.")
    optimum_net_t_co2e_ha_yr: float
    provenance: Provenance


@server.tool(description=(
    "Water-table management scenario: three-gas balance (t CO2e/ha/yr) across mean water-table "
    "depths and the net-GHG optimum. CO2 and CH4 use rewetting vegetation (reed by default); "
    "N2O uses the named crop's fertiliser regime."))
def water_table_scenario(
    mean_wtd_m: Annotated[list[MeanWTD] | None, Field(
        min_length=2, max_length=200,
        description="Depths to evaluate (m). Omit for 45 depths from 0.02 to 1.05 m.")] = None,
    crop: Crop = "Potato",
    vegetation: Vegetation = "reed",
    include_flood_litter: bool = True,
    years_since_rewetting: YearsSinceRewetting = 3,
    site: Site = "default",
) -> WaterTableScenario:
    wg = np.linspace(0.02, 1.05, 45) if mean_wtd_m is None else np.asarray(mean_wtd_m, float)
    co2p, ch4p, n2op = store.get("co2", site), store.get("ch4", site), store.get("n2o", site)
    co2_pars = dict(m_ch4.CO2_PARS, k_peat=co2p["k_peat"], Q10_h=co2p["Q10_h"])
    pts = []
    for w in wg:
        c = m_ch4.annual_nee(w, vegetation, co2_pars) * m_co2.CO2C_TO_CO2
        m = m_ch4.annual_ch4_components(
            w, ch4p, vegetation, m_ch4.LITTER if include_flood_litter else None,
            years_since_rewetting)["total"] * m_ch4.GWP_CH4 / 1000
        n = (m_n2o.n2o_at_wtd(w, n2op, crop, co2p, lo=0.02)
             * m_n2o.N2ON_TO_N2O * m_n2o.GWP_N2O / 1000)
        pts.append(ScenarioPoint(mean_wtd_m=float(w), co2_t_co2e_ha_yr=c, ch4_t_co2e_ha_yr=m,
                                 n2o_t_co2e_ha_yr=n, net_t_co2e_ha_yr=c + m + n))
    best = min(pts, key=lambda p: p.net_t_co2e_ha_yr)
    return WaterTableScenario(crop_for_n2o=crop, vegetation_for_co2_ch4=vegetation, points=pts,
                              optimum_wtd_m=best.mean_wtd_m,
                              optimum_net_t_co2e_ha_yr=best.net_t_co2e_ha_yr,
                              provenance=_prov(site, "co2", "ch4", "n2o"))


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
class InventoryProfileRow(BaseModel):
    wtd_cm: float
    co2_model_t: float
    co2_report_eq1_t: float
    ch4_model_kg: float
    ch4_report_eq3_kg: float
    n2o_model_kg_n: float


class Skill(BaseModel):
    bias: float
    rmse: float
    r: float
    nse: float


class Tier2Row(BaseModel):
    peat_class: str
    wtd_cm: float
    ef_tier2: float = Field(description="UK Tier-2 CH4 emission factor, kg CH4/ha/yr.")
    model: float


class InventoryValidation(BaseModel):
    water_table_profile: list[InventoryProfileRow]
    co2_slope_model: float
    co2_slope_report: float
    cropland_co2_model_t: float
    cropland_co2_tier2_t: float
    ch4_rewetted_model_kg: float
    ch4_rewetted_tier2_kg: float
    ch4_cropland_model_kg: float
    ch4_cropland_tier2_kg: float
    n2o_cropland_model_kg_n: float
    n2o_cropland_tier2_kg_n: float
    n2o_grass_model_kg_n: float
    n2o_grass_tier2_kg_n: float
    n2o_rewetted_model_kg_n: float
    ch4_skill: dict[str, Skill] = Field(description="CH4 model against Inventory Eq. 3 (5-70 cm, "
                                                    "20-70 cm) and the five Tier-2 classes.")
    ch4_tier2_table: list[Tier2Row]
    reference: str = ("Evans et al. (2023) UK Peatland Inventory / CEH report: Eq. 1 (CO2), "
                      "Eq. 3 (CH4), Fig. 3.9 (N2O), Tier-2 emission factors")
    provenance: Provenance


@server.tool(description=(
    "Validate the twin against the UK Peatland Inventory (CEH report): CO2 and CH4 water-table "
    "laws, N2O switch-on, and Tier-2 emission factors for cropland, grassland and rewetted fen."))
def validate_inventory(site: Site = "default") -> InventoryValidation:
    # peat respiration parameters follow the site; crop eps_max stays at its per-module value
    co2p = store.get("co2", site)
    co2_pars = {"k_peat": co2p["k_peat"], "Q10_h": co2p["Q10_h"]}
    v = m_inv.validate(store.get("ch4", site), store.get("n2o", site), co2_pars)
    c = m_ch4.inventory_validation(store.get("ch4", site))
    v["ch4_skill"] = {k: c[k] for k in ("eq3_5_70cm", "eq3_20_70cm", "tier2_classes")}
    v["ch4_tier2_table"] = c["tier2_table"]
    return InventoryValidation(**v, provenance=_prov(site, "co2", "ch4", "n2o"))


# --------------------------------------------------------------------------- #
# parameter state and self-learning
# --------------------------------------------------------------------------- #
class ParameterState(BaseModel):
    site: str
    co2: dict[str, float]
    ch4: dict[str, float]
    n2o: dict[str, float]
    sources: dict[str, str]
    persisted_to: str | None
    known_sites: list[str]


def _state(site: str) -> ParameterState:
    return ParameterState(site=site, co2=store.get("co2", site), ch4=store.get("ch4", site),
                          n2o=store.get("n2o", site),
                          sources={g: store.source(g, site) for g in ("co2", "ch4", "n2o")},
                          persisted_to=str(store.path) if store.path else None,
                          known_sites=store.sites())


@server.tool(description="Show the current (calibrated or learned) parameters for a site.")
def get_parameters(site: Site = "default") -> ParameterState:
    return _state(site)


@server.tool(description="Discard learned parameters for a site and return to the calibrated "
                         "baseline (one gas, or all gases if omitted).")
def reset_parameters(gas: Literal["co2", "ch4", "n2o"] | None = None,
                     site: Site = "default") -> ParameterState:
    store.reset(site, gas)
    return _state(site)


class CH4Observation(BaseModel):
    tsoil_c: float = Field(ge=-20, le=40, description="Soil temperature (degC).")
    wtd_m: float = Field(ge=-0.5, le=2.0, description="Water-table depth (m, positive below "
                                                      "surface).")
    lai: float = Field(ge=0, le=10, description="Leaf area index (e.g. from Sentinel-2).")
    ch4_mg_m2_d: float = Field(description="Observed net CH4 flux (mg CH4 m-2 d-1).")


class LearningResult(BaseModel):
    gas: str
    site: str
    data: str
    prior: dict[str, float]
    learned: dict[str, float]
    truth: dict[str, float] | None = Field(None, description="Only for synthetic data.")
    convergence: dict[str, list[float]] = Field(description="Averaged parameter after each "
                                                            "epoch.")
    persisted: bool
    provenance: Provenance


def _learnable(p: dict, keys) -> dict:
    return {k: float(p[k]) for k in keys}


@server.tool(description=(
    "Demonstrate self-learning on a synthetic observation stream: start from a deliberately "
    "wrong prior (2.2x CH4 production or 2x N2O emission factor, wrong Q10) and recover the "
    "true CH4 or N2O parameters. With persist=true the learned set becomes the site's parameters."))
def self_learn_synthetic(
    gas: Literal["ch4", "n2o"],
    epochs: Annotated[int, Field(ge=1, le=40)] = 20,
    persist: bool = False,
    site: Site = "default",
) -> LearningResult:
    truth = store.baseline(gas)
    if gas == "ch4":
        prior = dict(truth, k_prod=2.2 * truth["k_prod"], Q10_CH4=2.0)
        learned, hist = m_ch4.self_learn_ch4(m_ch4.make_synthetic(truth), prior, epochs,
                                             scale_k=truth["k_prod"])
        keys = m_ch4.LEARNABLE
    else:
        prior = dict(truth, ef_peat=2.0 * truth["ef_peat"], Q10_n2o=1.8)
        rng = np.random.default_rng(1)
        learned, hist = m_n2o.self_learn_n2o(m_n2o.make_synthetic(truth, rng=rng), prior, epochs,
                                             scale_ef=truth["ef_peat"], rng=rng)
        keys = m_n2o.LEARNABLE
    if persist:
        store.set(gas, learned, site, note=f"synthetic self-learning, {epochs} epochs")
    return LearningResult(gas=gas, site=site, data="synthetic: true model + heteroscedastic noise",
                          prior=_learnable(prior, keys), learned=_learnable(learned, keys),
                          truth=_learnable(truth, keys), convergence=hist, persisted=persist,
                          provenance=_prov(site, gas))


@server.tool(description=(
    "Assimilate observed daily CH4 fluxes (with soil temperature, water table and LAI) to "
    "update the site's CH4 production rate and Q10. Starts from the site's current parameters."))
def assimilate_ch4(
    observations: Annotated[list[CH4Observation], Field(min_length=10, max_length=20000)],
    epochs: Annotated[int, Field(ge=1, le=40)] = 10,
    persist: bool = True,
    site: Site = "default",
) -> LearningResult:
    prior = store.get("ch4", site)
    obs = [dict(Tsoil=np.array([o.tsoil_c for o in observations]),
                WTD=np.array([o.wtd_m for o in observations]),
                LAI=np.array([o.lai for o in observations]),
                ch4=np.array([o.ch4_mg_m2_d for o in observations]))]
    learned, hist = m_ch4.self_learn_ch4(obs, prior, epochs,
                                         scale_k=store.baseline("ch4")["k_prod"])
    if persist:
        store.set("ch4", learned, site,
                  note=f"assimilated {len(observations)} CH4 observations, {epochs} epochs")
    return LearningResult(gas="ch4", site=site, data=f"{len(observations)} observed days",
                          prior=_learnable(prior, m_ch4.LEARNABLE),
                          learned=_learnable(learned, m_ch4.LEARNABLE), convergence=hist,
                          persisted=persist, provenance=_prov(site, "ch4"))


if __name__ == "__main__":
    server.run("streamable-http" if "--http" in sys.argv else "stdio")
