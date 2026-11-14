# DT4 agent: forest above-ground biomass and carbon

DT4 serves the forest biomass twin to an orchestrator over MCP. It keeps an estimate of
above-ground biomass (AGB) and carbon for British woodland, observed with **ESA Biomass CCI v7**,
and projects it with two growth models side by side, **Chapman-Richards yield curves** and the
**3-PG** process model, under management and disturbance scenarios.

Pilot landscapes: **Thetford** (lowland Corsican pine on Breckland sands) and **Kielder**
(upland Sitka spruce on peaty gleys).

## Decisions this build follows

- **Biomass CCI v7 only.** Both growth models are calibrated against ESA Biomass CCI v7.0
  (100 m AGB and per-pixel SD, 18 annual maps: 2005–2012 and 2015–2024). No GEDI, ICESat-2,
  lidar, Sentinel-2 or NFI plots are used. The woodland mask is derived from CCI too.
- **Two growth models for comparison.** Every scenario tool can run the yield curves, 3-PG,
  or both, and `validate` scores both on years they have not seen.
- **Pilot landscapes Thetford and Kielder** (the suggestion in the concept; no other areas were
  named).

## Layout

| Path | What it is |
|---|---|
| `dt4_server.py` | MCP server named `dt4` (16 tools) |
| `forest/` | the model package, server-safe (no plotting, no prints, no global state) |
| `forest/cci.py` | CCI v7 cubes, woodland mask, area statistics with honest uncertainty, change |
| `forest/landscapes.py` | pilot windows, dominant species, soils, monthly climate |
| `forest/species.py` | Sitka spruce, Corsican pine, Scots pine, oak: yield-curve shape, wood density, BEF, 3-PG parameters |
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
| `forest/data/` | CCI v7 cubes for both pilots (2.8 MB) and the shipped calibration |
| `scripts/extract_cci_pilots.py` | re-extracts the CCI cubes from CEDA (the only networked step) |
| `scripts/calibrate_pilots.py` | regenerates `forest/data/calibration_cci_v7.json` (about 15 s) |
| `dt4_agent.ipynb` | acts as the orchestrator: launches the server and calls every tool (executed) |
| `test_*.py`, `claude_orchestrator_check.py` | tests, see below |

## How the twin works

**Observe.** `forest/cci.py` reads each landscape's cube. Area means come with an SD that
treats CCI errors as spatially correlated (effective sample size n/25, plus a 30 % systematic
share), because averaging 30,000 pixels does not really shrink a SAR biomass error to nothing.
Changes are called significant only when they exceed 1.645 × the combined SD, and changes
across the 2012/2015 gap are flagged because the sensors change there (ALOS/Envisat →
ALOS-2/Sentinel-1).

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
therefore pixel by pixel: every sampled woodland pixel gets the productivity and age that best
fit its own CCI trajectory, weighted by the CCI SD. Pixels with a clearfell or windthrow
detected in CCI are fitted from the year of the loss, as a restocked stand.

**Assimilate.** `assimilate_agb` runs an ensemble Kalman filter with AGB and productivity in
the state, so the site's productivity is learned from data (CCI for an area, or values you
pass). Learned values are stored per site, exactly like DT8's learned CH4 parameters.

**Manage, disturb, account.** The scenario engine applies the regime and disturbances each
year and tracks living, dead and product carbon. Net flux is the atmosphere's view (stock
change plus the carbon handed to soil), forest plus wood products, positive = emission.

## Calibration and model comparison (shipped results)

From `forest/data/calibration_cci_v7.json`: 2,000 woodland pixels per landscape; validation
fitted on 2005–2017 and scored on 2018–2024 (pixels felled in those years excluded).

| Landscape | Model | Productivity (median, IQR) | Stand age 2024 | Hold-out RMSE | Hold-out bias | Hold-out R² |
|---|---|---|---|---|---|---|
| Thetford | yield curve | YC 4 (3–8) | 58 | 38.4 Mg/ha | +13.7 | 0.54 |
| Thetford | 3-PG | FR 0.10 (0.05–0.35) | 62 | 38.0 Mg/ha | +14.6 | 0.55 |
| Kielder | yield curve | YC 6 (3–9) | 50 | 42.6 Mg/ha | +0.9 | 0.27 |
| Kielder | 3-PG | FR 0.20 (0.05–0.35) | 53 | 43.7 Mg/ha | +1.8 | 0.24 |

What this says:

- The two models predict unseen CCI years about equally well: 3-PG is marginally better at
  Thetford, the yield curves marginally better at Kielder. The difference is far smaller than the
  CCI pixel error (about 40–60 Mg/ha).
- **CCI-calibrated productivity is low** compared with Forest Research yield classes (typically
  YC 10–14 for Corsican pine at Thetford and YC 12–16 for Sitka at Kielder). The likely causes are
  C- and L-band saturation in dense stands, thinning in the real forest (the fitted stand is an
  unthinned one), and flat, noisy pixel trajectories. Absolute growth and carbon removals from
  scenarios are therefore probably conservative. This is the main reason to bring in another
  constraint later (NFI or lidar), if you decide to.
- Thetford's positive hold-out bias means both models expect more growth after 2017 than CCI
  shows; the CCI mean there declines slightly from 2015 to 2024.

## Tools

| Tool | EBCF role | What it returns |
|---|---|---|
| `list_species` | | species parameters, regimes, disturbance types, growth models |
| `list_landscapes` | | pilot landscapes, woodland area, climate, calibration of both models |
| `get_agb` | state | CCI v7 AGB of a landscape, box or point (+ radius) in one year, with 90 % range |
| `agb_timeseries` | state | the 18-year series and the 2015–2024 trend |
| `carbon_stock` | state | living carbon (above + below ground), per ha and in total, t C and t CO2e |
| `biomass_change` | impact | change between two years, significance, impact term, loss/gain/conversion areas |
| `attribute_change` | pressure | loss split among pressures where supplied evidence overlaps it; the rest unattributed |
| `simulate_stand` | response | one stand with yield curves, 3-PG or both: AGB, carbon pools, products, net CO2 |
| `management_scenario` | response | regimes compared for the landscape's typical stand from its 2024 CCI AGB |
| `afforestation_scenario` | response | carbon from new planting, per ha and for an area (for DT10) |
| `calibrate_site` | | pixel calibration of either or both models for a landscape or area |
| `validate` | | hold-out skill of both models |
| `assimilate_agb` | state | Kalman filter on CCI or supplied AGB; learns and stores the site's productivity |
| `get_parameters`, `reset_parameters` | | a site's productivity and where it came from |
| `self_learn_synthetic` | | recovery of a known productivity from a wrong prior |

Areas are `{"bbox": [W, S, E, N]}` or `{"point": [lon, lat], "radius_m": r}` in degrees
(EPSG:4326). All tools take and return typed JSON with input validation and output schemas, and
every result carries provenance (model version, CCI citation and licence, parameter source,
assumptions). Positive fluxes are emissions; a growing forest has a negative net flux.

## Run

```bash
pip install -r dt4_agent/requirements.txt
python dt4_agent/dt4_server.py          # stdio (for orchestrators that launch it)
python dt4_agent/dt4_server.py --http   # streamable HTTP on http://127.0.0.1:8000/mcp
DT4_PORT=8765 python dt4_agent/dt4_server.py --http
DT4_STATE_FILE=~/.dt4/state.json python dt4_agent/dt4_server.py   # keep learned parameters
```

Register with Claude Code: `claude mcp add dt4 -- python /path/to/dt4_agent/dt4_server.py`

Rebuild the data (needs network access to dap.ceda.ac.uk and `pip install rasterio`):

```bash
python dt4_agent/scripts/extract_cci_pilots.py
python dt4_agent/scripts/calibrate_pilots.py
```

## Test

```bash
pip install pytest
pytest dt4_agent        # 60 tests, about 35 s
```

- `test_forest_models.py`: yield class equals peak MAI for every species; 3-PG responds to
  fertility and drought and obeys self-thinning; clearfell logs reach the product pools; net flux
  equals stock change plus soil input; disturbances replace stands; pinned CCI v7 numbers for both
  landscapes; change significance and the evidence rule for attribution; calibration recovers
  known pixels; **rerunning `calibrate_pilots.py` reproduces the shipped calibration exactly**;
  the Kalman filter learns a known productivity for both models; the package imports no plotting
  library, prints nothing and writes no files.
- `test_dt4_server.py`: every tool in memory, bad inputs come back as tool errors, learning is per
  site, and over stdio a learned value survives a restart with `DT4_STATE_FILE`.
- `test_dt4_end_to_end.py`: the agentic path. An orchestrator query with input parameters
  (Kielder's 2024 AGB, then three regimes over 40 years with both models, 20 members, seed 7)
  goes to `get_agb` and `management_scenario` in memory, over stdio, over streamable HTTP, and
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

- **Climate for 3-PG** is a monthly 1991–2020-style climatology typed in from nearby Met Office
  stations (rounded), not HadUK-Grid or UKCP18. It is used as a driver, not for calibration.
- **One species per landscape** (Corsican pine at Thetford, Sitka spruce at Kielder). Other
  species can be simulated with a priori productivity, and results say so.
- **Woodland mask** from CCI (median AGB 2015–2024 ≥ 20 Mg/ha or peak ≥ 60 Mg/ha), not the NFI
  map, following the CCI-only decision.
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
- **Data licence**: ESA CCI Biomass terms and conditions v2 (free and open, citation required).
  Cite: Santoro, M.; Cartus, O. (2026): ESA Biomass Climate Change Initiative (Biomass_cci):
  Global datasets of forest above-ground biomass for the years 2005-2012 and 2015-2024, v7.0.
  NERC EDS Centre for Environmental Data Analysis.
  [Catalogue record](https://catalogue.ceda.ac.uk/uuid/6429d1aafe1e43b9b414e4a5a7f8b903).
