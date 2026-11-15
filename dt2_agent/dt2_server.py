"""DT2 agent: the livestock methane twin for England as an MCP server.

DT2 keeps a 1 km picture of England's cattle, sheep and goats and computes their enteric and
manure methane with the UK inventory factors that the Farm Carbon Calculator uses:

* head counts: Defra June Survey, England, 1 June 2020;
* where the animals are: Malek et al. (2024) livestock maps (Zenodo 10.5281/zenodo.13734518),
  redistributed onto Living England grassland (Natural England) and calibrated against the
  NAEI 1 km agricultural methane map;
* emission factors: UK GHG Inventory 1990-2023 (NID 2025) Tables A 5.1.8, A 5.1.9 and A 5.1.11.

An orchestrator (or any MCP client) launches it over stdio:

    python dt2_agent/dt2_server.py

Run with ``--http`` to serve over streamable HTTP (default port 8000). Set ``DT2_STATE_FILE``
to a JSON path to keep what sites have learned across restarts.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
from pydantic import BaseModel, Field, model_validator

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from livestock import assimilation as m_assim  # noqa: E402
from livestock import calibration as m_cal  # noqa: E402
from livestock import factors as m_f  # noqa: E402
from livestock import herd as m_herd  # noqa: E402
from livestock import maps as m_maps  # noqa: E402
from livestock import model as m  # noqa: E402
from livestock.grid import GRID  # noqa: E402
from livestock.state import ParameterStore  # noqa: E402

VERSION = "0.1.0"
store = ParameterStore(os.environ.get("DT2_STATE_FILE") or None)
CFG = m_cal.calibrated_config()

Group = Literal["dairy", "beef_other", "sheep", "goats"]
CategoryCode = Literal[tuple(m_f.CATEGORIES)]  # type: ignore[valid-type]
Site = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$",
                            description="Site id; each site keeps its own learned livestock "
                                        "factors. Defaults to 'default' (no learning).")]
Gwp = Literal["AR5", "AR6"]


class AreaIn(BaseModel):
    """Where in England. Give a BNG box, or a WGS84 point and radius; nothing = all England."""
    bbox_bng: list[float] | None = Field(
        None, min_length=4, max_length=4,
        description="[xmin, ymin, xmax, ymax] in British National Grid metres (EPSG:27700).")
    lat: float | None = Field(None, ge=49.8, le=55.9, description="Latitude (WGS84).")
    lon: float | None = Field(None, ge=-6.5, le=2.0, description="Longitude (WGS84).")
    radius_km: float | None = Field(None, gt=0, le=200, description="Radius around lat/lon.")

    @model_validator(mode="after")
    def _one_kind(self):
        point = [self.lat, self.lon, self.radius_km]
        if self.bbox_bng is not None and any(v is not None for v in point):
            raise ValueError("give either bbox_bng or lat/lon/radius_km, not both")
        if any(v is not None for v in point) and not all(v is not None for v in point):
            raise ValueError("lat, lon and radius_km go together")
        if self.bbox_bng is not None:
            x0, y0, x1, y1 = self.bbox_bng
            if not (x1 > x0 and y1 > y0):
                raise ValueError("bbox_bng must be [xmin, ymin, xmax, ymax] with max > min")
        return self

    def area(self) -> m.Area:
        return m.Area(bbox_bng=tuple(self.bbox_bng) if self.bbox_bng else None,
                      lat=self.lat, lon=self.lon, radius_km=self.radius_km)


class Provenance(BaseModel):
    model: str = "DT2 livestock methane twin " + VERSION
    emission_factors: str = m_f.FACTOR_SOURCE
    head_counts: str = m_herd.CENSUS_SOURCE
    livestock_maps: str = m_maps.MALEK_SOURCE
    grassland_map: str = m_maps.LE_SOURCE
    allocation: str = Field(description="Calibrated allocation configuration.")
    site_factors: str = Field(description="Where the site's livestock factors came from.")
    gwp100: str = "CH4: AR5 28 (Farm Carbon Calculator), AR6 27 (non-fossil)"


def _prov(site: str) -> Provenance:
    return Provenance(allocation=str(CFG.__dict__), site_factors=store.source(site))


def _scales(site: str) -> dict[str, float]:
    p = store.get(site)
    return {"cattle": p["cattle"], "sheep": p["sheep"]}


def _mask(area: AreaIn | None) -> tuple[m.Area, np.ndarray]:
    a = (area or AreaIn()).area()
    mk = a.mask()
    if not mk.any():
        raise ToolError("the area contains no 1 km cell of England (Living England coverage)")
    return a, mk


server = MCPServer(
    name="dt2",
    instructions=(
        "DT2 livestock agent: enteric and manure methane from cattle, sheep and goats in England "
        "on a 1 km grid, with the UK inventory emission factors used by the Farm Carbon "
        "Calculator. Areas are a British National Grid box, a point and radius, or all England. "
        "Gives livestock numbers, grassland (Living England), methane in t CH4 and t CO2e, "
        "scenarios (herd size, grazing share, anaerobic digestion, feed additives, grassland "
        "loss, stocking caps), farm-level calculations, validation against the NAEI map and "
        "per-site learning from methane observations. Positive = emission to the atmosphere. "
        "Scenario outputs are what-if responses, not observations."),
    version=VERSION,
)


# --------------------------------------------------------------------------- #
# catalogue
# --------------------------------------------------------------------------- #
class CategoryInfo(BaseModel):
    code: str
    name: str
    species: str
    enteric_kg_ch4_head_yr: float
    manure_kg_ch4_head_yr: float
    manure_systems_pct: dict[str, float] = Field(description="Inventory 2023 share of excreta "
                                                             "per manure system.")
    mcf_weighted_pct: float
    methane_potential_kg_head_yr: float = Field(description="VS x Bo x 0.67, back-calculated "
                                                            "from the inventory manure EF.")


class CensusRow(BaseModel):
    census_row: str
    thousand_head: float
    category: str
    group: str


class Catalogue(BaseModel):
    categories: list[CategoryInfo]
    mcf_pct: dict[str, float]
    england_census_2020: list[CensusRow]
    group_factors_kg_head_yr: dict[str, dict[str, float]] = Field(
        description="Head-weighted enteric, manure and LSU per head of each group.")
    source: str = m_f.FACTOR_SOURCE


@server.tool(description="List DT2's livestock categories with their inventory methane factors, "
                         "manure systems, and England's June 2020 census mapped onto them.")
def list_categories() -> Catalogue:
    return Catalogue(
        categories=[CategoryInfo(code=c.code, name=c.name, species=c.species,
                                 enteric_kg_ch4_head_yr=c.enteric,
                                 manure_kg_ch4_head_yr=c.manure,
                                 manure_systems_pct=m_f.default_shares(c),
                                 mcf_weighted_pct=c.mcf_weighted(),
                                 methane_potential_kg_head_yr=c.methane_potential)
                    for c in m_f.CATEGORIES.values()],
        mcf_pct=m_f.MCF,
        england_census_2020=[CensusRow(census_row=r, thousand_head=k, category=c, group=g)
                             for r, k, c, g in m_herd.ENGLAND_2020],
        group_factors_kg_head_yr={g: m.per_head_factors(g) for g in m_herd.GROUPS})


# --------------------------------------------------------------------------- #
# farm scale
# --------------------------------------------------------------------------- #
class FarmCategoryResult(BaseModel):
    heads: float
    enteric_kg_ch4: float
    manure_kg_ch4: float


class FarmResult(BaseModel):
    by_category: dict[str, FarmCategoryResult]
    enteric_kg_ch4: float
    manure_kg_ch4: float
    total_kg_ch4: float
    t_co2e: float
    gwp: str
    method: str = ("Farm Carbon Calculator Tier 2: head x UK inventory EF (Eq. 1a); manure as "
                   "methane potential x share-weighted MCF (Eq. 4 form)")
    source: str = m_f.FACTOR_SOURCE


@server.tool(description=(
    "Methane of one farm's herd from head counts per category, exactly as the Farm Carbon "
    "Calculator's default Tier 2 does it (UK inventory factors). Optionally set the share of "
    "excreta deposited at pasture per category, and an enteric reduction (e.g. a feed additive)."))
def farm_methane(
    heads: Annotated[dict[CategoryCode, Annotated[float, Field(ge=0, le=1e6)]],
                     Field(min_length=1, description="Head count per category code.")],
    pasture_pct: Annotated[dict[CategoryCode, Annotated[float, Field(ge=0, le=100)]] | None,
                           Field(description="Share of excreta at pasture (%), per category; "
                                             "default the inventory mix.")] = None,
    enteric_reduction_pct: Annotated[
        dict[CategoryCode, Annotated[float, Field(ge=0, le=100)]] | None,
        Field(description="Enteric methane reduction (%), per category.")] = None,
    gwp: Gwp = "AR5",
) -> FarmResult:
    r = m_f.farm_methane(heads, gwp, pasture_pct=pasture_pct,
                         enteric_reduction_pct=enteric_reduction_pct)
    return FarmResult(
        by_category={k: FarmCategoryResult(heads=v["heads"], enteric_kg_ch4=v["enteric_kg"],
                                           manure_kg_ch4=v["manure_kg"])
                     for k, v in r["by_category"].items()},
        enteric_kg_ch4=r["enteric_kg"], manure_kg_ch4=r["manure_kg"],
        total_kg_ch4=r["total_kg"], t_co2e=r["t_co2e"], gwp=gwp)


# --------------------------------------------------------------------------- #
# area scale
# --------------------------------------------------------------------------- #
class GroupResult(BaseModel):
    heads: float
    lsu: float
    enteric_t_ch4: float
    manure_t_ch4: float
    total_t_ch4: float


class Grassland(BaseModel):
    improved_ha: float
    semi_natural_ha: float
    rough_grazing_ha: float
    land_ha: float


class AreaResult(BaseModel):
    area: str
    cells_km2: int
    groups: dict[str, GroupResult]
    enteric_t_ch4: float
    manure_t_ch4: float
    total_t_ch4: float
    t_co2e_ar5: float
    t_co2e_ar6: float
    lsu: float
    grassland: Grassland
    stocking_lsu_per_grazing_ha: float | None
    kg_ch4_per_grazing_ha: float | None
    site: str
    provenance: Provenance


def _area_result(a: m.Area, s: dict, site: str) -> AreaResult:
    return AreaResult(area=a.describe(), site=site, provenance=_prov(site),
                      **{k: v for k, v in s.items()})


@server.tool(description=(
    "Livestock and their methane in an area of England: heads, livestock units, enteric and "
    "manure CH4 per group (dairy, beef and other cattle, sheep, goats), CO2e (AR5 and AR6), "
    "Living England grassland and stocking rate."))
def area_methane(area: AreaIn | None = None, site: Site = "default") -> AreaResult:
    a, mk = _mask(area)
    return _area_result(a, m.summarise(m.emissions_grid(CFG, mk, _scales(site)), mk), site)


class ScenarioIn(BaseModel):
    herd_change_pct: dict[Group, Annotated[float, Field(ge=-100, le=200)]] = Field(
        default_factory=dict, description="Change in head count per group (%).")
    pasture_pct: dict[Group, Annotated[float, Field(ge=0, le=100)]] = Field(
        default_factory=dict, description="Share of excreta deposited at pasture (%), e.g. "
                                          "grazing days / 365 x 100. Inventory: dairy cows 20, "
                                          "other cattle 49, sheep 92-99.")
    ad_pct_of_housed: float | None = Field(None, ge=0, le=100, description=(
        "Share of housed cattle slurry and FYM sent to anaerobic digestion (%); inventory 2-6 %."))
    enteric_reduction_pct: dict[Group, Annotated[float, Field(ge=0, le=100)]] = Field(
        default_factory=dict, description=("Effective enteric CH4 reduction per group (%), e.g. "
                                           "a feed additive; give the herd-average effect."))
    grassland_loss_pct: float = Field(0.0, ge=0, le=100, description=(
        "Share of improved and semi-natural grassland converted (e.g. to woodland); grazing "
        "animals leave with it at unchanged stocking."))
    max_stocking_lsu_ha: float | None = Field(None, gt=0, le=10, description=(
        "Cap on livestock units per ha of grazing land in every 1 km cell."))

    def scenario(self) -> m.Scenario:
        return m.Scenario(**self.model_dump())


class ScenarioResult(BaseModel):
    baseline: AreaResult
    scenario: AreaResult
    change_t_ch4: float
    change_t_co2e_ar5: float
    change_pct: float
    interventions: ScenarioIn


@server.tool(description=(
    "What-if for an area: change herd sizes, the grazing share, anaerobic digestion of cattle "
    "manure, enteric methane (feed additives), grassland area or the maximum stocking rate, and "
    "compare methane with the baseline."))
def methane_scenario(interventions: ScenarioIn, area: AreaIn | None = None,
                     site: Site = "default") -> ScenarioResult:
    a, mk = _mask(area)
    sc = _scales(site)
    b = m.summarise(m.emissions_grid(CFG, mk, sc), mk)
    s = m.summarise(m.emissions_grid(CFG, mk, sc, interventions.scenario()), mk)
    d = s["total_t_ch4"] - b["total_t_ch4"]
    return ScenarioResult(baseline=_area_result(a, b, site), scenario=_area_result(a, s, site),
                          change_t_ch4=d, change_t_co2e_ar5=d * m_f.GWP100["AR5"],
                          change_pct=100.0 * d / b["total_t_ch4"] if b["total_t_ch4"] else 0.0,
                          interventions=interventions)


class Cell(BaseModel):
    easting: float = Field(description="Cell centre, BNG metres.")
    northing: float
    lat: float
    lon: float
    heads: dict[str, float]
    total_t_ch4: float
    naei_agriculture_t_ch4: float = Field(description="NAEI 2020 SNAP 10 methane in the same "
                                                      "cell (includes pigs and poultry).")
    improved_grassland_ha: float
    semi_natural_grassland_ha: float
    rough_grazing_ha: float


def _cell(i: int, j: int, grid: dict) -> Cell:
    from pyproj import Transformer
    L = m_maps.layers()
    x, y = GRID.centre(i, j)
    lon, lat = Transformer.from_crs(27700, 4326, always_xy=True).transform(x, y)
    return Cell(easting=x, northing=y, lat=lat, lon=lon,
                heads={g: float(d["heads"][i, j]) for g, d in grid.items()},
                total_t_ch4=float(sum(d["enteric"][i, j] + d["manure"][i, j]
                                      for d in grid.values())),
                naei_agriculture_t_ch4=float(L["naei_ch4_t"][i, j]),
                improved_grassland_ha=float(L["improved_grassland"][i, j]),
                semi_natural_grassland_ha=float(L["semi_natural_grassland"][i, j]),
                rough_grazing_ha=float(L["rough_grazing"][i, j]))


class Hotspots(BaseModel):
    area: str
    cells: list[Cell]
    share_of_area_total: float = Field(description="Fraction of the area's methane in these "
                                                   "cells.")
    provenance: Provenance


@server.tool(description="The 1 km cells with the most livestock methane in an area, with their "
                         "animals, grassland and the NAEI value for comparison.")
def methane_hotspots(area: AreaIn | None = None,
                     n: Annotated[int, Field(ge=1, le=100)] = 10,
                     site: Site = "default") -> Hotspots:
    a, mk = _mask(area)
    grid = m.emissions_grid(CFG, mk, _scales(site))
    tot = sum(d["enteric"] + d["manure"] for d in grid.values())
    idx = np.argsort(np.where(mk, tot, -1).ravel())[::-1][:n]
    cells = [_cell(*np.unravel_index(k, GRID.shape), grid) for k in idx if mk.ravel()[k]]
    return Hotspots(area=a.describe(), cells=cells, provenance=_prov(site),
                    share_of_area_total=float(sum(c.total_t_ch4 for c in cells) / tot.sum()))


@server.tool(description="Livestock, methane and grassland of the single 1 km cell at a point.")
def cell_profile(lat: Annotated[float, Field(ge=49.8, le=55.9)],
                 lon: Annotated[float, Field(ge=-6.5, le=2.0)],
                 site: Site = "default") -> Cell:
    x, y = m.to_bng(lat, lon)
    i, j = GRID.index(x, y)
    if not (0 <= i < GRID.ny and 0 <= j < GRID.nx) or not m_maps.layers()["england"][i, j]:
        raise ToolError("the point is not in England")
    mk = np.zeros(GRID.shape, bool)
    mk[i, j] = True
    return _cell(i, j, m.emissions_grid(CFG, mk, _scales(site)))


class GrasslandMap(BaseModel):
    area: str
    living_england_ha: dict[str, float]
    grazing_groups_ha: Grassland
    source: str = m_maps.LE_SOURCE


@server.tool(description="Area of every Living England habitat class in an area (ha), and the "
                         "grazing groups DT2 uses (improved, semi-natural, rough grazing).")
def grassland_map(area: AreaIn | None = None) -> GrasslandMap:
    a, mk = _mask(area)
    le = np.load(m_maps.DATA / "living_england_1km.npz")
    classes = {str(c): float(np.where(mk, h, 0.0).sum()) for c, h in zip(le["classes"], le["ha"])}
    g = m.grassland(mk)
    return GrasslandMap(area=a.describe(), living_england_ha=classes,
                        grazing_groups_ha=Grassland(**{k: v for k, v in g.items()
                                                       if k != "grazing_ha_cell"}))


# --------------------------------------------------------------------------- #
# validation and calibration
# --------------------------------------------------------------------------- #
class Skill(BaseModel):
    r_1km: float | None = None
    r_5km: float | None = None
    r_10km: float | None = None
    r_20km: float | None = None
    dt2_t_ch4: float
    naei_t_ch4: float
    ratio_dt2_to_naei: float | None


class Validation(BaseModel):
    area: str
    skill: Skill
    shipped_holdout: Skill = Field(description="Calibrated allocation on the hold-out half of "
                                               "England.")
    malek_only_holdout: Skill = Field(description="Malek layers without Living England, same "
                                                  "hold-out.")
    allocation: dict[str, float]
    note: str = ("NAEI SNAP 10 also contains pigs, poultry, horses and deer (about 5-10 % in "
                 "England), so DT2 is expected to be slightly below it.")


@server.tool(description=(
    "Compare DT2's methane map with the NAEI 2020 1 km agricultural methane map over an area: "
    "Pearson r at 1, 5, 10 and 20 km and the ratio of totals, plus the shipped hold-out scores."))
def validate_naei(area: AreaIn | None = None, site: Site = "default") -> Validation:
    a, mk = _mask(area)
    grid = m.emissions_grid(CFG, mk, _scales(site))
    pred = sum(d["enteric"] + d["manure"] for d in grid.values())
    cal = m_cal.load()
    return Validation(area=a.describe(), skill=Skill(**m_cal.skill(pred, mk)),
                      shipped_holdout=Skill(**cal["holdout"]),
                      malek_only_holdout=Skill(
                          **cal["reference_holdout"]["malek_all_layers_no_living_england"]),
                      allocation=CFG.__dict__)


class CalibrationReport(BaseModel):
    chosen: dict[str, float]
    holdout: Skill
    calibration: Skill
    england: Skill
    reference_holdout: dict[str, Skill]
    best_trials: list[dict] = Field(description="The ten best configurations on the "
                                                "calibration squares.")
    method: str


@server.tool(description="The shipped calibration of the livestock allocation against the NAEI "
                         "map: chosen configuration, hold-out skill and the best alternatives.")
def calibration_report() -> CalibrationReport:
    c = m_cal.load()
    best = sorted(c["trials"], key=lambda t: -t["calibration"]["r_1km"])[:10]
    return CalibrationReport(
        chosen=c["chosen"], holdout=Skill(**c["holdout"]), calibration=Skill(**c["calibration"]),
        england=Skill(**c["england"]),
        reference_holdout={k: Skill(**v) for k, v in c["reference_holdout"].items()},
        best_trials=[{**t["config"], "r_1km_calibration": t["calibration"]["r_1km"]}
                     for t in best],
        method=c["method"])


# --------------------------------------------------------------------------- #
# learning
# --------------------------------------------------------------------------- #
class SiteParameters(BaseModel):
    site: str
    cattle: float = Field(description="Factor on DT2's cattle numbers in the site.")
    sheep: float = Field(description="Factor on DT2's sheep and goat numbers in the site.")
    cattle_sd: float
    sheep_sd: float
    source: str
    known_sites: list[str]


def _params(site: str) -> SiteParameters:
    p = store.get(site)
    return SiteParameters(site=site, cattle=p["cattle"], sheep=p["sheep"],
                          cattle_sd=p["cattle_sd"], sheep_sd=p["sheep_sd"],
                          source=store.source(site), known_sites=store.sites())


@server.tool(description="Show a site's livestock factors (1 = June Survey totals as allocated) "
                         "and where they came from.")
def get_parameters(site: Site = "default") -> SiteParameters:
    return _params(site)


@server.tool(description="Forget what a site has learned and return its factors to 1.")
def reset_parameters(site: Site = "default") -> SiteParameters:
    store.reset(site)
    return _params(site)


class LearningResult(BaseModel):
    site: str
    area: str
    data: str
    prior: dict[str, float]
    posterior: dict[str, float]
    diagnostics: dict[str, float | int | None]
    persisted: bool
    provenance: Provenance


@server.tool(description=(
    "Learn a site's cattle and sheep factors from the NAEI 2020 1 km agricultural methane map "
    "over an area (Bayesian update from the site's current factors). Use it to correct DT2 "
    "where the dairy share or stocking differs from England's average."))
def assimilate_naei(area: AreaIn, site: Site,
                    rel_sd: Annotated[float, Field(gt=0, le=2)] = 0.3,
                    other_fraction: Annotated[float, Field(ge=0, lt=1)] = 0.05,
                    persist: bool = True) -> LearningResult:
    a, mk = _mask(area)
    prior = store.get(site)
    grid = m.emissions_grid(CFG, mk, {})
    try:
        post, diag = m_assim.from_cells(prior, grid, mk, m_maps.layers()["naei_ch4_t"],
                                        rel_sd=rel_sd, other_fraction=other_fraction)
    except ValueError as e:
        raise ToolError(str(e)) from e
    if persist:
        store.set({k: post[k] for k in ("cattle", "sheep", "cattle_sd", "sheep_sd")}, site,
                  note=f"NAEI 2020 cells, {a.describe()}")
    return LearningResult(site=site, area=a.describe(), data=m_maps.NAEI_SOURCE,
                          prior=prior, posterior=post, diagnostics=diag, persisted=persist,
                          provenance=_prov(site))


@server.tool(description=(
    "Learn a site's cattle and sheep factors from one observed methane total for an area "
    "(t CH4/yr with its standard deviation), e.g. from an aircraft or satellite inversion."))
def assimilate_total(area: AreaIn, site: Site,
                     observed_t_ch4: Annotated[float, Field(gt=0)],
                     sd_t_ch4: Annotated[float, Field(gt=0)],
                     other_fraction: Annotated[float, Field(ge=0, lt=1)] = 0.0,
                     persist: bool = True) -> LearningResult:
    a, mk = _mask(area)
    prior = store.get(site)
    grid = m.emissions_grid(CFG, mk, {})
    post, diag = m_assim.from_total(prior, grid, observed_t_ch4, sd_t_ch4, other_fraction)
    if persist:
        store.set({k: post[k] for k in ("cattle", "sheep", "cattle_sd", "sheep_sd")}, site,
                  note=f"observed total {observed_t_ch4:g} +/- {sd_t_ch4:g} t CH4, "
                       f"{a.describe()}")
    return LearningResult(site=site, area=a.describe(), data="observed area total",
                          prior=prior, posterior=post, diagnostics=diag, persisted=persist,
                          provenance=_prov(site))


if __name__ == "__main__":
    if "--http" in sys.argv:
        server.run("streamable-http", host=os.environ.get("DT2_HOST", "127.0.0.1"),
                   port=int(os.environ.get("DT2_PORT", "8000")))
    else:
        server.run("stdio")
