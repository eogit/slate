"""DT6 agent: the trees-outside-woodland biomass and carbon twin as an MCP server.

The science lives in the ``trees`` package next to this file. DT6 takes every lone tree,
group of trees and small woodland outside the NFI woodland map from the National Trees
Outside Woodland map (Forest Research 2025), measures their heights with Environment Agency
lidar at every epoch flown since 1998, calibrates two interchangeable growth models (an
empirical size-age curve and a process-based crown light-use model driven by HadUK-Grid
climate) crown by crown against those heights, and projects biomass and carbon under
baseline, ash-dieback and planting scenarios. Ten 5 km pilot tiles cover the English regions.

Boundaries agreed with the other twins: DT4 owns NFI woodland (including NFI overhanging
canopy); DT5 owns hedges below 3 m; DT6 owns every TOW object with canopy above 3 m. DT6 hands
the carbon it sheds to the soil (``to_soil``) to DT7.

An orchestrator (or any MCP client) can launch it over stdio:

    python dt6_agent/dt6_server.py

Run with ``--http`` to serve over streamable HTTP instead (default port 8000; ``DT6_PORT``).
Set ``DT6_STATE_FILE`` to a JSON path to keep learned site parameters across restarts.

Conventions (shared with DT4 and DT8): positive flux = emission to the atmosphere. Biomass in
tonnes dry matter (t DM), carbon in t C, CO2 in t CO2, for the selected trees (not per
hectare: these are scattered objects); per-hectare values are given per hectare of canopy
and per hectare of land. Every result carries an EBCF role (state, impact, pressure or
response) and provenance.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from trees import GROWTH_MODELS, MODEL_VERSION  # noqa: E402
from trees import allometry as m_al  # noqa: E402
from trees import assimilation as m_da  # noqa: E402
from trees import calibration as m_cal  # noqa: E402
from trees import change as m_chg  # noqa: E402
from trees import inventory as m_inv  # noqa: E402
from trees import pilots as m_pl  # noqa: E402
from trees import scenario as m_sc  # noqa: E402
from trees.state import ParameterStore, crown_fit, height_bank  # noqa: E402
from trees.state import calibration as shipped_calibration  # noqa: E402

VERSION = MODEL_VERSION
store = ParameterStore(os.environ.get("DT6_STATE_FILE") or None)

PilotKey = Literal["breckland", "fens", "mid_devon", "somerset_levels", "herefordshire",
                   "leicestershire", "vale_of_york", "cheshire", "oxford", "tyne_valley"]
ModelName = Literal["size_age", "crown_lue"]
ModelChoice = Literal["size_age", "crown_lue", "both"]
TowClass = Literal["lone_tree", "group_of_trees", "small_woodland"]
Site = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$",
                            description="Site id; each site keeps its own learned productivity "
                                        "shift. Defaults to the pilot key.")]
Z90 = 1.645

ASSUMPTIONS = [
    "Inventory: National Trees Outside Woodland map V1 (lone trees, groups of trees, small "
    "woodlands; canopy > 3 m outside NFI woodland). NFI overhanging canopy is left to DT4, "
    "hedges below 3 m to DT5.",
    "Calibrated on Environment Agency lidar canopy heights only: first and last return of the "
    "National LIDAR Programme and last-return LIDAR Tiles DSMs back to 1998, all above the NLP "
    "terrain model.",
    "Biomass from crown size and height with Jucker et al. (2017); trees in groups share the "
    "object's crown area equally; leaf type is a pilot prior (no open leaf-type map for TOW).",
    "Crown light-use model climate: HadUK-Grid 1991-2020 monthly averages; radiation from "
    "Hargreaves-Samani.",
    "Trees removed before the TOW map was made (2016-2023 lidar) are not in the inventory, so "
    "their loss is not seen.",
]


class Provenance(BaseModel):
    model: str = f"DT6 trees-outside-woodland twin {VERSION}"
    observations: str = ("Environment Agency LIDAR: National LIDAR Programme DSM/DTM and "
                         "LIDAR Tiles DSM (1998 onwards), environment.data.gov.uk")
    inventory: str = m_inv.CITATION
    allometry: str = m_al.CITATION
    licence: str = "Open Government Licence v3.0 (TOW map, EA lidar, HadUK-Grid)"
    parameters: str = Field(default="", description="Where the productivity came from.")
    assumptions: list[str] = Field(default_factory=lambda: list(ASSUMPTIONS))


class AreaSpec(BaseModel):
    """Part of a pilot tile. Omit for the whole tile."""

    bbox: Annotated[list[float], Field(min_length=4, max_length=4, description=(
        "[west, south, east, north] in degrees (EPSG:4326)."))] | None = None
    point: Annotated[list[float], Field(min_length=2, max_length=2, description=(
        "[lon, lat] in degrees."))] | None = None
    radius_m: Annotated[float, Field(ge=0, le=5000, description=(
        "Radius around the point; 0 = the object nearest the point."))] = 0.0

    def describe(self) -> str:
        if self.bbox:
            return f"bbox {self.bbox}"
        if self.point:
            return f"{self.radius_m:.0f} m around {self.point}"
        return "whole tile"


server = MCPServer(
    name="dt6",
    instructions=(
        "DT6 trees-outside-woodland agent: biomass and carbon of lone trees, groups of trees "
        "and small woodlands outside NFI woodland in ten 5 km pilot tiles across England "
        "(list_landscapes). The inventory is the National Trees Outside Woodland map; heights "
        "come from Environment Agency lidar at every epoch since 1998, and two growth models "
        "(size_age: height-age curve indexed by site index; crown_lue: crown light-use model "
        "on HadUK-Grid climate) are calibrated crown by crown against them. Results carry "
        "uncertainty (90 % ranges) and an EBCF role: 'state' (observed stock), 'impact' "
        "(observed change), 'pressure' (attributed cause, only with evidence) or 'response' "
        "(scenario, not an observation). Units are tonnes for the selected trees. Sign "
        "convention: positive flux = emission to the atmosphere."),
    version=VERSION,
)


def _mask(inv: m_inv.Inventory, area: AreaSpec | None, tow_class: str | None = None):
    m = np.ones(inv.n, bool)
    if area and area.bbox:
        w, s, e, n = area.bbox
        m = (inv.lon >= w) & (inv.lon <= e) & (inv.lat >= s) & (inv.lat <= n)
    elif area and area.point:
        plon, plat = area.point
        d = np.hypot((inv.lon - plon) * 111_320.0 * math.cos(math.radians(plat)),
                     (inv.lat - plat) * 111_320.0)
        m = d <= area.radius_m if area.radius_m > 0 else (d == d.min())
    if tow_class:
        m &= inv.cls == m_inv.CLASSES.index(tow_class)
    if not m.any():
        where = area.describe() if area else "the tile"
        raise ValueError(f"no TOW objects{' of class ' + tow_class if tow_class else ''} in "
                         f"{where} of {inv.key}")
    return m


def _land_area_ha(key: str, area: AreaSpec | None) -> float:
    if area is None or (not area.bbox and not area.point):
        return m_pl.TILE_M ** 2 / 1e4
    if area.bbox:
        w, s, e, n = area.bbox
        p = m_pl.get(key)
        w, s = max(w, p.bbox_wsen[0]), max(s, p.bbox_wsen[1])
        e, n = min(e, p.bbox_wsen[2]), min(n, p.bbox_wsen[3])
        lat = 0.5 * (s + n)
        return max(e - w, 0) * 111_320 * math.cos(math.radians(lat)) * max(n - s, 0) * 111_320 / 1e4
    return math.pi * area.radius_m ** 2 / 1e4 if area.radius_m > 0 else 0.0


def _models(choice: str) -> list[str]:
    return list(GROWTH_MODELS) if choice == "both" else [choice]


# --------------------------------------------------------------------------- #
# catalogue
# --------------------------------------------------------------------------- #
class ModelSkill(BaseModel):
    growth_model: str
    productivity_name: str
    productivity_median: float
    productivity_p25: float
    productivity_p75: float
    age_median_years: float
    holdout_n: int
    holdout_years_ahead: float | None
    holdout_rmse_m: float | None
    persistence_rmse_m: float | None
    skill_vs_persistence: float | None


class LandscapeInfo(BaseModel):
    key: str
    name: str
    region: str
    landscape: str
    tile: str
    centre_lon_lat: list[float]
    bbox: list[float]
    conifer_share_prior: float
    lidar_epochs: list[int]
    objects: int | None
    trees: int | None
    canopy_area_ha: float | None
    observed_height_growth_m_yr: float | None
    calibration: list[ModelSkill]
    annual_rain_mm: float | None
    mean_temp_c: float | None
    notes: list[str]


class LandscapeList(BaseModel):
    landscapes: list[LandscapeInfo]
    growth_models: dict[str, str]


def _skills(key: str) -> list[ModelSkill]:
    entry = shipped_calibration().get("pilots", {}).get(key)
    out = []
    for name, r in (entry or {}).get("models", {}).items():
        c, v = r["calibration"], r.get("validation", {})
        out.append(ModelSkill(
            growth_model=name, productivity_name=c.get("theta_name", ""),
            productivity_median=c["theta_median"], productivity_p25=c["theta_p25"],
            productivity_p75=c["theta_p75"], age_median_years=c["age_median"],
            holdout_n=v.get("n", 0), holdout_years_ahead=v.get("years_ahead_median"),
            holdout_rmse_m=v.get("model", {}).get("rmse_m"),
            persistence_rmse_m=v.get("persistence", {}).get("rmse_m"),
            skill_vs_persistence=v.get("skill_vs_persistence")))
    return out


@server.tool(description="List the ten pilot tiles with their landscape, lidar epochs, TOW "
                         "inventory size, observed height growth, climate and the calibration "
                         "and hold-out skill of both growth models.")
def list_landscapes() -> LandscapeList:
    rows = []
    for key, p in m_pl.PILOTS.items():
        entry = shipped_calibration().get("pilots", {}).get(key, {})
        inv = entry.get("inventory", {})
        try:
            cl = p.climate
            rain, temp = cl.annual_rain_mm, cl.mean_temp_c
        except FileNotFoundError:
            rain = temp = None
        rows.append(LandscapeInfo(
            key=key, name=p.name, region=p.region, landscape=p.landscape, tile=p.tile,
            centre_lon_lat=[p.lon, p.lat], bbox=list(p.bbox_wsen),
            conifer_share_prior=p.p_conifer, lidar_epochs=entry.get("epochs", []),
            objects=inv.get("objects"), trees=inv.get("trees"),
            canopy_area_ha=inv.get("canopy_area_ha"),
            observed_height_growth_m_yr=entry.get("observed_growth", {}).get("median_m_yr"),
            calibration=_skills(key), annual_rain_mm=rain, mean_temp_c=temp,
            notes=list(p.notes)))
    return LandscapeList(landscapes=rows, growth_models={
        "size_age": "Chapman-Richards height-age curve; productivity = site index (m at 50 yr)",
        "crown_lue": "single-tree crown light-use model on monthly HadUK-Grid climate; "
                     "productivity = light-use efficiency multiplier (0-1)"})


# --------------------------------------------------------------------------- #
# state: inventory and carbon stock
# --------------------------------------------------------------------------- #
class ClassRow(BaseModel):
    tow_class: str
    objects: int
    trees: int
    canopy_area_ha: float
    height_median_m: float | None
    agb_t: float


class InventoryResult(BaseModel):
    pilot: str
    area: str
    land_area_ha: float
    objects: int
    trees: int
    canopy_area_ha: float
    canopy_cover_pct: float
    agb_t: float
    by_class: list[ClassRow]
    reference_lidar_year: int
    lidar_epochs: list[int]
    ebcf_role: str = "state"
    provenance: Provenance


@server.tool(description=(
    "The trees outside woodland of a pilot tile or part of it: objects, estimated trees, "
    "canopy area and cover, median height and AGB by class (lone tree, group, small wood)."))
def tree_inventory(pilot: PilotKey, area: AreaSpec | None = None) -> InventoryResult:
    inv = m_inv.load(pilot)
    m = _mask(inv, area)
    s = m_inv.summary(inv, m)
    land = _land_area_ha(pilot, area)
    return InventoryResult(
        pilot=pilot, area=area.describe() if area else "whole tile", land_area_ha=land,
        objects=s["objects"], trees=s["trees"], canopy_area_ha=s["canopy_area_ha"],
        canopy_cover_pct=100 * s["canopy_area_ha"] / land if land else 0.0, agb_t=s["agb_t"],
        by_class=[ClassRow(tow_class=r["class"], **{k: v for k, v in r.items() if k != "class"})
                  for r in s["by_class"]],
        reference_lidar_year=int(np.nanmax(inv.fz_date[m])),
        lidar_epochs=inv.epoch_year.tolist(), provenance=Provenance())


class CarbonStockResult(BaseModel):
    pilot: str
    area: str
    objects: int
    trees: int
    reference_lidar_year: int
    agb_t: float
    agb_p05_t: float
    agb_p95_t: float
    above_ground_c_t: float
    below_ground_c_t: float
    total_living_c_t: float
    total_living_co2_t: float
    c_t_per_ha_canopy: float
    c_t_per_ha_land: float
    uncertainty_parts_sd_t: dict[str, float]
    ebcf_role: str = "state"
    provenance: Provenance


@server.tool(description=(
    "Living biomass carbon (above and below ground) of the trees outside woodland in a pilot "
    "tile or part of it at the latest lidar date, with a 90 % range combining tree-level "
    "allometric error, systematic allometry error and unknown leaf type."))
def carbon_stock(pilot: PilotKey, area: AreaSpec | None = None,
                 tow_class: TowClass | None = None) -> CarbonStockResult:
    inv = m_inv.load(pilot)
    m = _mask(inv, area, tow_class)
    tree = m_al.agb_kg(inv.height_m[m], inv.crown_diam_m[m], inv.p_conifer) / 1000
    n = inv.n_trees[m]
    agb = float((tree * n).sum())
    var_tree = float((n * tree ** 2).sum() * (math.exp(m_al.SIGMA_TREE ** 2) - 1))
    sd_sys = m_al.SYSTEMATIC_SD * agb
    p = inv.p_conifer
    p_sd = math.sqrt(p * (1 - p) / (m_sc.P_CONIFER_CONCENTRATION + 1)) if 0 < p < 1 else 0.05
    lo = m_al.agb_kg(inv.height_m[m], inv.crown_diam_m[m], max(p - p_sd, 0)) / 1000
    hi = m_al.agb_kg(inv.height_m[m], inv.crown_diam_m[m], min(p + p_sd, 1)) / 1000
    sd_leaf = float(abs(((hi - lo) * n).sum()) / 2)
    sd = math.sqrt(var_tree + sd_sys ** 2 + sd_leaf ** 2)
    agc, bgc = m_al.living_carbon_t(agb * 1000)
    land = _land_area_ha(pilot, area)
    canopy = float(inv.area_m2[m].sum() / 1e4)
    return CarbonStockResult(
        pilot=pilot, area=area.describe() if area else "whole tile", objects=int(m.sum()),
        trees=int(n.sum()), reference_lidar_year=int(np.nanmax(inv.fz_date[m])), agb_t=agb,
        agb_p05_t=max(agb - Z90 * sd, 0.0), agb_p95_t=agb + Z90 * sd,
        above_ground_c_t=float(agc), below_ground_c_t=float(bgc),
        total_living_c_t=float(agc + bgc), total_living_co2_t=float((agc + bgc) * m_al.CO2_PER_C),
        c_t_per_ha_canopy=float((agc + bgc) / canopy) if canopy else 0.0,
        c_t_per_ha_land=float((agc + bgc) / land) if land else 0.0,
        uncertainty_parts_sd_t={"tree_allometry": math.sqrt(var_tree), "systematic": sd_sys,
                                "leaf_type": sd_leaf},
        provenance=Provenance())


# --------------------------------------------------------------------------- #
# impact and pressure: canopy change
# --------------------------------------------------------------------------- #
class ChangeResult(BaseModel):
    pilot: str
    area: str
    epoch1: int
    epoch2: int
    years_between_median: float
    objects_compared: int
    median_change_m: float | None
    median_growth_m_yr: float | None
    threshold_m: float
    significant_reductions: int
    significant_increases: int
    modification_reductions: int
    removal_candidates: int
    share_reduced: float
    agb_lost_t: float
    impact: str
    impact_rule: str
    available_epochs: list[int]
    caveat: str = ("Trees removed before the TOW map was made are not in the inventory, so "
                   "their loss cannot be seen; new trees are seen only if mapped today.")
    ebcf_role: str = "impact"
    provenance: Provenance


def _change(pilot, year1, year2, area, tow_class):
    inv = m_inv.load(pilot)
    m = _mask(inv, area, tow_class)
    return inv, m_chg.height_change(inv, year1, year2, m)


@server.tool(description=(
    "Canopy-height change of trees outside woodland between the two lidar epochs nearest the "
    "requested years: growth, and significant reductions (beyond the 90 % threshold) split "
    "into modification (still a tree) and removal candidates (below 3 m), with AGB lost."))
def canopy_change(pilot: PilotKey,
                  year1: Annotated[int, Field(ge=1998, le=2030)],
                  year2: Annotated[int, Field(ge=1998, le=2030)],
                  area: AreaSpec | None = None,
                  tow_class: TowClass | None = None) -> ChangeResult:
    inv, ch = _change(pilot, year1, year2, area, tow_class)
    return ChangeResult(pilot=pilot, area=area.describe() if area else "whole tile",
                        available_epochs=inv.epoch_year.tolist(), provenance=Provenance(),
                        **{k: v for k, v in ch.items() if not k.startswith("_")})


class EvidenceIn(BaseModel):
    pressure: Literal["felling", "tree_management", "ash_dieback", "disease", "storm",
                      "development"]
    year_from: Annotated[int, Field(ge=1990, le=2035)]
    year_to: Annotated[int, Field(ge=1990, le=2035)]
    bbox: Annotated[list[float], Field(min_length=4, max_length=4)] | None = None
    point: Annotated[list[float], Field(min_length=2, max_length=2)] | None = None
    radius_m: Annotated[float, Field(ge=0, le=5000)] = 0.0
    source: Annotated[str, Field(max_length=300, description="Where the evidence comes from, "
                                 "e.g. a felling licence, a tree-health survey, a planning "
                                 "consent.")] = ""


class Attribution(BaseModel):
    pressure: str
    source: str
    years: list[int]
    overlaps_in_time: bool
    attributed_objects: int
    share_of_reductions: float
    label: str


class AttributionResult(BaseModel):
    pilot: str
    epoch1: int
    epoch2: int
    reductions: int
    attributions: list[Attribution]
    unattributed_objects: int
    unattributed_share: float
    rule: str
    ebcf_role: str = "pressure"
    provenance: Provenance


@server.tool(description=(
    "Attribute significant canopy-height reductions between two epochs to pressures (felling, "
    "tree management, ash dieback, disease, storm, development) where you supply independent "
    "evidence that overlaps them in space and time. Without evidence reductions stay "
    "unattributed (Living Earth EBCF rule)."))
def attribute_change(pilot: PilotKey,
                     year1: Annotated[int, Field(ge=1998, le=2030)],
                     year2: Annotated[int, Field(ge=1998, le=2030)],
                     evidence: Annotated[list[EvidenceIn], Field(max_length=100)],
                     area: AreaSpec | None = None) -> AttributionResult:
    inv, ch = _change(pilot, year1, year2, area, None)
    ev = [m_chg.Evidence(e.pressure, e.year_from, e.year_to,
                         tuple(e.bbox) if e.bbox else None,
                         tuple(e.point) if e.point else None, e.radius_m, e.source)
          for e in evidence]
    r = m_chg.attribute(inv, ch, ev)
    return AttributionResult(pilot=pilot, epoch1=ch["epoch1"], epoch2=ch["epoch2"],
                             reductions=r["reductions"],
                             attributions=[Attribution(**a) for a in r["attributions"]],
                             unattributed_objects=r["unattributed_objects"],
                             unattributed_share=r["unattributed_share"], rule=r["rule"],
                             provenance=Provenance())


# --------------------------------------------------------------------------- #
# response: projections
# --------------------------------------------------------------------------- #
class Band(BaseModel):
    mean: list[float]
    p05: list[float]
    p95: list[float]


class TreeRun(BaseModel):
    growth_model: str
    productivity_name: str
    productivity_shift: float
    productivity_source: str
    years: list[int]
    n_objects: int
    n_trees: int
    living_c_t: Band
    deadwood_c_t: Band
    firewood_c_t: Band
    replanted_living_c_t: Band | None = None
    trees_alive: Band
    height_median_m: Band
    net_flux_t_co2_yr: Band = Field(description="Positive = emission.")
    cumulative_net_t_co2: list[float] = Field(description=(
        "[ensemble mean, 5th, 95th percentile] of CO2 exchanged with the atmosphere over the "
        "run; negative = removal."))
    mean_annual_net_t_co2_yr: float
    to_soil_t_c_yr: float = Field(description="Mean annual carbon shed to the soil, for DT7.")
    n_members: int


def _band(d: dict) -> Band:
    return Band(**{k: [round(float(x), 3) for x in v] for k, v in d.items()})


def _project(pilot, model, site, area, tow_class, *, years, start_year, n_members, seed,
             ash=None, replant_share=0.0, firewood_fraction=0.7) -> TreeRun:
    _, inv, fit, _ = crown_fit(pilot, model)
    m = _mask(inv, area, tow_class)
    sub = inv.select(m)
    sub_fit = m_cal.CrownFit(**{k: v[m] for k, v in fit.as_dict().items()})
    shift = store.theta_shift(site, pilot, model)
    r = m_sc.simulate(height_bank(pilot, model), sub, sub_fit, start_year=start_year,
                      years=years, n_members=n_members, seed=seed, theta_shift=shift, ash=ash,
                      replant_share=replant_share, firewood_fraction=firewood_fraction)
    cum = r["cumulative_net_t_co2"]
    flux = r["net_flux_t_co2_yr"]["mean"][1:]
    return TreeRun(
        growth_model=model, productivity_name=crown_fit(pilot, model)[0].theta_name,
        productivity_shift=shift, productivity_source=store.source(site, pilot, model),
        years=r["years"], n_objects=r["n_objects"], n_trees=r["n_trees"],
        living_c_t=_band(r["living_c_t"]), deadwood_c_t=_band(r["deadwood_c_t"]),
        firewood_c_t=_band(r["firewood_c_t"]),
        replanted_living_c_t=_band(r["replanted_living_c_t"]) if r["replanted_living_c_t"] else None,
        trees_alive=_band(r["trees_alive"]), height_median_m=_band(r["height_median_m"]),
        net_flux_t_co2_yr=_band(r["net_flux_t_co2_yr"]),
        cumulative_net_t_co2=[round(cum["mean"][-1], 3), round(cum["p05"][-1], 3),
                              round(cum["p95"][-1], 3)],
        mean_annual_net_t_co2_yr=round(float(np.mean(flux)), 3),
        to_soil_t_c_yr=round(float(np.mean(r["to_soil_t_c_yr"]["mean"][1:])), 4),
        n_members=r["n_members"])


class TreeResult(BaseModel):
    pilot: str
    area: str
    scenario: str
    runs: list[TreeRun]
    ebcf_role: str = "response"
    provenance: Provenance


Years = Annotated[int, Field(ge=1, le=100)]
StartYear = Annotated[int, Field(ge=2000, le=2100)]
Members = Annotated[int, Field(ge=5, le=200)]


@server.tool(description=(
    "Project the trees outside woodland of a tile or area forward with the size-age model, "
    "the crown light-use model, or both: living carbon, deadwood, firewood, trees alive, "
    "median height and net CO2 flux each year as an ensemble with 90 % ranges. Each object "
    "starts from its measured lidar height and grows with its own calibrated productivity "
    "(plus the site's learned shift)."))
def simulate_trees(pilot: PilotKey, area: AreaSpec | None = None,
                   tow_class: TowClass | None = None, growth_model: ModelChoice = "both",
                   years: Years = 30, start_year: StartYear = 2025, n_members: Members = 40,
                   seed: int = 0, site: Site | None = None) -> TreeResult:
    runs = [_project(pilot, mdl, site or pilot, area, tow_class, years=years,
                     start_year=start_year, n_members=n_members, seed=seed)
            for mdl in _models(growth_model)]
    return TreeResult(pilot=pilot, area=area.describe() if area else "whole tile",
                      scenario="baseline (background mortality only)", runs=runs,
                      provenance=Provenance(parameters="; ".join(
                          f"{r.growth_model}: {r.productivity_source}" for r in runs)))


@server.tool(description=(
    "Ash dieback scenario for the trees outside woodland of a tile or area: cumulative ash "
    "mortality m_max(1 - exp(-t/tau)) on the ash share of broadleaved trees, dead trees to "
    "firewood or deadwood, optional replanting of a share of the dead ash. Returns the "
    "baseline and the dieback run side by side for each growth model."))
def ash_dieback_scenario(
    pilot: PilotKey, area: AreaSpec | None = None, growth_model: ModelChoice = "size_age",
    ash_share: Annotated[float, Field(ge=0, le=1, description=(
        "Share of broadleaved TOW trees that are ash (default 0.15; no open map gives it)."))] = 0.15,
    final_mortality: Annotated[float, Field(ge=0, le=1)] = 0.8,
    tau_years: Annotated[float, Field(gt=0, le=50)] = 10.0,
    replant_share: Annotated[float, Field(ge=0, le=1, description=(
        "Share of dead ash replaced by new young trees."))] = 0.0,
    firewood_fraction: Annotated[float, Field(ge=0, le=1)] = 0.7,
    years: Years = 30, start_year: StartYear = 2025, n_members: Members = 40, seed: int = 0,
    site: Site | None = None,
) -> TreeResult:
    ash = {"ash_share": ash_share, "m_max": final_mortality, "tau_years": tau_years}
    runs = []
    for mdl in _models(growth_model):
        kw = dict(years=years, start_year=start_year, n_members=n_members, seed=seed)
        runs.append(_project(pilot, mdl, site or pilot, area, None, **kw))
        runs.append(_project(pilot, mdl, site or pilot, area, None, ash=ash,
                             replant_share=replant_share, firewood_fraction=firewood_fraction,
                             **kw))
    return TreeResult(pilot=pilot, area=area.describe() if area else "whole tile",
                      scenario=("runs alternate: baseline, then ash dieback "
                                f"(ash share {ash_share}, final mortality {final_mortality}, "
                                f"tau {tau_years} yr, replant {replant_share})"),
                      runs=runs, provenance=Provenance(parameters=store.source(
                          site or pilot, pilot, _models(growth_model)[0])))


class PlantingRun(BaseModel):
    growth_model: str
    productivity: float
    productivity_sd: float
    years: list[int]
    trees_alive: Band
    living_c_t: Band
    net_flux_t_co2_yr: Band
    cumulative_net_t_co2: list[float]
    to_soil_t_c_yr: float


class PlantingResult(BaseModel):
    pilot: str
    kind: str
    n_planted: int
    establishment_survival: float
    runs: list[PlantingRun]
    ebcf_role: str = "response"
    provenance: Provenance


@server.tool(description=(
    "New tree planting outside woodland (hedgerow trees, agroforestry, riparian buffers or "
    "urban trees) in a pilot's climate and calibrated productivity: trees alive, living "
    "carbon and net CO2 flux each year, with 90 % ranges."))
def planting_scenario(
    pilot: PilotKey,
    n_trees: Annotated[int, Field(ge=1, le=1_000_000)],
    kind: Literal["hedgerow", "agroforestry", "riparian", "urban"] = "hedgerow",
    growth_model: ModelChoice = "both", years: Years = 50, start_year: StartYear = 2025,
    n_members: Members = 40, seed: int = 0, site: Site | None = None,
) -> PlantingResult:
    runs = []
    for mdl in _models(growth_model):
        p = store.get(site or pilot, pilot, mdl)
        r = m_sc.planting(height_bank(pilot, mdl), p["theta"], p["theta_sd"], n_trees, kind,
                          m_pl.get(pilot).p_conifer, start_year, years, n_members, seed)
        cum = r["cumulative_net_t_co2"]
        runs.append(PlantingRun(growth_model=mdl, productivity=p["theta"],
                                productivity_sd=p["theta_sd"], years=r["years"],
                                trees_alive=_band(r["trees_alive"]),
                                living_c_t=_band(r["living_c_t"]),
                                net_flux_t_co2_yr=_band(r["net_flux_t_co2_yr"]),
                                cumulative_net_t_co2=[cum["mean"][-1], cum["p05"][-1],
                                                      cum["p95"][-1]],
                                to_soil_t_c_yr=float(np.mean(r["to_soil_t_c_yr"]["mean"][1:]))))
    return PlantingResult(pilot=pilot, kind=kind, n_planted=n_trees,
                          establishment_survival=m_sc.PLANTING_TYPES[kind]["survival"],
                          runs=runs, provenance=Provenance(
                              parameters=store.source(site or pilot, pilot, runs[0].growth_model)))


# --------------------------------------------------------------------------- #
# calibration, validation, learning
# --------------------------------------------------------------------------- #
class CalibrationResult(BaseModel):
    pilot: str
    area: str
    growth_model: str
    productivity_name: str
    pilot_prior: list[float] = Field(description="Empirical-Bayes prior [mean, sd] of the tile.")
    objects: int
    productivity_median: float
    productivity_p25: float
    productivity_p75: float
    productivity_sd_median: float
    age_median_years: float
    age_p25_years: float
    age_p75_years: float
    current_growth_m_yr_median: float
    share_seen_on_2plus_dates: float
    height_drop_events: int


class CalibrationList(BaseModel):
    results: list[CalibrationResult]
    ebcf_role: str = "state"
    provenance: Provenance


@server.tool(description=(
    "Crown-by-crown calibration of the growth models in a tile or area: productivity and tree "
    "age fitted to every lidar height of every object, summarised (median and quartiles), "
    "with the number of height-drop events (cutting, pollarding) found in the record."))
def calibrate_area(pilot: PilotKey, area: AreaSpec | None = None,
                   tow_class: TowClass | None = None,
                   growth_model: ModelChoice = "both") -> CalibrationList:
    out = []
    for mdl in _models(growth_model):
        model, inv, fit, prior = crown_fit(pilot, mdl)
        m = _mask(inv, area, tow_class)
        sub = m_cal.CrownFit(**{k: v[m] for k, v in fit.as_dict().items()})
        s = m_cal.summarise(sub, model)
        if not s.get("n"):
            raise ValueError("no calibrated objects in the selection")
        out.append(CalibrationResult(
            pilot=pilot, area=area.describe() if area else "whole tile", growth_model=mdl,
            productivity_name=model.theta_name, pilot_prior=list(prior), objects=s["n"],
            productivity_median=s["theta_median"], productivity_p25=s["theta_p25"],
            productivity_p75=s["theta_p75"], productivity_sd_median=s["theta_sd_median"],
            age_median_years=s["age_median"], age_p25_years=s["age_p25"],
            age_p75_years=s["age_p75"], current_growth_m_yr_median=s["growth_m_yr_median"],
            share_seen_on_2plus_dates=s["multi_epoch_share"],
            height_drop_events=int(np.isfinite(sub.event_year).sum())))
    return CalibrationList(results=out, provenance=Provenance())


class ValidationRow(BaseModel):
    pilot: str
    growth_model: str
    n: int
    years_ahead_median: float | None
    model_rmse_m: float | None
    model_bias_m: float | None
    persistence_rmse_m: float | None
    persistence_bias_m: float | None
    skill_vs_persistence: float | None
    observed_growth_m_yr: float | None
    predicted_growth_m_yr: float | None


class ValidationResult(BaseModel):
    rows: list[ValidationRow]
    method: str = ("Latest lidar epoch held out; each object fitted on its earlier epochs with "
                   "the pilot prior learned from the other half of the objects (two-fold); "
                   "forecast of the last-return height at the latest flight compared with "
                   "persistence (no growth since the previous epoch). Shipped results from "
                   "scripts/calibrate_pilots.py.")
    provenance: Provenance


@server.tool(description=(
    "Hold-out skill of both growth models in each pilot: forecast of the latest lidar height "
    "from earlier epochs, compared with a no-growth persistence baseline (RMSE, bias, skill)."))
def validate(pilots: Annotated[list[PilotKey], Field(min_length=1, max_length=10)] | None = None
             ) -> ValidationResult:
    rows = []
    cal = shipped_calibration().get("pilots", {})
    for key in pilots or list(m_pl.PILOTS):
        for mdl, r in cal.get(key, {}).get("models", {}).items():
            v = r.get("validation", {})
            rows.append(ValidationRow(
                pilot=key, growth_model=mdl, n=v.get("n", 0),
                years_ahead_median=v.get("years_ahead_median"),
                model_rmse_m=v.get("model", {}).get("rmse_m"),
                model_bias_m=v.get("model", {}).get("bias_m"),
                persistence_rmse_m=v.get("persistence", {}).get("rmse_m"),
                persistence_bias_m=v.get("persistence", {}).get("bias_m"),
                skill_vs_persistence=v.get("skill_vs_persistence"),
                observed_growth_m_yr=v.get("observed_growth_m_yr_median"),
                predicted_growth_m_yr=v.get("predicted_growth_m_yr_median")))
    return ValidationResult(rows=rows, provenance=Provenance())


class HeightObservation(BaseModel):
    tow_id: Annotated[str, Field(max_length=32)] | None = None
    lon: float | None = None
    lat: float | None = None
    year: Annotated[float, Field(ge=1998, le=2100, description="Decimal year of measurement.")]
    height_m: Annotated[float, Field(gt=0, le=60, description="Tallest height of the object.")]
    sd_m: Annotated[float, Field(gt=0, le=10)] = 1.0


class AssimilationResult(BaseModel):
    site: str
    pilot: str
    growth_model: str
    productivity_name: str
    n_observations: int
    n_matched: int
    productivity_shift: float
    productivity_shift_sd: float | None
    objects: list[dict]
    persisted: bool
    ebcf_role: str = "state"
    provenance: Provenance


class AssimilationList(BaseModel):
    results: list[AssimilationResult]


@server.tool(description=(
    "Learn from new tree heights (a new lidar flight, drone or field survey): match each "
    "measurement to a TOW object (by id, or the nearest within 15 m), update its productivity "
    "and age with an ensemble Kalman filter, and store the mean productivity shift for the "
    "site so later projections use it (unless persist is false)."))
def assimilate_heights(
    pilot: PilotKey, site: Site,
    observations: Annotated[list[HeightObservation], Field(min_length=1, max_length=2000)],
    growth_model: ModelChoice = "both", persist: bool = True, seed: int = 0,
) -> AssimilationList:
    obs = []
    for o in observations:
        if o.tow_id is None and (o.lon is None or o.lat is None):
            raise ValueError("each observation needs a tow_id or lon and lat")
        obs.append(o.model_dump())
    out = []
    for mdl in _models(growth_model):
        model, inv, fit, _ = crown_fit(pilot, mdl)
        r = m_da.assimilate(height_bank(pilot, mdl), inv, fit, obs, seed=seed)
        if persist and r["n_matched"]:
            store.set(site, pilot, mdl, store.theta_shift(site, pilot, mdl) + r["theta_shift"],
                      note=f"EnKF on {r['n_matched']} height observations")
        out.append(AssimilationResult(
            site=site, pilot=pilot, growth_model=mdl, productivity_name=model.theta_name,
            n_observations=r["n_observations"], n_matched=r["n_matched"],
            productivity_shift=r["theta_shift"], productivity_shift_sd=r["theta_shift_sd"],
            objects=r["objects"][:200], persisted=bool(persist and r["n_matched"]),
            provenance=Provenance(parameters=store.source(site, pilot, mdl))))
    return AssimilationList(results=out)


class SiteParameters(BaseModel):
    site: str
    pilot: str
    growth_model: str
    productivity_name: str
    productivity_median: float
    productivity_sd: float
    learned_shift: float
    age_median_years: float
    source: str


class ParameterList(BaseModel):
    parameters: list[SiteParameters]
    sites_with_learned_values: list[str]


@server.tool(description="Show a site's current productivity for each growth model (tile "
                         "calibration median plus any learned shift) and where it came from.")
def get_parameters(pilot: PilotKey, site: Site | None = None) -> ParameterList:
    site = site or pilot
    rows = []
    for mdl in GROWTH_MODELS:
        p = store.get(site, pilot, mdl)
        rows.append(SiteParameters(site=site, pilot=pilot, growth_model=mdl,
                                   productivity_name=p["theta_name"],
                                   productivity_median=p["theta"], productivity_sd=p["theta_sd"],
                                   learned_shift=p["theta_shift"],
                                   age_median_years=p["age_median"],
                                   source=store.source(site, pilot, mdl)))
    return ParameterList(parameters=rows, sites_with_learned_values=store.sites())


@server.tool(description="Forget a site's learned productivity shift (one growth model or "
                         "both) and return to the lidar calibration baseline.")
def reset_parameters(pilot: PilotKey, site: Site,
                     growth_model: ModelChoice = "both") -> ParameterList:
    for mdl in _models(growth_model):
        store.reset(site, mdl)
    return get_parameters(pilot, site)


if __name__ == "__main__":
    if "--http" in sys.argv:
        server.run("streamable-http", host=os.environ.get("DT6_HOST", "127.0.0.1"),
                   port=int(os.environ.get("DT6_PORT", "8000")))
    else:
        server.run("stdio")
