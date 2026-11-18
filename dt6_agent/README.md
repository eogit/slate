# DT6 agent: trees outside woodland, biomass and carbon

DT6 serves the twin of **trees outside woodland** (TOW) to an orchestrator over MCP: every lone
tree, group of trees and small woodland outside the National Forest Inventory woodland map.
It keeps an estimate of their biomass and carbon, measures how their canopies change, and
projects them under baseline, ash-dieback and planting scenarios with two growth models side
by side.

- **Inventory**: the **National Trees Outside Woodland map V1** (Forest Research / Forestry
  Commission for the Natural Capital and Ecosystem Assessment, 2025, OGL v3).
- **Calibration data**: **Environment Agency lidar** canopy heights only, at every epoch
  flown over each pilot: the National LIDAR Programme (NLP, 2016–2023, first and last return)
  and the older LIDAR Tiles surveys (last return, 1998 onwards).
- **Growth models**: an empirical **size-age curve** indexed by site index, and a
  process-based **crown light-use model** driven by **HadUK-Grid** 1991–2020 climate.
- **Pilots**: ten 5 km × 5 km Ordnance Survey tiles spread across England (below).

## Decisions this build follows

These come from the concept proposal ("Trees outside forests twin: concept proposal") and
the decisions on it:

- **Calibrated against EA lidar canopy height only.** The TOW map is the inventory (which
  trees exist and how big their crowns are); productivity and tree age are fitted to lidar
  heights alone. No satellite biomass product is used.
- **Boundaries between twins.** DT6 owns every TOW object with canopy above 3 m. DT5
  (hedgerows) owns hedges below that. DT4 owns NFI woodland, including the "NFI overhanging
  canopy" class of the TOW map, which DT6 therefore drops. DT6 hands the carbon its trees shed
  to the soil twin (DT7).
- **Both growth models now**: the crown light-use model is built alongside the size-age
  curves, and every projection tool can run either or both.
- **Ten pilot areas** rather than two, spread across landscapes and favouring tiles with
  repeat lidar.

## Pilot tiles

| Pilot | Tile | Region | Landscape | Lidar epochs | TOW objects | Trees | Canopy (ha) | AGB (t) |
|---|---|---|---|---|---|---|---|---|
| `breckland` Breckland farmland | TL7580 | Eastern | Dry arable Brecks beside Thetford Forest: Scots pine rows, shelterbelts, field trees | 1998, 2009, 2018 | 2,186 | 3,727 | 28 | 1,468 |
| `fens` Cambridgeshire Fens | TL4075 | Eastern | Open fen arable along the Great Ouse washes: willows, poplars, farmstead trees | 1999, 2017, 2019, 2021 | 856 | 2,379 | 13 | 560 |
| `mid_devon` Exe valley, mid-Devon | SX9095 | South West | Pastoral Devon with hedgebanks, field oaks and riparian trees | 2005, 2016, 2020 | 6,048 | 20,735 | 161 | 10,655 |
| `somerset_levels` Somerset Levels | ST3535 | South West | Grazing marsh and rhynes: pollard willows and lines of trees | 2003, 2015, 2021 | 6,462 | 16,066 | 102 | 4,600 |
| `herefordshire` Wye valley, Herefordshire | SO5040 | West Midlands | Mixed farming in the Welsh Marches: orchards, field and hedgerow oaks | 2002, 2006, 2019 | 10,190 | 27,704 | 155 | 9,123 |
| `leicestershire` Soar valley, Leicestershire | SK6005 | East Midlands | Urban fringe of Leicester and Midlands clay farmland | 2001, 2014, 2018, 2022 | 10,561 | 28,024 | 155 | 7,866 |
| `vale_of_york` Vale of York | SE6045 | Yorkshire and Humber | Flat arable and Derwent floodplain: hedgerow trees and farm copses | 2000, 2010, 2020 | 5,766 | 19,424 | 133 | 8,101 |
| `cheshire` Cheshire plain near Chester | SJ4065 | North West | Dairy pasture with marl pits and many field oaks | 2001, 2015, 2021 | 18,376 | 41,967 | 193 | 9,043 |
| `oxford` Oxford and the Thames | SP5005 | South East | City, parks and colleges, and Thames floodplain meadows | 2005, 2016, 2020, 2023 | 16,933 | 36,042 | 230 | 15,572 |
| `tyne_valley` Tyne valley near Hexham | NY9065 | North East | Upland-fringe pasture: riparian alders, field ash and sycamore | 2005, 2016, 2019 | 5,737 | 18,485 | 121 | 9,274 |

Each tile is one OS 5 km tile, so every lidar product (which EA distributes by the same tiles)
covers it whole. The tiles were picked to span landscape types (arable, pastoral, wetland,
upland fringe, peri-urban, urban), one or more per English region outside London, and each
has at least one survey from before 2010 as well as the NLP. Breckland shares an edge with
DT4's Thetford window, to test the DT4/DT6 boundary. The Fens tile is only partly flown by the
NLP (905 of its 3,450 TOW objects), so DT6 models only that part.

Leaf type is not mapped for trees outside woodland. Each pilot carries an a priori conifer
share: 8 % by default (the lowland TOW population is overwhelmingly broadleaved), 35 % in
Breckland (Scots pine rows and shelterbelts) and 15 % in the Tyne valley.

## Layout

| Path | What it is |
|---|---|
| `dt6_server.py` | MCP server named `dt6` (13 tools) |
| `trees/` | the model package, server-safe (no plotting, no prints, no global state) |
| `trees/pilots.py` | the ten pilot tiles, their HadUK-Grid climate and conifer prior |
| `trees/inventory.py` | TOW objects with their lidar heights; trees per object, crown size, representative height |
| `trees/allometry.py` | Jucker et al. (2017) crown-height biomass, root:shoot, carbon |
| `trees/growth_curves.py` | empirical growth: size-age height curve indexed by site index |
| `trees/crown_lue.py` | process growth: single-tree crown light-use model on monthly climate |
| `trees/calibration.py` | crown-by-crown fit of either model to every lidar height, empirical-Bayes pilot prior, hold-out validation |
| `trees/carbon.py` | living, deadwood and firewood pools; litter carbon to soil for DT7 |
| `trees/scenario.py` | ensemble projections: baseline, ash dieback (with replanting), new planting |
| `trees/change.py` | significant canopy-height reductions and Living Earth EBCF impact (pressure) attribution |
| `trees/assimilation.py` | ensemble Kalman filter that learns productivity and age from new heights |
| `trees/state.py` | calibrated and learned productivity per site (`DT6_STATE_FILE` to persist) |
| `trees/data/` | per pilot: TOW objects with lidar heights (`<pilot>_crowns.npz`), crown calibration (`fit_<pilot>.npz`), HadUK-Grid climate; the calibration summary (`calibration_lidar.json`); 6 MB in all |
| `scripts/extract_pilots.py` | downloads the TOW map and every EA lidar epoch of a pilot and measures each object (and the HadUK-Grid climate) |
| `scripts/calibrate_pilots.py` | regenerates the calibration summary and crown fits (15–20 min) |
| `dt6_agent.ipynb` | acts as the orchestrator: launches the server and calls every tool (executed) |
| `test_*.py` | tests, see below |

## How the twin works

**Know the trees.** `scripts/extract_pilots.py` takes, for each tile, every TOW polygon of
the classes *Lone Tree* (5–350 m²), *Group of Trees* (up to 1,000 m²) and *Small Woodland*
(over 1,000 m²) from the TOW map's OGC API, and every lidar product EA holds for the tile from
its survey catalogue. On a common 1 m grid in British National Grid:

- the latest NLP terrain model (DTM) is the ground for **every** epoch, so heights from
  different years are measured from the same surface;
- first-return canopy height = NLP first-return DSM − DTM; last-return height = DSM − DTM for
  the NLP and for the old LIDAR Tiles DSMs (which are last-return only). Growth is therefore
  measured last return against last return;
- per object: the tallest return (excluding anything over 45 m), the share of the polygon
  covered, the flight date, and the number of tree tops (local maxima of the smoothed
  first-return canopy, 5 m apart, over 3 m) for groups and small woods.

`trees/inventory.py` turns this into trees: a lone tree is one tree; a group or small wood
has as many trees as tree tops, sharing the polygon's area equally. The representative tree
height is the tallest return for a lone tree and 0.85 × it for groups (not every tree is as
tall as the tallest). Crown ratio (crown diameter / height) is held constant as trees grow.

**Biomass.** AGB per tree from crown diameter and height with Jucker et al. (2017), Eq. 7
(angiosperm and gymnosperm forms, mixed by the conifer share), roots at 0.26 of AGB (Cairns
et al. 1997), carbon 50 % of dry matter. `carbon_stock` reports a 90 % range that combines
the tree-level allometric error (σ = 0.69 on the log scale, independent between trees), a
systematic allometry error (20 %, shared by all trees) and the unknown leaf type.

**Grow.** Both models predict the height of the representative tree at any age; biomass
follows from the allometry.

- *Size-age*: H(t) = 1.35 SI (1 − e^(−kt))^1.5 with k = 0.0342, so H(50) = SI. The
  productivity θ is the site index (4–30 m).
- *Crown light-use*: a tree gains above-ground woody biomass from the light its crown
  absorbs: dAGB/dt = η Y ε_max θ E A_crown(H) − m AGB, with E the year's climate-weighted
  absorbed PAR per m² of crown (monthly HadUK-Grid radiation, leaf-on season, 3-PG
  temperature, frost and soil-water modifiers), A_crown = π (cr H / 2)², ε_max = 6 g DM per
  MJ (the 3-PG maximum quantum efficiency), Y = 0.47, η = 0.35 and branch turnover m = 1.5 %
  a year. Gain grows with H² and turnover with AGB ∝ H⁴, so trees level off at a height that
  rises with √θ. θ (0.04–1) scales the light-use efficiency.

**Calibrate.** `trees/calibration.py` fits, for every object, θ and the tree's age at the
latest NLP flight on a grid, to all its heights: the first-return height (σ 1.0 m) and the
last-return height at every epoch (σ 1.5 m, modelled as ρ × H with ρ the pilot's median
last/first ratio on the same NLP night for that TOW class). Where an earlier epoch is more
than 3 m taller than a later one the tree was cut or lost crown; earlier heights are dropped
and the drop is recorded as an event. With one date, θ and age trade off (a short tree can be
young and vigorous or old and slow); repeat epochs separate them through growth. The prior on
θ is therefore the pilot's own: an **empirical-Bayes** prior learned, iteratively, from the
objects seen on two or more dates, which single-date objects then borrow.

**Validate.** The latest epoch is held out. Each object is refitted on its earlier epochs
alone (with the pilot prior learned from the *other* half of the objects, so no held-out
height informs its own forecast), and its last-return height at the latest flight is forecast
and compared with persistence (no growth since the previous epoch).

**Project.** `trees/scenario.py` starts every object from its measured height and grows it
along its own calibrated curve, H(Y) = h_obs + H(θ, a + Y − t) − H(θ, a), in an ensemble that
draws θ from each object's posterior, a crown-level allometric residual, a systematic
allometry factor and the conifer share. Background mortality is 0.5 % of trees a year. Dead
trees become firewood (70 % of the above-ground wood, burnt within about a year) or deadwood
(20-year half-life). Leaf, fine-root and branch litter go to the soil (DT7). Net flux =
−(change in living + deadwood + firewood carbon) − carbon passed to the soil; positive means
emission.

- *Ash dieback*: ash is an assumed share (default 15 %) of broadleaved trees, drawn per
  member; cumulative mortality m_max (1 − e^(−t/τ)), m_max 0.8 and τ 10 years by default;
  optionally a share of dead ash is replanted.
- *Planting*: a cohort of 1.3 m saplings grown on the pilot's calibrated curve, with
  establishment survival after 5 years of 0.85 (hedgerow), 0.90 (agroforestry), 0.85
  (riparian) or 0.75 (urban), then background mortality.

**Change and attribution.** `canopy_change` compares last-return heights between the epochs
nearest two years. A change counts only beyond 1.645 × √2 × 1.5 m = 3.5 m (90 %). Significant
reductions are *modifications* (still taller than 3 m: pruning, pollarding, crown loss) or
*removal candidates* (below 3 m). `attribute_change` names a pressure (felling, tree
management, ash dieback, disease, storm, development) only where supplied evidence overlaps a
reduction in space and time, following the Living Earth EBCF rule; the rest stays
unattributed.

**Learn.** `assimilate_heights` matches new height measurements (a new flight, drone or field
survey) to objects by id or nearest centroid, updates each object's θ and age with a
stochastic ensemble Kalman filter, and stores the mean θ shift for the site, which every
later projection of that site applies.

## Calibration and validation (shipped results)

Crown-by-crown calibration on all epochs (median over objects) and the hold-out forecast of the latest last-return height, against persistence. *Growth* is the observed median last-return height growth between the first and last epoch; *drops* the objects with a height drop over 3 m between epochs.

| Pilot | Growth (m/yr) | Drops | Size-age SI (m) | Crown LUE θ | Hold-out n | Years ahead | RMSE size-age / crown LUE / persistence (m) | Bias size-age / crown LUE (m) |
|---|---|---|---|---|---|---|---|---|
| breckland | 0.19 | 35 | 8.8 | 0.19 | 544 | 9.0 | 2.51 / 2.60 / 3.55 | +0.27 / +1.17 |
| fens | 0.37 | 143 | 5.7 | 0.12 | 705 | 1.4 | 2.58 / 2.99 / 2.58 | +0.06 / +1.47 |
| mid_devon | 0.07 | 2,644 | 6.6 | 0.09 | 2,787 | 14.3 | 2.85 / 2.99 / 3.01 | +0.25 / +1.22 |
| somerset_levels | 0.15 | 1,373 | 7.1 | 0.11 | 5,088 | 7.0 | 2.80 / 2.58 / 3.48 | -0.50 / +0.18 |
| herefordshire | 0.11 | 1,042 | 6.9 | 0.10 | 5,370 | 13.0 | 3.88 / 3.87 / 4.34 | +0.01 / +0.92 |
| leicestershire | 0.16 | 3,639 | 6.4 | 0.10 | 6,922 | 4.0 | 2.23 / 2.16 / 2.07 | +0.06 / +0.76 |
| vale_of_york | 0.17 | 282 | 10.1 | 0.19 | 3,728 | 20.9 | 4.22 / 4.15 / 5.75 | -0.36 / +0.93 |
| cheshire | 0.14 | 593 | 6.6 | 0.10 | 8,828 | 20.0 | 3.42 / 3.35 / 4.09 | +0.06 / +1.06 |
| oxford | 0.09 | 10,537 | 6.4 | 0.10 | 6,396 | 3.0 | 2.48 / 2.60 / 2.25 | +0.09 / +0.99 |
| tyne_valley | 0.54 | 503 | 10.3 | 0.32 | 1,977 | 2.3 | 4.13 / 3.92 / 4.66 | -0.33 / -0.19 |

What this shows:

- **Both models beat persistence in 7 of 10 pilots**, wherever the held-out epoch is 7 to 21 years after the previous one (RMSE down 5–30 %; skill 0.2–0.5 in Breckland, the Somerset Levels and the Vale of York). Where the gap is only 1–4 years (Fens, Leicestershire, Oxford, all NLP-to-NLP), growth is smaller than the 1.5 m lidar noise and persistence wins narrowly. Tyne valley wins with a 2.3-year gap because its trees grow fastest (0.54 m/yr).
- **The two models are close in skill.** The size-age curve has almost no bias; the crown LUE model over-forecasts growth by about 1 m over a decade in most pilots, because its curve shape keeps young-looking trees growing fast. Neither is clearly better, which is why both stay available.
- **Trees outside woodland grow slowly**: median last-return growth is 0.07–0.19 m/yr in the lowland pilots, so the calibrated site indices are low (6–10 m, against 15–25 m for woodland broadleaves). Many TOW trees are mature, managed hedgerow and field trees near their maximum height; the twin reads this as low productivity and old age (median 50–160 years for the size-age model).
- **Height drops are common**: from 282 objects in the Vale of York to over 10,000 in Oxford (city trees are pruned and lidar registration in built-up areas is harder). They are kept as events, not fitted, and not attributed without evidence.

Calibration uses no random sampling, so `scripts/calibrate_pilots.py` reproduces the shipped file exactly (tested for Breckland).

## Tools

| Tool | EBCF role | What it returns |
|---|---|---|
| `list_landscapes` | | the ten pilots: region, landscape, lidar epochs, TOW objects, canopy area, observed growth, climate, calibration and hold-out skill of both models |
| `tree_inventory` | state | objects, trees, canopy area and cover, median height and AGB by TOW class for a tile or area |
| `carbon_stock` | state | living carbon (above + below ground) with a 90 % range and its error budget, per ha of canopy and of land |
| `canopy_change` | impact | height change between two lidar epochs: growth, significant reductions (modification or removal), AGB lost |
| `attribute_change` | pressure | reductions split among pressures where supplied evidence overlaps them; the rest unattributed |
| `simulate_trees` | response | projection with size-age, crown LUE or both: living, deadwood and firewood carbon, trees alive, height, net CO2, carbon to soil |
| `ash_dieback_scenario` | response | baseline and ash-dieback runs side by side, optional replanting |
| `planting_scenario` | response | carbon of new hedgerow, agroforestry, riparian or urban trees |
| `calibrate_area` | | crown calibration summarised for a tile or area: productivity, age, growth, height-drop events |
| `validate` | | hold-out skill of both models in each pilot against persistence |
| `assimilate_heights` | state | Kalman filter on new heights; learns and stores the site's productivity shift |
| `get_parameters`, `reset_parameters` | | a site's productivity and where it came from |

Areas are `{"bbox": [W, S, E, N]}` or `{"point": [lon, lat], "radius_m": r}` in degrees
(EPSG:4326); `radius_m: 0` selects the object nearest the point. Tools that take an area also
take an optional `tow_class` (`lone_tree`, `group_of_trees`, `small_woodland`). All tools take
and return typed JSON with input validation and output schemas, and every result carries
provenance (model version, inventory, lidar and allometry citations and licences, parameter
source, assumptions). Stocks and fluxes are totals in tonnes for the selected trees.

## Run

```bash
pip install -r dt6_agent/requirements.txt
python dt6_agent/dt6_server.py          # stdio (for orchestrators that launch it)
python dt6_agent/dt6_server.py --http   # streamable HTTP on http://127.0.0.1:8000/mcp
DT6_PORT=8766 python dt6_agent/dt6_server.py --http
DT6_STATE_FILE=~/.dt6/state.json python dt6_agent/dt6_server.py   # keep learned parameters
```

Register with Claude Code: `claude mcp add dt6 -- python /path/to/dt6_agent/dt6_server.py`

Rebuild the data (needs network access to environment.data.gov.uk and the Met Office Climate
Data Portal, and `pip install rasterio scipy pyproj`; about 20 minutes for all ten tiles):

```bash
python dt6_agent/scripts/extract_pilots.py            # or name pilots: ... breckland oxford
python dt6_agent/scripts/calibrate_pilots.py
```

## Test

```bash
pip install pytest
pytest dt6_agent        # 59 tests, about 30 s
```

- `test_tree_models.py`: the Jucker allometry and its inverse; the size-age curve passes
  through the site index; the crown LUE model responds to productivity, light and drought;
  calibration recovers synthetic trees, catches height drops and ignores same-night
  first/last return differences; the empirical prior is learned from multi-epoch trees;
  deadwood and firewood pools decay as stated; projections are repeatable and close the
  carbon budget; ash dieback lowers carbon and replanting recovers some; planting survival
  matters; the change threshold and the evidence rule for attribution; the Kalman filter moves
  productivity toward the data; the parameter store persists; all ten inventories load; the
  models beat persistence in most pilots; **rerunning `calibrate_pilots.py` reproduces the
  shipped calibration** (Breckland); the package imports no plotting library, prints nothing
  and writes no files.
- `test_dt6_server.py`: every tool in memory, bad inputs come back as tool errors, learning is
  per site, and over stdio a learned value survives a restart with `DT6_STATE_FILE`.
- `test_dt6_end_to_end.py`: the agentic path. An orchestrator query with input parameters
  (the living carbon of part of the Cheshire tile, then the cost of ash dieback over 30 years
  with both models, 10 members, seed 5) goes to `carbon_stock` and `ash_dieback_scenario` in
  memory, over stdio, over streamable HTTP, and as raw JSON-RPC 2.0 over stdio and HTTP
  without the MCP client library. Every answer must equal the `trees` package run directly.

## Assumptions and limitations

- **Lost trees are invisible.** The TOW map lists trees present at its lidar date
  (2016–2023). A tree felled before then is not in the inventory, so its loss cannot be seen,
  and canopy change only measures reductions within objects that still exist. Likewise new
  trees between epochs appear only if they are on the map today.
- **Old surveys.** LIDAR Tiles DSMs before the NLP are last-return only and often at 1–2 m;
  they miss some crown tops and cover only part of most tiles (typically 10–40 % of objects).
  Height drops between epochs include real cutting and pollarding but also some registration
  and resolution artefacts; they are recorded as events and excluded from fitting, not
  attributed.
- **Trees per object** come from tree-top counting on a 1 m canopy model, which merges small
  crowns and splits wide ones; the crown area per tree is the object's area shared equally.
- **Leaf type** is a pilot-level prior (no open leaf-type map for TOW); it changes biomass by
  up to a factor of two for the same crown and height, and is part of the uncertainty.
- **Growth curve shapes are fixed** (size-age asymptote and shape; crown LUE constants). Only θ
  and age are fitted. Many TOW trees are managed (hedgerow trees, pollards, street trees), which
  the curves do not represent except through low θ and the height-drop events. The pilot prior's
  spread is floored at a tenth of the θ range: iterating the empirical prior narrows it, and the
  floor keeps single-date trees from all sharing one curve.
- **Ash share** of broadleaved TOW (15 %) is an assumption; regional surveys would replace it.
- **Climate** for the crown LUE model is the HadUK-Grid 1991–2020 average (no year-to-year
  weather, no climate change); radiation comes from Hargreaves–Samani.
- **Net flux is for the trees, with the soil left to DT7.** Leaf, fine-root and branch litter
  passed to the soil counts as carbon leaving the tree compartment, so mature trees whose
  living stock is level (slow growth balanced by 0.5 % mortality, as in several lowland
  pilots) still show a net uptake equal to their litter. Most of that carbon returns to the air
  as it decomposes in DT7; add DT7 for the ecosystem balance.
- **Crown LUE over-forecasts short-term growth**, by about 1 m a decade in most pilots and
  most where the trees look young (Fens, Leicestershire); its curve shape is fixed and only θ
  and age are fitted. The two models also diverge in long projections where trees are young
  (Tyne valley: 5,500 t C against 10,000 t C by 2055), which is the spread a user should quote.
- **Allometry** (Jucker et al. 2017) was fitted mostly on forest-grown trees; open-grown trees
  have deeper crowns and may carry more branch wood for a given crown and height.
