# DT4 agent: forest above-ground biomass and carbon

DT4 serves the forest biomass twin to an orchestrator over MCP. It keeps an estimate of
above-ground biomass (AGB) and carbon for British woodland, observed with **ESA Biomass CCI v7**,
and projects it with two growth models side by side, **Chapman-Richards yield curves** and the
**3-PG** process model, under management and disturbance scenarios.

Pilot landscapes: **Thetford** (lowland Corsican pine on Breckland sands) and **Kielder**
(upland Sitka spruce on peaty gleys). Woodland, species and stand ages come from the
**National Forest Inventory** woodland map and the **Forestry England sub-compartment
database**; every species group recorded there is modelled and calibrated on its own. Climate
for 3-PG is **HadUK-Grid** 1991–2020.

## Decisions this build follows

- **Biomass CCI v7 only.** Both growth models are calibrated against ESA Biomass CCI v7.0
  (100 m AGB and per-pixel SD, 18 annual maps: 2005–2012 and 2015–2024). No GEDI, ICESat-2,
  lidar or Sentinel-2 data are used. The inventory supplies *where* the woodland is, *which*
  species grows there and *how old* the stands are; productivity is fitted to CCI alone.
  Forestry England's own yield class is kept only as an independent check.
- **HadUK-Grid instead of station data** for the 3-PG climate.
- **National Forest Inventory and species.** The Forest Research NFI products that are open
  are the woodland map (no species) and, for the public forest estate, the Forestry England
  sub-compartment database (species, planting year, yield class). The NFI field-plot species
  data are not public, so species come from the sub-compartments (details below).
- **Two growth models for comparison.** Every scenario tool can run the yield curves, 3-PG,
  or both, and `validate` scores both on years they have not seen.
- **Pilot landscapes Thetford and Kielder** (the suggestion in the concept; no other areas were
  named).

## Layout

| Path | What it is |
|---|---|
| `dt4_server.py` | MCP server named `dt4` (17 tools) |
| `forest/` | the model package, server-safe (no plotting, no prints, no global state) |
| `forest/cci.py` | CCI v7 cubes, NFI woodland mask, saturation level, area statistics with honest uncertainty, change |
| `forest/inventory.py` | NFI woodland and Forestry England sub-compartments on the CCI grid: species group, stand age, FE yield class |
| `forest/landscapes.py` | pilot windows, dominant species, soils, HadUK-Grid monthly climate |
| `forest/species.py` | 11 species groups: yield-curve shape, wood density, BEF, 3-PG parameters |
| `forest/yield_curves.py` | empirical growth: yield class = peak mean annual increment |
| `forest/threepg.py` | process growth: 3-PG on a monthly step (Landsberg & Waring 1997; Sands & Landsberg 2002) |
| `forest/management.py` | regimes: no intervention, thin and fell, clearfell, continuous cover |
| `forest/disturbance.py` | wind, fire, biotic, drought; prescribed or stochastic |
| `forest/carbon.py` | roots, deadwood, litter, harvested wood products; carbon to soil for DT7 |
| `forest/scenario.py` | the yearly engine: growth → management → disturbance → carbon |
| `forest/calibration.py` | pixel-by-pixel calibration of either model to CCI v7, with hold-out validation |
| `forest/assimilation.py` | ensemble Kalman filter that learns a site's productivity |
| `forest/change.py` | change significance and Living Earth EBCF impact (pressure) attribution |
| `forest/state.py` | calibrated and learned productivity per site (`DT4_STATE_FILE` to persist) |
| `forest/data/` | CCI v7 cubes (2.8 MB), inventory rasters (0.1 MB), HadUK-Grid climate and the shipped calibration |
| `scripts/extract_cci_pilots.py` | re-extracts the CCI cubes from CEDA |
| `scripts/extract_inventory.py` | rasterises the NFI woodland map and FE sub-compartments onto the CCI grid |
| `scripts/extract_haduk_climate.py` | HadUK-Grid 1991–2020 monthly climate from the Met Office Climate Data Portal |
| `scripts/calibrate_pilots.py` | regenerates `forest/data/calibration_cci_v7.json` (about 1.5 min) |
| `dt4_agent.ipynb` | acts as the orchestrator: launches the server and calls every tool (executed) |
| `test_*.py`, `claude_orchestrator_check.py` | tests, see below |

## How the twin works

**Observe.** `forest/cci.py` reads each landscape's cube. Area means come with an SD that
treats CCI errors as spatially correlated (effective sample size n/25, plus a 30 % systematic
share), because averaging 30,000 pixels does not really shrink a SAR biomass error to nothing.
Changes are called significant only when they exceed 1.645 × the combined SD, and changes
across the 2012/2015 gap are flagged because the sensors change there (ALOS/Envisat →
ALOS-2/Sentinel-1).

**Know the forest.** `forest/inventory.py` puts two Forestry Commission datasets on the CCI
100 m grid (a pixel takes the polygon that contains its centre):

- the *NFI woodland map GB 2024* gives the woodland mask (category "Woodland", which keeps
  felled and young stands) and the interpreted forest type;
- the *Forestry England sub-compartment database* gives, on the public forest estate, each
  stand's main species, planting year and FE yield class.

Species names are grouped into 11 DT4 species groups: Sitka spruce (SS), Norway and other
spruces (NS), Corsican pine (CP), Scots pine (SP), lodgepole pine (LP), Douglas fir and other
conifers (DF), larches (LA), oak (OK), beech (BE), birch (BI) and mixed broadleaves (MB:
sycamore, ash, alder, poplar, chestnut and the rest). Woodland pixels outside the estate, or
with no species recorded, take a group from the NFI forest type: conifer, felled and young
types the landscape's dominant conifer, broadleaved types MB.

| Landscape | NFI woodland | In the FE estate | With species and planting year | Composition (area share) |
|---|---|---|---|---|
| Thetford | 13,670 ha | 75 % | 68 % | CP 56 %, MB 15 %, SP 15 %, DF 5 %, BE 4 %, LA 2 %, BI 2 %, OK 1 % |
| Kielder | 26,521 ha | 88 % | 65 % | SS 84 %, NS 6 %, MB 4 %, BI 2 %, LP 1 %, SP 1 %, DF 1 % |

**Climate.** 3-PG runs on the HadUK-Grid 1991–2020 monthly averages of each landscape window,
from the Met Office Climate Data Portal: mean temperature, rainfall and air-frost days on the
portal's ~2 km grid, and maximum and minimum temperature from the 12 km grid shifted to the
~2 km mean. HadUK-Grid has no radiation, so global radiation comes from the diurnal temperature
range (Hargreaves–Samani, kRs 0.16). Thetford: 648 mm, 10.2 °C, 62 air-frost days; Kielder:
1,389 mm, 7.3 °C, 89 air-frost days.

**Grow.** Both growth models share one interface, so the scenario engine, calibration and
Kalman filter treat them alike.

- *Yield curves*: V(t) = A (1 − e^(−kt))^p, with A and k set so the peak mean annual increment
  equals the yield class at a species-typical age (50 years for Sitka spruce). AGB = V × wood
  density × BEF. Thinned stands keep increment in proportion to √(relative stocking).
- *3-PG*: monthly light interception, quantum efficiency reduced by temperature, frost, VPD,
  soil water, nutrition and age; NPP partitioned to roots, foliage and stems; litterfall, root
  turnover and −3/2 self-thinning; a soil water bucket with Penman–Monteith transpiration. The
  fertility rating (0–1) is the parameter calibrated to CCI.

**Calibrate.** Each landscape is a mosaic of stand ages, so its mean AGB says little about
growth (Thetford's barely moves in 20 years because felling balances growth). Calibration is
therefore pixel by pixel and species by species: for every species group with at least 300
woodland pixels, a sample of up to 2,000 pixels each gets the productivity that best fits its
own CCI trajectory, weighted by the CCI SD. Where Forestry England records a planting year the
stand age is fixed (±2 years) and only productivity is fitted; elsewhere age is fitted too.
Pixels with a clearfell or windthrow detected in CCI are fitted from the year of the loss, as a
restocked stand.

*CCI saturates.* Plotting CCI against the recorded stand age shows it plainly: AGB climbs to
about 150 Mg/ha by age 30 and then stays flat for stands of any age, in both forests and for
every conifer. CCI also reads 10–20-year-old stands high (about 100 Mg/ha).

| Stand age (years) | 10–19 | 20–29 | 30–39 | 40–49 | 50–59 | 60–69 |
|---|---|---|---|---|---|---|
| Thetford Corsican pine, median CCI 2020 (Mg/ha) | 108 | 138 | 154 | 155 | 160 | 149 |
| Kielder Sitka spruce, median CCI 2020 (Mg/ha) | 102 | 147 | 166 | 147 | 140 | 138 |

So the fit compares CCI with what CCI can see, min(model AGB, 150 Mg/ha), while the model
itself keeps growing. Without this, stands of known age either take implausibly low
productivity to match the plateau or overshoot in later years.

**Assimilate.** `assimilate_agb` runs an ensemble Kalman filter with AGB and productivity in
the state, so the site's productivity is learned from data (CCI for an area, or values you
pass). Learned values are stored per site, exactly like DT8's learned CH4 parameters.

**Manage, disturb, account.** The scenario engine applies the regime and disturbances each
year and tracks living, dead and product carbon. Net flux is the atmosphere's view (stock
change plus the carbon handed to soil), forest plus wood products, positive = emission.

## Calibration and model comparison (shipped results)

From `forest/data/calibration_cci_v7.json`. Validation is fitted on 2005–2017 and scored on
2018–2024 (pixels felled or restocked in those years excluded). Hold-out RMSE is given for
yield curve / 3-PG, with inventory ages and, for comparison, with ages fitted from CCI alone
(the previous version of DT4). FE YC is Forestry England's yield class of the same pixels, and
r its pixel-by-pixel correlation with the CCI-calibrated yield class; neither is used in the
fit.

| Landscape | Species | Area | Age 2024 | CCI yield class (IQR) | FE YC | r | 3-PG FR | Hold-out RMSE, inventory ages | Hold-out RMSE, CCI ages |
|---|---|---|---|---|---|---|---|---|---|
| Thetford | CP | 56 % | 38 | YC 14 (7–22) | 14 | 0.08 | 0.55 | 37.2 / 35.7 | 34.2 / 33.5 |
| Thetford | MB | 15 % | 44 | YC 2 (2–4) | 4 | 0.01 | 0.35 | 30.2 / 28.8 | 27.9 / 26.5 |
| Thetford | SP | 15 % | 43 | YC 8 (3–15) | 10 | 0.01 | 0.50 | 45.9 / 43.3 | 38.9 / 37.4 |
| Thetford | DF | 5 % | 23 | YC 14 (4–17) | 12 | −0.14 | 0.50 | 41.5 / 41.2 | 38.5 / 38.7 |
| Thetford | BE | 4 % | 78 | YC 3 (2–6) | 6 | −0.13 | 0.35 | 47.7 / 51.4 | 37.6 / 38.2 |
| Thetford | LA | 2 % | 18 | YC 9 (6–17) | 10 | 0.35 | 0.50 | 63.8 / 52.6 | 56.0 / 56.8 |
| Thetford | BI | 2 % | 21 | YC 6 (3–9) | 4 | 0.04 | 0.50 | 35.6 / 36.5 | 33.9 / 35.2 |
| Thetford | OK | 1 % | 82 | YC 2 (2–4) | 4 | −0.03 | 0.35 | 42.9 / 46.5 | 29.9 / 31.1 |
| Kielder | SS | 84 % | 28 | YC 8 (2–17) | 12 | 0.38 | 0.20 | 32.5 / 31.2 | 33.1 / 33.5 |
| Kielder | NS | 6 % | 25 | YC 4 (2–13) | 10 | 0.35 | 0.10 | 30.1 / 29.2 | 34.9 / 35.7 |
| Kielder | MB | 4 % | 19 | YC 2 (2–3) | 2 | 0.05 | 0.15 | 23.4 / 18.8 | 18.0 / 18.0 |
| Kielder | BI | 2 % | 12 | YC 3 (2–4) | 4 | −0.08 | 0.40 | 34.9 / 20.8 | 47.5 / 45.0 |
| Kielder | LP | 1 % | 59 | YC 3 (2–6) | 6 | 0.41 | 0.10 | 37.5 / 30.5 | 31.4 / 32.6 |
| Kielder | SP | 1 % | 64 | YC 3 (2–8) | 10 | 0.25 | 0.10 | 42.2 / 37.8 | 35.0 / 34.5 |
| Kielder | DF | 1 % | 46 | YC 3 (2–14) | 8 | 0.13 | 0.05 | 31.7 / 30.6 | 50.9 / 53.6 |

RMSE in Mg/ha. What this says:

- **Known ages fix the productivity of the main species.** With ages from the sub-compartment
  database and the saturation cap, CCI alone gives Corsican pine at Thetford a median YC 14,
  exactly Forestry England's median, and Sitka spruce at Kielder YC 8 against FE's 12. Fitting
  age from CCI made Thetford's pine stands about 50–90 years old (they are 38) and pushed yield
  classes down to 3–4.
- At Kielder the CCI yield class also tracks FE's from stand to stand (r ≈ 0.35–0.41 for the
  conifers); at Thetford it does not (r ≈ 0), likely because thinning, which an unthinned stand
  model cannot see, dominates the pixel trajectories there.
- **Hold-out skill is mixed.** Inventory ages improve it for Kielder Sitka and Norway spruce,
  birch and Douglas fir (by up to 20 Mg/ha), and make it worse by 2–13 Mg/ha for most Thetford
  species and the old broadleaves: a flat CCI trajectory is easiest to match with an old stand
  on the flat part of its curve, whether or not the stand is old. The inventory ages are kept
  because they are observed, not inferred.
- **3-PG and the yield curves remain close**; 3-PG has the lower hold-out RMSE for 12 of the
  15 species–landscape pairs, by 1–2 Mg/ha for the main species and most clearly for Kielder
  birch and lodgepole pine.
- Above ~150 Mg/ha CCI carries no information, so the productivity of dense older stands rests
  on their younger years and the prior; the spread (IQR) of calibrated yield classes is wide
  and up to a third of pixels sit at the edge of the productivity grid for some species.

## Tools

| Tool | EBCF role | What it returns |
|---|---|---|
| `list_species` | | species parameters, regimes, disturbance types, growth models |
| `list_landscapes` | | pilot landscapes, NFI woodland area, species composition, climate, calibration of every species group |
| `forest_inventory` | state | species composition, stand ages and FE yield class of a landscape or area, with the CCI calibration per species |
| `get_agb` | state | CCI v7 AGB of a landscape, box or point (+ radius) in one year, with 90 % range; optionally one species group |
| `agb_timeseries` | state | the 18-year series and the 2015–2024 trend |
| `carbon_stock` | state | living carbon (above + below ground), per ha and in total, t C and t CO2e |
| `biomass_change` | impact | change between two years, significance, impact term, loss/gain/conversion areas |
| `attribute_change` | pressure | loss split among pressures where supplied evidence overlaps it; the rest unattributed |
| `simulate_stand` | response | one stand with yield curves, 3-PG or both: AGB, carbon pools, products, net CO2 |
| `management_scenario` | response | regimes compared for a species group's typical stand from its 2024 CCI AGB |
| `afforestation_scenario` | response | carbon from new planting, per ha and for an area (for DT10) |
| `calibrate_site` | | pixel calibration of either or both models for one species group in a landscape or area, with the FE yield-class check |
| `validate` | | hold-out skill of both models for every species group, inventory ages against CCI-fitted ages |
| `assimilate_agb` | state | Kalman filter on CCI or supplied AGB; learns and stores the site's productivity per species |
| `get_parameters`, `reset_parameters` | | a site's productivity per species and where it came from |
| `self_learn_synthetic` | | recovery of a known productivity from a wrong prior |

Species are the group codes above; tools that model a stand default to the landscape's
dominant species (CP at Thetford, SS at Kielder). Areas are `{"bbox": [W, S, E, N]}` or `{"point": [lon, lat], "radius_m": r}` in degrees
(EPSG:4326). All tools take and return typed JSON with input validation and output schemas, and
every result carries provenance (model version, CCI and inventory citations and licences,
parameter source, assumptions). Positive fluxes are emissions; a growing forest has a negative net flux.

## Run

```bash
pip install -r dt4_agent/requirements.txt
python dt4_agent/dt4_server.py          # stdio (for orchestrators that launch it)
python dt4_agent/dt4_server.py --http   # streamable HTTP on http://127.0.0.1:8000/mcp
DT4_PORT=8765 python dt4_agent/dt4_server.py --http
DT4_STATE_FILE=~/.dt4/state.json python dt4_agent/dt4_server.py   # keep learned parameters
```

Register with Claude Code: `claude mcp add dt4 -- python /path/to/dt4_agent/dt4_server.py`

Rebuild the data (needs network access to dap.ceda.ac.uk, services.arcgis.com and
services2.arcgis.com, and `pip install rasterio`):

```bash
python dt4_agent/scripts/extract_cci_pilots.py
python dt4_agent/scripts/extract_inventory.py
python dt4_agent/scripts/extract_haduk_climate.py
python dt4_agent/scripts/calibrate_pilots.py
```

## Test

```bash
pip install pytest
pytest dt4_agent        # 72 tests, about 2 min (most of it the calibration rerun)
```

- `test_forest_models.py`: yield class equals peak MAI for every species; 3-PG responds to
  fertility and drought and obeys self-thinning; clearfell logs reach the product pools; net flux
  equals stock change plus soil input; disturbances replace stands; pinned CCI v7 numbers for both
  landscapes on the NFI mask; the inventory species mapping, composition and ages; the HadUK-Grid
  climate; change significance and the evidence rule for attribution; calibration recovers
  known pixels, holds recorded ages, and recovers yield class from saturated data; **rerunning `calibrate_pilots.py` reproduces the shipped calibration exactly**;
  the Kalman filter learns a known productivity for both models; the package imports no plotting
  library, prints nothing and writes no files.
- `test_dt4_server.py`: every tool in memory, bad inputs come back as tool errors, learning is per
  site, and over stdio a learned value survives a restart with `DT4_STATE_FILE`.
- `test_dt4_end_to_end.py`: the agentic path. An orchestrator query with input parameters
  (Kielder's 2024 AGB, then three regimes over 40 years with both models, 20 members, seed 7)
  goes to `get_agb` and `management_scenario` (Sitka spruce) in memory, over stdio, over streamable HTTP, and
  as raw JSON-RPC 2.0 over stdio and HTTP without the MCP client library. Every answer must equal
  the `forest` package run directly with the same inputs.

`claude_orchestrator_check.py` puts a headless Claude Code agent in the orchestrator's seat with
only the DT4 server and a plain-language question (Kielder's AGB, the best regime by each model,
and which model validated better). It checks every result the agent received against DT4 run
in-process and that the answer quotes the AGB and names the best regimes.
`claude_orchestrator_run.json` is a recorded run. It needs the signed-in `claude` CLI, so it is
not part of the pytest suite:

```bash
python dt4_agent/claude_orchestrator_check.py --out run.json
```

## Assumptions and limitations

- **Climate for 3-PG** is the HadUK-Grid 1991–2020 average from the Met Office Climate Data
  Portal (~2 km for temperature, rain and frost; 12 km for Tmax and Tmin), not the 1 km monthly
  series on CEDA, which needs a CEDA login. Radiation is estimated from the temperature range
  (Hargreaves–Samani), which tends to overestimate UK radiation by roughly 10–15 %; 3-PG
  productivity absorbs this in calibration. Climate is a driver only, never calibrated against.
- **Species where Forestry England records none** (32 % of Thetford's and 35 % of Kielder's
  woodland: private woods, open ground, felled areas) are inferred
  from the NFI forest type, so "CP" there means "conifer at Thetford". Mixed stands are
  represented by their main species. NFI field-plot species data are not public.
- **Stand ages** come from the FE planting year of the current stand. Where CCI shows a
  stand-replacing loss the CCI date wins, because the record may predate the felling.
- **Saturation level** (150 Mg/ha) is read off the CCI-against-age plateau of the pilot
  conifers; it is one number for both forests and all species.
- **Each pixel is fitted as an unthinned even-aged stand.** Thinning in the real forest is the
  likely reason the stand-to-stand agreement with FE yield class is weak at Thetford.
- **Assimilation** (`assimilate_agb`) compares the filter with observations directly, without
  the saturation cap; use it with observations below ~150 Mg/ha, or for young stands.
- **Yield curves** reproduce the defining property of yield class but are not the Forest Research
  yield tables, which are not openly licensed as code.
- **Continuous cover** harvests rejuvenate the stand's effective age (regeneration in gaps). This
  makes continuous cover look strong in the yield-curve model and is the main reason the two
  models rank regimes differently; treat that ranking as a hypothesis to test.
- **Roots** use the Mokany et al. (2006) relation for both models; deadwood, litter, product
  shares and half-lives, disturbance rates and salvage shares are a priori values from IPCC
  defaults and British practice.
- **Soil carbon** belongs to DT7. DT4 reports the litter and deadwood carbon passed to soil each
  year (`litter_and_deadwood_to_soil_t_c_ha_yr`) as DT7's input.
- **Inventory licence**: NFI Woodland GB 2024 and Forestry England Subcompartments, Forestry
  Commission open data, Open Government Licence v3.0. **Climate licence**: HadUK-Grid via the
  Met Office Climate Data Portal, Open Government Licence v3.0.
- **Data licence**: ESA CCI Biomass terms and conditions v2 (free and open, citation required).
  Cite: Santoro, M.; Cartus, O. (2026): ESA Biomass Climate Change Initiative (Biomass_cci):
  Global datasets of forest above-ground biomass for the years 2005-2012 and 2015-2024, v7.0.
  NERC EDS Centre for Environmental Data Analysis.
  [Catalogue record](https://catalogue.ceda.ac.uk/uuid/6429d1aafe1e43b9b414e4a5a7f8b903).
