"""DT4 agent: the forest above-ground biomass and carbon twin as an MCP server.

The science lives in the ``forest`` package next to this file. DT4 observes woodland biomass
with ESA Biomass CCI v7 (the only data it is calibrated against), grows stands forward with
two interchangeable growth models, empirical yield curves and the process-based 3-PG model,
applies management and disturbance scenarios, and keeps the carbon books (living biomass,
deadwood, litter, harvested wood products). Pilot landscapes: Thetford and Kielder.

An orchestrator (or any MCP client) can launch it over stdio:

    python dt4_agent/dt4_server.py

Run with ``--http`` to serve over streamable HTTP instead (default port 8000; ``DT4_PORT``).
Set ``DT4_STATE_FILE`` to a JSON path to keep learned site parameters across restarts.

Conventions (shared with DT8): positive flux = emission to the atmosphere, so a growing
forest has a negative net flux. AGB is in Mg (= t) dry matter per hectare, carbon in t C/ha,
CO2 in t CO2/ha. Every result carries an EBCF role (state, impact, pressure or response)
and provenance.
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

from forest import GROWTH_MODELS, MODEL_VERSION, curve_bank, make_model  # noqa: E402
from forest import assimilation as m_da  # noqa: E402
from forest import calibration as m_cal  # noqa: E402
from forest import carbon as m_c  # noqa: E402
from forest import cci  # noqa: E402
from forest import change as m_chg  # noqa: E402
from forest import disturbance as m_dist  # noqa: E402
from forest import landscapes as m_ls  # noqa: E402
from forest import management as m_mg  # noqa: E402
from forest import scenario as m_sc  # noqa: E402
from forest import species as m_sp  # noqa: E402
from forest.state import ParameterStore, calibration as shipped_calibration  # noqa: E402

VERSION = MODEL_VERSION
store = ParameterStore(os.environ.get("DT4_STATE_FILE") or None)

LandscapeKey = Literal["thetford", "kielder"]
SpeciesCode = Literal["SS", "CP", "SP", "OK"]
ModelName = Literal["yield_curve", "3pg"]
ModelChoice = Literal["yield_curve", "3pg", "both"]
RegimeName = Literal["no_intervention", "thin_and_fell", "clearfell_no_thin", "continuous_cover"]
CCIYear = Annotated[int, Field(ge=2005, le=2024, description=(
    "A year with a Biomass CCI v7 map: 2005-2012 or 2015-2024 (no maps for 2013-2014)."))]
Site = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$",
                            description="Site id; each site keeps its own learned productivity. "
                                        "Defaults to the landscape key.")]

ASSUMPTIONS = [
    "Calibrated on ESA Biomass CCI v7 only (no GEDI, ICESat-2, lidar or other satellite data).",
    "Woodland mask derived from CCI v7 (median AGB 2015-2024 >= 20 or peak >= 60 Mg/ha), not the NFI map.",
    "One dominant species per pilot landscape: Corsican pine (Thetford), Sitka spruce (Kielder).",
    "3-PG climate: approximate 1991-2020 station climatology typed in per landscape, not HadUK-Grid.",
    "SAR saturation and thinning bias CCI-calibrated productivity low relative to Forest Research yield classes.",
]


class Provenance(BaseModel):
    model: str = f"DT4 forest biomass twin {VERSION}"
    observations: str = f"ESA Biomass CCI v{cci.CCI_VERSION} (100 m AGB and SD), {cci.CATALOGUE}"
    citation: str = cci.CITATION
    licence: str = cci.LICENCE
    parameters: str = Field(default="", description="Where the productivity came from.")
    assumptions: list[str] = Field(default_factory=lambda: list(ASSUMPTIONS))


class AreaSpec(BaseModel):
    """Part of a landscape. Omit for the whole landscape."""

    bbox: Annotated[list[float], Field(min_length=4, max_length=4, description=(
        "[west, south, east, north] in degrees (EPSG:4326)."))] | None = None
    point: Annotated[list[float], Field(min_length=2, max_length=2, description=(
        "[lon, lat] in degrees."))] | None = None
    radius_m: Annotated[float, Field(ge=0, le=20000, description=(
        "Radius around the point; 0 = the single 100 m pixel."))] = 0.0

    def to_area(self) -> cci.Area:
        return cci.Area(bbox=tuple(self.bbox) if self.bbox else None,
                        point=tuple(self.point) if self.point else None,
                        radius_m=self.radius_m)


server = MCPServer(
    name="dt4",
    instructions=(
        "DT4 forest biomass agent: above-ground biomass (AGB) and carbon of British woodland, "
        "observed with ESA Biomass CCI v7 (100 m, 2005-2012 and 2015-2024) and projected with "
        "two growth models (empirical yield curves and the 3-PG process model) under "
        "management and disturbance scenarios. Pilot landscapes: thetford (Corsican pine) and "
        "kielder (Sitka spruce). Results carry uncertainty (90 % ranges) and an EBCF role: "
        "'state' (observed stock), 'impact' (observed change), 'pressure' (attributed cause, "
        "only with evidence) or 'response' (management scenario, not an observation). "
        "Sign convention: positive flux = emission to the atmosphere."),
    version=VERSION,
)


def _area(spec: AreaSpec | None) -> cci.Area:
    return spec.to_area() if spec else cci.Area()


def _mask(landscape: str, spec: AreaSpec | None):
    cube = cci.load(landscape)
    area = _area(spec)
    return cube, cci.select(cube, area), area


# --------------------------------------------------------------------------- #
# catalogue
# --------------------------------------------------------------------------- #
class SpeciesInfo(BaseModel):
    code: str
    name: str
    latin: str
    conifer: bool
    yield_class_range: list[int]
    culmination_age: float
    wood_density_t_m3: float
    biomass_expansion_factor: float
    rotation_age: int
    first_thin_age: int
    threepg_parameters: dict[str, float | bool]


class RegimeInfo(BaseModel):
    name: str
    description: str


class SpeciesList(BaseModel):
    species: list[SpeciesInfo]
    regimes: list[RegimeInfo]
    disturbances: list[str]
    growth_models: dict[str, str]


@server.tool(description="List the species, management regimes, disturbance types and growth "
                         "models DT4 knows, with each species' a priori parameters.")
def list_species() -> SpeciesList:
    return SpeciesList(
        species=[SpeciesInfo(code=s.code, name=s.name, latin=s.latin, conifer=s.conifer,
                             yield_class_range=[s.yc_min, s.yc_max],
                             culmination_age=s.culmination_age,
                             wood_density_t_m3=s.wood_density, biomass_expansion_factor=s.bef,
                             rotation_age=s.rotation_age, first_thin_age=s.first_thin_age,
                             threepg_parameters=s.threepg)
                 for s in m_sp.SPECIES.values()],
        regimes=[RegimeInfo(name=r.name, description=r.description) for r in m_mg.REGIMES.values()],
        disturbances=list(m_dist.KINDS),
        growth_models={"yield_curve": "Chapman-Richards yield curves indexed by yield class "
                                      "(peak MAI, m3/ha/yr)",
                       "3pg": "3-PG process model (Landsberg & Waring 1997), productivity "
                              "set by the fertility rating (0-1), monthly climate"})


class ModelSkill(BaseModel):
    rmse_mg_ha: float | None
    bias_mg_ha: float | None
    r2: float | None
    n: int


class CalibrationSummary(BaseModel):
    growth_model: str
    productivity_name: str
    productivity_median: float
    productivity_p25: float
    productivity_p75: float
    stand_age_median_2024: float
    fit_all_years: ModelSkill
    holdout_2018_2024: ModelSkill | None = None


class LandscapeInfo(BaseModel):
    key: str
    name: str
    description: str
    bbox_wsen: list[float]
    dominant_species: str
    woodland_area_ha: float
    woodland_pixels: int
    cci_years: list[int]
    annual_rain_mm: float
    mean_temperature_c: float
    climate_source: str
    calibration: list[CalibrationSummary]
    notes: list[str]


class LandscapeList(BaseModel):
    landscapes: list[LandscapeInfo]
    provenance: Provenance


def _cal_summaries(key: str) -> list[CalibrationSummary]:
    out = []
    for name in GROWTH_MODELS:
        entry = shipped_calibration().get(key, {}).get(name)
        if not entry:
            continue
        c, v = entry["calibration"], entry["validation"]
        h = v.get("holdout")
        out.append(CalibrationSummary(
            growth_model=name, productivity_name=c["productivity_name"],
            productivity_median=c["theta_median"], productivity_p25=c["theta_p25"],
            productivity_p75=c["theta_p75"], stand_age_median_2024=c["age_median_last_cci_year"],
            fit_all_years=ModelSkill(**c["fit"]),
            holdout_2018_2024=ModelSkill(**{k: h[k] for k in ("rmse_mg_ha", "bias_mg_ha", "r2", "n")})
            if h else None))
    return out


@server.tool(description="List the pilot landscapes with their woodland area, CCI v7 years, "
                         "climate and the CCI calibration of both growth models.")
def list_landscapes() -> LandscapeList:
    items = []
    for key, ls in m_ls.LANDSCAPES.items():
        cube = cci.load(key)
        items.append(LandscapeInfo(
            key=key, name=ls.name, description=ls.description, bbox_wsen=list(ls.bbox),
            dominant_species=ls.species,
            woodland_area_ha=float(cube.pixel_area_ha()[cube.woodland].sum()),
            woodland_pixels=int(cube.woodland.sum()), cci_years=list(cube.years),
            annual_rain_mm=ls.climate.annual_rain_mm, mean_temperature_c=ls.climate.mean_temp_c,
            climate_source=ls.climate.source, calibration=_cal_summaries(key),
            notes=list(ls.notes)))
    return LandscapeList(landscapes=items, provenance=Provenance(parameters="shipped calibration"))


# --------------------------------------------------------------------------- #
# state: observed AGB and carbon
# --------------------------------------------------------------------------- #
class AGBResult(BaseModel):
    landscape: str
    area: str
    year: int
    agb_mean_mg_ha: float = Field(description="Mean above-ground biomass of the woodland pixels.")
    agb_sd_mg_ha: float = Field(description="SD of the area mean (spatially correlated errors).")
    agb_p05_mg_ha: float
    agb_p95_mg_ha: float
    pixel_sd_mean_mg_ha: float = Field(description="Mean CCI per-pixel SD.")
    pixel_agb_p10_mg_ha: float
    pixel_agb_p90_mg_ha: float
    n_pixels: int
    area_ha: float
    agb_total_mg: float
    ebcf_role: str = "state"
    provenance: Provenance


@server.tool(description=(
    "Observed above-ground biomass (Mg/ha) of the woodland in a landscape, or part of it, in "
    "one year from Biomass CCI v7, with the uncertainty of the area mean and the woodland area."))
def get_agb(landscape: LandscapeKey, year: CCIYear, area: AreaSpec | None = None) -> AGBResult:
    cube, mask, a = _mask(landscape, area)
    st = cci.area_stats(cube, year, mask)
    return AGBResult(landscape=landscape, area=a.describe(), provenance=Provenance(
        parameters="observation only"), **st)


class TimeseriesRow(BaseModel):
    year: int
    agb_mean_mg_ha: float
    agb_sd_mg_ha: float
    agb_p05_mg_ha: float
    agb_p95_mg_ha: float


class TimeseriesResult(BaseModel):
    landscape: str
    area: str
    n_pixels: int
    area_ha: float
    series: list[TimeseriesRow]
    trend_mg_ha_yr_2015_2024: float = Field(description="Least-squares slope over the "
                                                        "Sentinel-1/ALOS-2 epoch.")
    sensor_epoch_note: str
    ebcf_role: str = "state"
    provenance: Provenance


@server.tool(description="Annual CCI v7 AGB of a landscape or area for every year with a map "
                         "(2005-2012, 2015-2024), with uncertainty and the 2015-2024 trend.")
def agb_timeseries(landscape: LandscapeKey, area: AreaSpec | None = None) -> TimeseriesResult:
    cube, mask, a = _mask(landscape, area)
    rows = [cci.area_stats(cube, y, mask) for y in cube.years]
    post = [(r["year"], r["agb_mean_mg_ha"]) for r in rows if r["year"] >= 2015]
    slope = float(np.polyfit([p[0] for p in post], [p[1] for p in post], 1)[0])
    return TimeseriesResult(
        landscape=landscape, area=a.describe(), n_pixels=rows[0]["n_pixels"],
        area_ha=rows[0]["area_ha"],
        series=[TimeseriesRow(**{k: r[k] for k in TimeseriesRow.model_fields}) for r in rows],
        trend_mg_ha_yr_2015_2024=slope,
        sensor_epoch_note="2005-2012 maps use ALOS PALSAR/Envisat, 2015-2024 ALOS-2/Sentinel-1; "
                          "compare levels across the gap with care.",
        provenance=Provenance(parameters="observation only"))


class CarbonStockResult(BaseModel):
    landscape: str
    area: str
    year: int
    agb_mg_ha: float
    above_ground_c_t_ha: float
    below_ground_c_t_ha: float = Field(description="Roots from Mokany et al. (2006) root:shoot relation.")
    living_c_t_ha: float
    living_c_sd_t_ha: float
    living_co2e_t_ha: float
    total_living_c_t: float = Field(description="Over the woodland area of the selection.")
    total_living_co2e_t: float
    area_ha: float
    not_included: str = ("Deadwood, litter and soil carbon are not observed by CCI; use "
                         "simulate_stand for modelled dead pools and DT7 for soil.")
    ebcf_role: str = "state"
    provenance: Provenance


@server.tool(description="Living biomass carbon (above- and below-ground) of a landscape or "
                         "area in a CCI year, per hectare and in total, in t C and t CO2e.")
def carbon_stock(landscape: LandscapeKey, year: CCIYear,
                 area: AreaSpec | None = None) -> CarbonStockResult:
    cube, mask, a = _mask(landscape, area)
    i = cube.year_index(year)
    conifer = m_sp.get(m_ls.get(landscape).species).conifer
    agb_px = cube.agb[i][mask]
    ac_px, bc_px = m_c.living_carbon(agb_px, conifer)
    st = cci.area_stats(cube, year, mask)
    ratio = (ac_px.mean() + bc_px.mean()) / max(ac_px.mean(), 1e-9)
    living = float(ac_px.mean() + bc_px.mean())
    living_sd = st["agb_sd_mg_ha"] * m_sp.CARBON_FRACTION * ratio
    return CarbonStockResult(
        landscape=landscape, area=a.describe(), year=year, agb_mg_ha=st["agb_mean_mg_ha"],
        above_ground_c_t_ha=float(ac_px.mean()), below_ground_c_t_ha=float(bc_px.mean()),
        living_c_t_ha=living, living_c_sd_t_ha=float(living_sd),
        living_co2e_t_ha=living * m_sp.CO2_PER_C, total_living_c_t=living * st["area_ha"],
        total_living_co2e_t=living * st["area_ha"] * m_sp.CO2_PER_C, area_ha=st["area_ha"],
        provenance=Provenance(parameters="observation only; Mokany et al. (2006) root:shoot"))


# --------------------------------------------------------------------------- #
# impact and pressure
# --------------------------------------------------------------------------- #
class ChangeResult(BaseModel):
    landscape: str
    area: str
    year1: int
    year2: int
    delta_agb_mean_mg_ha: float
    delta_agb_sd_mg_ha: float
    delta_agb_p05_mg_ha: float
    delta_agb_p95_mg_ha: float
    delta_agb_per_year_mg_ha: float
    significant_at_90pct: bool
    impact: str = Field(description="EBCF impact term; 'no detectable change' when the change "
                                    "is within the combined uncertainty.")
    loss_area_ha: float = Field(description="Pixels with a significant AGB loss.")
    gain_area_ha: float
    conversion_candidate_area_ha: float = Field(description="Significant loss to below the "
                                                            "woodland threshold (e.g. clearfell).")
    modification_loss_area_ha: float
    area_ha: float
    crosses_sensor_epoch: bool
    ebcf_role: str = "impact"
    provenance: Provenance


def _change(landscape, year1, year2, area):
    cube, mask, a = _mask(landscape, area)
    ch = m_chg.area_change(cube, year1, year2, mask)
    return cube, ch, a


@server.tool(description=(
    "AGB change between two CCI years for a landscape or area: mean change with propagated "
    "uncertainty, whether it is significant (90 %), the EBCF impact term, and the areas of "
    "significant pixel loss and gain. Names no cause; use attribute_change for that."))
def biomass_change(landscape: LandscapeKey, year1: CCIYear, year2: CCIYear,
                   area: AreaSpec | None = None) -> ChangeResult:
    _, ch, a = _change(landscape, year1, year2, area)
    ch.pop("_loss_mask")
    return ChangeResult(landscape=landscape, area=a.describe(),
                        provenance=Provenance(parameters="observation only"), **ch)


class EvidenceIn(BaseModel):
    pressure: Literal["harvest", "wind", "fire", "biotic", "drought"]
    year_from: Annotated[int, Field(ge=2005, le=2030)]
    year_to: Annotated[int, Field(ge=2005, le=2030)]
    bbox: Annotated[list[float], Field(min_length=4, max_length=4)] | None = None
    point: Annotated[list[float], Field(min_length=2, max_length=2)] | None = None
    radius_m: Annotated[float, Field(ge=0, le=50000)] = 0.0
    source: Annotated[str, Field(max_length=200, description=(
        "Where the evidence comes from, e.g. 'felling licence FL123', 'Storm Arwen footprint'."))] = ""


class Attribution(BaseModel):
    pressure: str
    source: str
    years: list[int]
    overlaps_in_time: bool
    attributed_loss_area_ha: float
    share_of_loss: float
    label: str


class AttributionResult(BaseModel):
    landscape: str
    area: str
    year1: int
    year2: int
    impact: str
    loss_area_ha: float
    attributions: list[Attribution]
    unattributed_loss_area_ha: float
    unattributed_share: float
    rule: str
    ebcf_role: str = "pressure"
    provenance: Provenance


@server.tool(description=(
    "Attribute the significant AGB loss between two CCI years to pressures, using evidence you "
    "supply (felling licences, storm footprints, fire perimeters, tree-health surveys). Loss "
    "without overlapping evidence stays unattributed (Living Earth EBCF rule)."))
def attribute_change(landscape: LandscapeKey, year1: CCIYear, year2: CCIYear,
                     evidence: Annotated[list[EvidenceIn], Field(max_length=200)],
                     area: AreaSpec | None = None) -> AttributionResult:
    cube, ch, a = _change(landscape, year1, year2, area)
    ev = [m_chg.Evidence(pressure=e.pressure, year_from=e.year_from, year_to=e.year_to,
                         bbox=tuple(e.bbox) if e.bbox else None,
                         point=tuple(e.point) if e.point else None,
                         radius_m=e.radius_m, source=e.source) for e in evidence]
    at = m_chg.attribute(cube, ch, ev)
    return AttributionResult(landscape=landscape, area=a.describe(), year1=year1, year2=year2,
                             impact=ch["impact"], loss_area_ha=at["loss_area_ha"],
                             attributions=[Attribution(**r) for r in at["attributions"]],
                             unattributed_loss_area_ha=at["unattributed_loss_area_ha"],
                             unattributed_share=at["unattributed_share"], rule=at["rule"],
                             provenance=Provenance(parameters="observation and supplied evidence"))


# --------------------------------------------------------------------------- #
# response: growth, management, disturbance, carbon
# --------------------------------------------------------------------------- #
class Band(BaseModel):
    mean: list[float]
    p05: list[float]
    p95: list[float]


class FinalStocks(BaseModel):
    above_ground_c_t_ha: float
    below_ground_c_t_ha: float
    deadwood_c_t_ha: float
    litter_c_t_ha: float
    wood_products_c_t_ha: float
    total_c_t_ha: float


class StandRun(BaseModel):
    growth_model: str
    species: str
    regime: str
    productivity_name: str
    productivity: float
    productivity_sd: float
    productivity_source: str
    start_age: float
    years: list[int]
    agb_mg_ha: Band
    total_carbon_t_c_ha: Band = Field(description="Living + deadwood + litter + wood products.")
    net_flux_t_co2_ha_yr: Band = Field(description="Forest + products; positive = emission.")
    cumulative_net_t_co2_ha: list[float] = Field(description=(
        "[ensemble mean, 5th, 95th percentile] of CO2 exchanged with the atmosphere over the "
        "run, forest ecosystem plus harvested wood products; negative = removal."))
    mean_annual_net_t_co2_ha_yr: float
    removals_total_t_dm_ha: float = Field(description="Harvested and salvaged logs, mean.")
    litter_and_deadwood_to_soil_t_c_ha_yr: float = Field(description="Mean annual carbon input "
                                                                     "to soil, for DT7.")
    final_stocks: FinalStocks
    events: list[dict]
    n_members: int


def _theta_for(model_name: str, species: str, landscape: str, site: str,
               override: float | None) -> tuple[float, float, str]:
    if override is not None:
        return float(override), 0.0, "given by the caller"
    if species == m_ls.get(landscape).species:
        p = store.get(site, landscape, model_name)
        return p["theta"], p["theta_sd"], store.source(site, landscape, model_name)
    sp = m_sp.get(species)
    if model_name == "yield_curve":
        return float(sp.yc_default), (sp.yc_max - sp.yc_min) / 4.0, \
            f"a priori: {species} is not calibrated in {landscape}"
    return 0.5, 0.2, f"a priori: {species} is not calibrated in {landscape}"


def _run(model_name, species, landscape, site, theta_override, *, age, years, start_year,
         regime, events, stochastic, n_members, seed, agb0=None, agb0_sd=0.0) -> StandRun:
    ls = m_ls.get(landscape)
    model = make_model(model_name, species, ls)
    theta, theta_sd, src = _theta_for(model_name, species, landscape, site, theta_override)
    res = m_sc.simulate(model, start_year=start_year, years=years, age=age, theta=theta,
                        theta_sd=theta_sd, agb0=agb0, agb0_sd=agb0_sd, regime=regime,
                        events=events, stochastic=stochastic, n_members=n_members, seed=seed)
    flux = res.net_flux_co2[1:]
    cum = flux.sum(axis=0)
    last = -1
    reg = regime if isinstance(regime, str) else regime.name
    return StandRun(
        growth_model=model_name, species=species, regime=reg,
        productivity_name=model.productivity_name, productivity=theta,
        productivity_sd=theta_sd, productivity_source=src, start_age=float(age),
        years=res.years.tolist(), agb_mg_ha=Band(**m_sc.summarise(res.agb)),
        total_carbon_t_c_ha=Band(**m_sc.summarise(res.total_c)),
        net_flux_t_co2_ha_yr=Band(**m_sc.summarise(res.net_flux_co2)),
        cumulative_net_t_co2_ha=[round(float(cum.mean()), 3),
                                 round(float(np.percentile(cum, 5)), 3),
                                 round(float(np.percentile(cum, 95)), 3)],
        mean_annual_net_t_co2_ha_yr=round(float(flux.mean()), 4),
        removals_total_t_dm_ha=round(float(res.removals_dm.sum(axis=0).mean()), 3),
        litter_and_deadwood_to_soil_t_c_ha_yr=round(float(res.to_soil_c[1:].mean()), 4),
        final_stocks=FinalStocks(
            above_ground_c_t_ha=float(res.agb_c[last].mean()),
            below_ground_c_t_ha=float(res.bgb_c[last].mean()),
            deadwood_c_t_ha=float(res.deadwood_c[last].mean()),
            litter_c_t_ha=float(res.litter_c[last].mean()),
            wood_products_c_t_ha=float(res.hwp_c[last].mean()),
            total_c_t_ha=float(res.total_c[last].mean())),
        events=res.events[:50], n_members=res.agb.shape[1])


class DisturbanceIn(BaseModel):
    year: Annotated[int, Field(ge=1900, le=2300)]
    kind: Literal["wind", "fire", "biotic", "drought"]
    severity: Annotated[float, Field(ge=0, le=1, description="Share of standing AGB killed; "
                                                             ">= 0.8 is stand-replacing.")]
    salvage_fraction: Annotated[float, Field(ge=0, le=1)] | None = None


class StandResult(BaseModel):
    landscape: str
    runs: list[StandRun]
    ebcf_role: str = "response"
    provenance: Provenance


def _models(choice: str) -> list[str]:
    return list(GROWTH_MODELS) if choice == "both" else [choice]


@server.tool(description=(
    "Simulate one stand forward with the yield-curve model, 3-PG, or both side by side: AGB, "
    "carbon pools, wood products and net CO2 flux each year, as an ensemble with 90 % ranges. "
    "Productivity defaults to the landscape's CCI v7 calibration (or the site's learned value)."))
def simulate_stand(
    landscape: LandscapeKey,
    age: Annotated[float, Field(ge=0, le=250, description="Stand age at the start (years).")],
    years: Annotated[int, Field(ge=1, le=150)] = 50,
    growth_model: ModelChoice = "both",
    species: SpeciesCode | None = None,
    regime: RegimeName = "no_intervention",
    rotation_age: Annotated[int, Field(ge=10, le=250)] | None = None,
    yield_class: Annotated[float, Field(ge=2, le=30)] | None = None,
    fertility_rating: Annotated[float, Field(ge=0, le=1)] | None = None,
    disturbances: Annotated[list[DisturbanceIn], Field(max_length=50)] = [],
    stochastic_disturbance: bool = False,
    start_year: Annotated[int, Field(ge=1900, le=2200)] = 2024,
    n_members: Annotated[int, Field(ge=1, le=200)] = 50,
    seed: int = 0,
    site: Site | None = None,
) -> StandResult:
    species = species or m_ls.get(landscape).species
    reg = m_mg.get(regime).with_options(rotation_age=rotation_age)
    ev = [m_dist.Event(d.year, d.kind, d.severity, d.salvage_fraction) for d in disturbances]
    runs = [_run(m, species, landscape, site or landscape,
                 yield_class if m == "yield_curve" else fertility_rating,
                 age=age, years=years, start_year=start_year, regime=reg, events=ev,
                 stochastic=stochastic_disturbance, n_members=n_members, seed=seed)
            for m in _models(growth_model)]
    return StandResult(landscape=landscape, runs=runs, provenance=Provenance(
        parameters="; ".join(f"{r.growth_model}: {r.productivity_source}" for r in runs)))


class RegimeOutcome(BaseModel):
    regime: str
    growth_model: str
    cumulative_net_t_co2_ha: list[float] = Field(description=(
        "[ensemble mean, 5th percentile, 95th percentile] of the CO2 exchanged with the "
        "atmosphere over the horizon, counting the forest ecosystem AND harvested wood "
        "products (carbon stored in products is credited until it decays). Negative = "
        "removal from the atmosphere."))
    mean_annual_net_t_co2_ha_yr: float = Field(description="Ensemble mean per year, same "
                                                           "accounting.")
    removals_total_t_dm_ha: float = Field(description="Harvested logs over the horizon "
                                                      "(ensemble mean).")
    final_total_c_t_ha: float = Field(description="Living + deadwood + litter + wood products "
                                                  "at the end (ensemble mean).")
    final_wood_products_c_t_ha: float = Field(description="Carbon still in wood products at "
                                                          "the end (ensemble mean).")
    final_agb_mg_ha: float


class ScenarioResult(BaseModel):
    landscape: str
    species: str
    start_year: int
    horizon_years: int
    start_age: float
    start_agb_mg_ha: float | None
    start_agb_source: str
    outcomes: list[RegimeOutcome]
    best_for_carbon: dict[str, str] = Field(description="Per growth model, the regime with the "
                                                        "largest cumulative removal of CO2 "
                                                        "(forest + products).")
    runs: list[StandRun] | None = None
    ebcf_role: str = "response"
    note: str = "Scenario outcomes are management responses, not observations."
    provenance: Provenance


@server.tool(description=(
    "Compare management regimes for a landscape's typical stand (calibrated median age and "
    "productivity, starting from the CCI v7 AGB of 2024) over a horizon: cumulative net CO2, "
    "removals and final carbon per regime and growth model, and the best regime for carbon."))
def management_scenario(
    landscape: LandscapeKey,
    regimes: Annotated[list[RegimeName], Field(min_length=1, max_length=4)] = [
        "no_intervention", "thin_and_fell", "clearfell_no_thin", "continuous_cover"],
    horizon_years: Annotated[int, Field(ge=5, le=150)] = 60,
    growth_model: ModelChoice = "both",
    age: Annotated[float, Field(ge=0, le=250)] | None = None,
    start_from_cci: bool = True,
    area: AreaSpec | None = None,
    stochastic_disturbance: bool = False,
    include_annual: bool = False,
    n_members: Annotated[int, Field(ge=1, le=200)] = 50,
    seed: int = 0,
    site: Site | None = None,
) -> ScenarioResult:
    ls = m_ls.get(landscape)
    site = site or landscape
    start_year = cci.CCI_YEARS[-1]
    agb0 = agb0_sd = None
    src = "model value at the start age"
    if start_from_cci:
        cube, mask, a = _mask(landscape, area)
        st = cci.area_stats(cube, start_year, mask)
        agb0, agb0_sd = st["agb_mean_mg_ha"], st["agb_sd_mg_ha"]
        src = f"CCI v7 {start_year}, {a.describe()}"
    outcomes, runs, best = [], [], {}
    for m in _models(growth_model):
        a0 = age if age is not None else store.get(site, landscape, m)["age_median"]
        scores = {}
        for r in regimes:
            run = _run(m, ls.species, landscape, site, None, age=a0, years=horizon_years,
                       start_year=start_year, regime=r, events=[],
                       stochastic=stochastic_disturbance, n_members=n_members, seed=seed,
                       agb0=agb0, agb0_sd=agb0_sd or 0.0)
            outcomes.append(RegimeOutcome(
                regime=r, growth_model=m, cumulative_net_t_co2_ha=run.cumulative_net_t_co2_ha,
                mean_annual_net_t_co2_ha_yr=run.mean_annual_net_t_co2_ha_yr,
                removals_total_t_dm_ha=run.removals_total_t_dm_ha,
                final_total_c_t_ha=run.final_stocks.total_c_t_ha,
                final_wood_products_c_t_ha=run.final_stocks.wood_products_c_t_ha,
                final_agb_mg_ha=run.agb_mg_ha.mean[-1]))
            scores[r] = run.cumulative_net_t_co2_ha[0]
            if include_annual:
                runs.append(run)
        best[m] = min(scores, key=scores.get)
    return ScenarioResult(
        landscape=landscape, species=ls.species, start_year=start_year,
        horizon_years=horizon_years,
        start_age=age if age is not None else store.get(site, landscape, "yield_curve")["age_median"],
        start_agb_mg_ha=agb0, start_agb_source=src, outcomes=outcomes, best_for_carbon=best,
        runs=runs or None, provenance=Provenance(parameters="; ".join(
            f"{m}: {store.source(site, landscape, m)}" for m in _models(growth_model))))


class AfforestationResult(BaseModel):
    landscape: str
    species: str
    area_ha: float
    planting_year: int
    horizon_years: int
    per_hectare: list[StandRun]
    total_cumulative_net_t_co2: dict[str, list[float]] = Field(
        description="Per growth model, [mean, p05, p95] over the whole planted area.")
    carbon_per_ha_per_year_t_co2: dict[str, float]
    ebcf_role: str = "response"
    provenance: Provenance


@server.tool(description=(
    "Carbon from new woodland: plant a species on bare land in a landscape's climate and soils "
    "and follow it for a horizon, per hectare and for the whole area (the hook DT10 calls for "
    "land-use transitions)."))
def afforestation_scenario(
    landscape: LandscapeKey,
    species: SpeciesCode,
    area_ha: Annotated[float, Field(gt=0, le=1_000_000)] = 100.0,
    planting_year: Annotated[int, Field(ge=2000, le=2100)] = 2026,
    horizon_years: Annotated[int, Field(ge=5, le=150)] = 50,
    growth_model: ModelChoice = "both",
    regime: RegimeName = "no_intervention",
    yield_class: Annotated[float, Field(ge=2, le=30)] | None = None,
    fertility_rating: Annotated[float, Field(ge=0, le=1)] | None = None,
    n_members: Annotated[int, Field(ge=1, le=200)] = 50,
    seed: int = 0,
) -> AfforestationResult:
    runs = [_run(m, species, landscape, landscape,
                 yield_class if m == "yield_curve" else fertility_rating,
                 age=0, years=horizon_years, start_year=planting_year, regime=regime,
                 events=[], stochastic=False, n_members=n_members, seed=seed)
            for m in _models(growth_model)]
    return AfforestationResult(
        landscape=landscape, species=species, area_ha=area_ha, planting_year=planting_year,
        horizon_years=horizon_years, per_hectare=runs,
        total_cumulative_net_t_co2={r.growth_model: [v * area_ha for v in r.cumulative_net_t_co2_ha]
                                    for r in runs},
        carbon_per_ha_per_year_t_co2={r.growth_model: r.mean_annual_net_t_co2_ha_yr for r in runs},
        provenance=Provenance(parameters="; ".join(
            f"{r.growth_model}: {r.productivity_source}" for r in runs)))


# --------------------------------------------------------------------------- #
# calibration, validation, learning
# --------------------------------------------------------------------------- #
class CalibrationResult(BaseModel):
    landscape: str
    area: str
    growth_model: str
    species: str
    productivity_name: str
    productivity_unit: str
    fit_years: list[int]
    holdout_years: list[int]
    n_pixels: int
    n_restocked_in_fit: int
    productivity_median: float
    productivity_p25: float
    productivity_p75: float
    productivity_at_grid_edge_frac: float
    stand_age_median_2024: float
    fit: ModelSkill
    holdout: ModelSkill | None
    residual_mean_pre_2013_mg_ha: float | None
    residual_mean_post_2014_mg_ha: float | None
    stored_for_site: str | None
    provenance: Provenance


def _cal_result(landscape, area_desc, c, stored) -> CalibrationResult:
    h = c.get("holdout")
    return CalibrationResult(
        landscape=landscape, area=area_desc, growth_model=c["model"], species=c["species"],
        productivity_name=c["productivity_name"], productivity_unit=c["productivity_unit"],
        fit_years=c["fit_years"], holdout_years=c["holdout_years"], n_pixels=c["n_pixels"],
        n_restocked_in_fit=c["n_restocked_in_fit"], productivity_median=c["theta_median"],
        productivity_p25=c["theta_p25"], productivity_p75=c["theta_p75"],
        productivity_at_grid_edge_frac=c["theta_at_grid_edge_frac"],
        stand_age_median_2024=c["age_median_last_cci_year"], fit=ModelSkill(**c["fit"]),
        holdout=ModelSkill(**{k: h[k] for k in ("rmse_mg_ha", "bias_mg_ha", "r2", "n")}) if h else None,
        residual_mean_pre_2013_mg_ha=c["residual_mean_pre_2013_mg_ha"],
        residual_mean_post_2014_mg_ha=c["residual_mean_post_2014_mg_ha"],
        stored_for_site=stored, provenance=Provenance(parameters="fitted here to CCI v7"))


class CalibrationList(BaseModel):
    results: list[CalibrationResult]


@server.tool(description=(
    "Calibrate the yield-curve model, 3-PG or both to Biomass CCI v7 pixel by pixel for a "
    "landscape or area: productivity distribution, stand ages, fit skill and, with a fit end "
    "year, hold-out skill. Optionally store the result as the site's productivity."))
def calibrate_site(
    landscape: LandscapeKey,
    growth_model: ModelChoice = "both",
    area: AreaSpec | None = None,
    fit_end_year: Annotated[int, Field(ge=2010, le=2024, description=(
        "Fit on CCI years up to this year; later years are held out for validation."))] = 2024,
    n_sample: Annotated[int, Field(ge=50, le=5000)] = 1000,
    store_for_site: Site | None = None,
    seed: int = 0,
) -> CalibrationList:
    cube, mask, a = _mask(landscape, area)
    ls = m_ls.get(landscape)
    fit_years = [y for y in cube.years if y <= fit_end_year]
    hold = [y for y in cube.years if y > fit_end_year]
    out = []
    for m in _models(growth_model):
        model = make_model(m, ls.species, ls)
        c = m_cal.calibrate(model, cube, mask, fit_years, hold, n_sample=n_sample, seed=seed)
        if store_for_site:
            store.set(store_for_site, landscape, m, {
                "theta": c["theta_median"],
                "theta_sd": max((c["theta_p75"] - c["theta_p25"]) / 1.349, 1e-6),
                "age_median": c["age_median_last_cci_year"],
                "age_ref_year": c["last_cci_year"], "species": ls.species},
                note=f"calibrate_site on {a.describe()}, CCI {fit_years[0]}-{fit_years[-1]}")
        out.append(_cal_result(landscape, a.describe(), c, store_for_site))
    return CalibrationList(results=out)


class ValidationRow(BaseModel):
    landscape: str
    growth_model: str
    productivity_median: float
    holdout: ModelSkill
    pixels_excluded_for_harvest: int
    holdout_landscape_mean_observed: list[float]
    holdout_landscape_mean_model: list[float]


class ValidationResult(BaseModel):
    fit_years: list[int]
    holdout_years: list[int]
    rows: list[ValidationRow]
    better_model: dict[str, str] = Field(description="Per landscape, the model with lower "
                                                     "hold-out RMSE.")
    method: str
    provenance: Provenance


@server.tool(description=(
    "Hold-out validation of both growth models against Biomass CCI v7: fitted on 2005-2017, "
    "scored on 2018-2024 (pixels felled in those years excluded). Compares yield curves and 3-PG."))
def validate(landscapes: Annotated[list[LandscapeKey], Field(min_length=1, max_length=2)] = [
        "thetford", "kielder"]) -> ValidationResult:
    rows, better = [], {}
    meta = None
    for key in landscapes:
        best = None
        for m in GROWTH_MODELS:
            v = shipped_calibration()[key][m]["validation"]
            meta = v
            h = v["holdout"]
            rows.append(ValidationRow(
                landscape=key, growth_model=m, productivity_median=v["theta_median"],
                holdout=ModelSkill(**{k: h[k] for k in ("rmse_mg_ha", "bias_mg_ha", "r2", "n")}),
                pixels_excluded_for_harvest=h["pixels_excluded_for_harvest"],
                holdout_landscape_mean_observed=v["holdout_landscape_mean_observed"],
                holdout_landscape_mean_model=v["holdout_landscape_mean_model"]))
            if best is None or h["rmse_mg_ha"] < best[1]:
                best = (m, h["rmse_mg_ha"])
        better[key] = best[0]
    return ValidationResult(
        fit_years=meta["fit_years"], holdout_years=meta["holdout_years"], rows=rows,
        better_model=better,
        method="Pixel-by-pixel fit of productivity and age on a fixed sample of 2000 woodland "
               "pixels per landscape; scores are over pixel-years in the hold-out period.",
        provenance=Provenance(parameters="shipped calibration (scripts/calibrate_pilots.py)"))


class ObservationIn(BaseModel):
    year: Annotated[int, Field(ge=1950, le=2100)]
    agb_mg_ha: Annotated[float, Field(ge=0, le=2000)]
    sd_mg_ha: Annotated[float, Field(gt=0, le=1000)]


class AssimilationYear(BaseModel):
    year: int
    forecast_agb_mean: float
    forecast_agb_sd: float
    observed_agb: float | None = None
    observed_sd: float | None = None
    innovation: float | None = None
    analysis_agb_mean: float
    analysis_agb_sd: float
    productivity_mean: float
    productivity_sd: float


class AssimilationResult(BaseModel):
    site: str
    landscape: str
    growth_model: str
    productivity_name: str
    data: str
    prior_productivity: float
    prior_productivity_sd: float
    posterior_productivity: float
    posterior_productivity_sd: float
    final_agb_mean_mg_ha: float
    final_agb_sd_mg_ha: float
    years: list[AssimilationYear]
    persisted: bool
    ebcf_role: str = "state"
    provenance: Provenance


def _assimilate(site, landscape, m, years, obs, sd, persist, data_desc, seed):
    ls = m_ls.get(landscape)
    model = make_model(m, ls.species, ls)
    prior = store.get(site, landscape, m)
    bank = curve_bank(m, ls.species, landscape)
    r = m_da.enkf(model, years, obs, sd, prior_theta=prior["theta"],
                  prior_theta_sd=max(prior["theta_sd"], 0.05 * prior["theta"] + 1e-3),
                  start_year=min(years), n_members=100, seed=seed, bank=bank)
    if persist:
        store.set(site, landscape, m, {
            "theta": r["theta_mean"], "theta_sd": r["theta_sd"],
            "age_median": prior["age_median"], "age_ref_year": prior["age_ref_year"],
            "species": ls.species}, note=f"EnKF on {data_desc}")
    return AssimilationResult(
        site=site, landscape=landscape, growth_model=m, productivity_name=model.productivity_name,
        data=data_desc, prior_productivity=prior["theta"], prior_productivity_sd=prior["theta_sd"],
        posterior_productivity=r["theta_mean"], posterior_productivity_sd=r["theta_sd"],
        final_agb_mean_mg_ha=r["agb_mean"], final_agb_sd_mg_ha=r["agb_sd"],
        years=[AssimilationYear(productivity_mean=y["theta_mean"], productivity_sd=y["theta_sd"],
                                **{k: v for k, v in y.items() if k not in ("theta_mean", "theta_sd", "gain")})
               for y in r["years"]],
        persisted=persist, provenance=Provenance(parameters=store.source(site, landscape, m)))


class AssimilationList(BaseModel):
    results: list[AssimilationResult]


@server.tool(description=(
    "Run the ensemble Kalman filter for a site: blend the growth model with AGB observations "
    "(the CCI v7 series of an area by default, or your own values) and learn the site's "
    "productivity. The learned value is stored for the site unless persist is false."))
def assimilate_agb(
    landscape: LandscapeKey,
    site: Site,
    growth_model: ModelChoice = "both",
    area: AreaSpec | None = None,
    observations: Annotated[list[ObservationIn], Field(max_length=200)] | None = None,
    persist: bool = True,
    seed: int = 0,
) -> AssimilationList:
    if observations:
        years = [o.year for o in observations]
        obs = [o.agb_mg_ha for o in observations]
        sd = [o.sd_mg_ha for o in observations]
        desc = f"{len(observations)} supplied AGB observations"
    else:
        cube, mask, a = _mask(landscape, area)
        rows = [cci.area_stats(cube, y, mask) for y in cube.years]
        years = [r["year"] for r in rows]
        obs = [r["agb_mean_mg_ha"] for r in rows]
        sd = [r["agb_sd_mg_ha"] for r in rows]
        desc = f"CCI v7 {years[0]}-{years[-1]}, {a.describe()}"
    return AssimilationList(results=[_assimilate(site, landscape, m, years, obs, sd, persist,
                                                 desc, seed) for m in _models(growth_model)])


class SiteParameters(BaseModel):
    site: str
    landscape: str
    growth_model: str
    productivity_name: str
    productivity: float
    productivity_sd: float
    stand_age_median: float
    source: str


class ParameterList(BaseModel):
    parameters: list[SiteParameters]
    sites_with_learned_values: list[str]


@server.tool(description="Show a site's current productivity for each growth model and where "
                         "it came from (CCI calibration baseline or learned).")
def get_parameters(landscape: LandscapeKey, site: Site | None = None) -> ParameterList:
    site = site or landscape
    ls = m_ls.get(landscape)
    rows = []
    for m in GROWTH_MODELS:
        p = store.get(site, landscape, m)
        rows.append(SiteParameters(site=site, landscape=landscape, growth_model=m,
                                   productivity_name=make_model(m, ls.species, ls).productivity_name,
                                   productivity=p["theta"], productivity_sd=p["theta_sd"],
                                   stand_age_median=p["age_median"],
                                   source=store.source(site, landscape, m)))
    return ParameterList(parameters=rows, sites_with_learned_values=store.sites())


@server.tool(description="Forget a site's learned productivity (one growth model or both) and "
                         "return to the CCI calibration baseline.")
def reset_parameters(landscape: LandscapeKey, site: Site,
                     growth_model: ModelChoice = "both") -> ParameterList:
    for m in _models(growth_model):
        store.reset(site, m)
    return get_parameters(landscape, site)


class SyntheticResult(BaseModel):
    growth_model: str
    productivity_name: str
    true_productivity: float
    prior_productivity: float
    recovered_productivity: float
    recovered_sd: float
    abs_error_before: float
    abs_error_after: float
    n_observations: int


@server.tool(description=(
    "Self-learning check: generate noisy AGB observations from a growth model with a known "
    "productivity, start the Kalman filter from a wrong prior, and report how close it gets."))
def self_learn_synthetic(
    landscape: LandscapeKey = "kielder",
    growth_model: ModelName = "yield_curve",
    true_productivity: float | None = None,
    prior_productivity: float | None = None,
    start_age: Annotated[float, Field(ge=0, le=100)] = 10.0,
    noise_fraction: Annotated[float, Field(ge=0, le=0.5)] = 0.15,
    seed: int = 1,
) -> SyntheticResult:
    ls = m_ls.get(landscape)
    model = make_model(growth_model, ls.species, ls)
    bank = curve_bank(growth_model, ls.species, landscape)
    grid = bank.grid
    if true_productivity is None:
        true_productivity = float(np.quantile(grid, 0.7))
    if prior_productivity is None:
        prior_productivity = float(np.quantile(grid, 0.3))
    syn = m_da.synthetic_observations(model, theta_true=true_productivity, age_start=start_age,
                                      years=cci.CCI_YEARS, noise_frac=noise_fraction, seed=seed,
                                      bank=bank)
    r = m_da.enkf(model, syn["years"], syn["obs"], syn["sd"], prior_theta=prior_productivity,
                  prior_theta_sd=(grid[-1] - grid[0]) / 4.0, start_year=syn["years"][0],
                  prior_age=start_age, n_members=100, seed=seed, bank=bank)
    return SyntheticResult(growth_model=growth_model, productivity_name=model.productivity_name,
                           true_productivity=true_productivity,
                           prior_productivity=prior_productivity,
                           recovered_productivity=r["theta_mean"], recovered_sd=r["theta_sd"],
                           abs_error_before=abs(prior_productivity - true_productivity),
                           abs_error_after=abs(r["theta_mean"] - true_productivity),
                           n_observations=len(syn["years"]))


if __name__ == "__main__":
    if "--http" in sys.argv:
        server.run("streamable-http", host=os.environ.get("DT4_HOST", "127.0.0.1"),
                   port=int(os.environ.get("DT4_PORT", "8000")))
    else:
        server.run("stdio")
