# DT2 agent: livestock methane in England

DT2 serves a livestock methane twin to an orchestrator over MCP. It keeps a 1 km picture of
England's cattle, sheep and goats, the grassland they graze, and the **enteric and manure
methane** they emit, and answers questions for any area, single cells, farms and what-if
scenarios. It learns site by site from methane observations.

## Decisions this build follows

- **Open livestock data instead of holding-level microdata.** The livestock maps are
  **Malek et al. (2024)** on Zenodo, the official head counts are the published **Defra June
  Survey** tables. No restricted census or Cattle Tracing System microdata are used.
- **Emission factors as the Farm Carbon Toolkit uses them**, so a farm assessed with the
  Farm Carbon Calculator and the same farm inside DT2 get the same methane per head.
- **Living England as the grassland map of England** (ancillary data for placing animals and
  for stocking rates).
- **Reasonable assumptions where the sources stop**, each listed below.

## Data sources

| What | Source | Licence | Used for |
|---|---|---|---|
| Livestock distribution | Malek, Ž., Romanchuk, Z., Yashchun, O. and See, L. (2024). *Spatial distribution of cattle, sheep and goat density, and grazed areas for the European Union and the United Kingdom*, v1. Zenodo, [doi:10.5281/zenodo.13734518](https://doi.org/10.5281/zenodo.13734518). Companion paper: Malek et al. (2024), *Landscape Ecology*, doi:10.1007/s10980-024-01810-6. ~2020, 100 m, EPSG:3035, LSU/ha | CC BY 4.0 | where cattle and sheep are (relative weights) |
| Head counts | Defra, *Farming statistics: final land use, livestock populations and agricultural workforce at 1 June 2020, England* (22 Dec 2020), Tables 7, 9, 11 | OGL | how many animals of each category |
| Emission factors | UK Greenhouse Gas Inventory 1990–2023, National Inventory Document 2025, Annex A 5.1.3: Table A 5.1.8 (enteric and manure CH4 per head, 2023), Table A 5.1.9 (methane conversion factors), Table A 5.1.11 (manure management systems) | OGL | methane per head and per manure system |
| Method and GWP | Farm Carbon Toolkit, *Methodology of the Farm Carbon Calculator* v3.6 (April 2026), Section 11.6, Eqs 1a and 4; *Livestock update* (June 2025) | — | equations, AR5 GWP100 = 28 |
| Grassland | Natural England, *Living England Habitat Map* Phase 4 (feature service `Living_England_Habitat_Map_Phase4`), 6.9 million segments | OGL | grazing land per km², placing animals, stocking rates |
| Validation | NAEI gridded emissions 2020, methane, SNAP 10 agriculture, 1 km | OGL | calibrating the allocation, validation, site learning |

## Which methane factors the Farm Carbon Calculator uses, and how DT2 uses them

The calculator's methodology (v3.6, Section 11.6) computes livestock methane at its default
**Tier 2** as

    enteric CH4 (t CO2e) = default enteric EF x head x 28 / 1000                  (Eq. 1a)
    manure CH4 (t CO2e)  = kg manure x (Bo x 0.67) x (MCF / 100) x 28 / 1000      (Eq. 4)

where the default enteric EF is "the UK GHG inventories value, kg CH4/head/year", Bo is the
methane-producing capacity and MCF the storage system's methane conversion factor, and 28 the
IPCC AR5 GWP100 of methane. The calculator's own tables of factors are not published in the
methodology; it points to the UK inventory annexes and to the IPCC 2019 Refinement. DT2
therefore takes the factors from the **inventory itself** (latest edition, NID 2025; the
calculator's June 2025 update cites the 1990–2022 edition, and the inventory revises the
factors every year):

| Category (inventory) | Enteric kg CH4/head/yr | Manure kg CH4/head/yr |
|---|---|---|
| Dairy cows | 123.28 | 38.03 |
| Dairy heifers | 53.72 | 5.96 |
| Dairy replacements > 1 year | 50.18 | 5.78 |
| Dairy calves < 1 year | 42.53 | 3.67 |
| Beef cows | 75.99 | 10.72 |
| Beef females for slaughter | 48.73 | 5.70 |
| Bulls for breeding | 59.13 | 8.28 |
| Heifers for breeding | 48.23 | 6.25 |
| Steers | 49.91 | 5.84 |
| Ewes | 6.98 | 0.18 |
| Rams | 8.25 | 0.23 |
| Lambs | 3.05 | 0.07 |
| Goats | 9.00 | 0.39 |

Methane conversion factors (Table A 5.1.9): liquid 17 %, daily spread 0.1 %, solid/FYM cattle
17 %, FYM sheep 2 %, pasture 1 %, anaerobic digestion (cattle) 3 %. System shares (Table A
5.1.11): dairy cows 61 / 9 / 8 / 20 / 2 % (liquid, daily spread, solid, pasture, AD), all other
cattle 18 / 14 / 17 / 49 / 1, ewes and goats 0 / 0 / 8 / 92 / 0, rams and lambs 0 / 0 / 1 / 99 / 0.

**Manure in the calculator's form.** The inventory gives one manure EF per head with the UK
system mix folded in. DT2 writes it as `EF = P x sum(share x MCF)` with `P = VS x Bo x 0.67`
and back-calculates P per category from the inventory EF and shares (a UK dairy cow comes out at
317 kg CH4/head/yr, which is 1,970 kg VS x 0.24 m³/kg x 0.67). With the inventory shares DT2
returns exactly the inventory EF; with other shares (more grazing, digestion) it returns what
the calculator's Eq. 4 gives. CO2e is reported with AR5 (28, the calculator) and AR6 (27,
non-fossil, as DT8 reports).

## How the twin works

**Count.** The June Survey 2020 rows for England are mapped onto the inventory categories
(`livestock/herd.py`) and grouped as *dairy* (dairy herd and its female followers, 1.89 M head),
*beef and other cattle* (suckler herd, beef followers, all male cattle and beef calves,
3.28 M), *sheep* (15.03 M) and *goats* (0.09 M).

**Place.** `scripts/extract_malek_livestock.py` sums Malek's 100 m LSU into DT2's 1 km British
National Grid. `scripts/extract_living_england.py` reads every Living England segment's
centroid, class and area and adds the area to its 1 km cell (England = 13.05 Mha). Within each
10 km block, the Malek weight is then shared among the cells in proportion to Living England
grazing land: improved grassland + 0.5 x semi-natural grassland for cattle; improved +
semi-natural grassland + rough grazing (dwarf shrub heath, bog, bracken, fen/marsh/swamp,
saltmarsh) for sheep and goats. Each group's England total is spread over the weights, so head
counts are conserved exactly.

**Calibrate.** The housed-cattle weight, the block size and the semi-natural weight were chosen
by grid search against the NAEI 2020 agricultural methane map on half of England (a checkerboard
of 20 km squares) and scored on the other half (`livestock/calibration.py`,
`scripts/calibrate_allocation.py`). The emission factors and head counts are not tuned.

| Allocation (scored on hold-out squares) | r 1 km | r 5 km | r 10 km | r 20 km |
|---|---|---|---|---|
| Malek, all cattle layers, no Living England | 0.503 | 0.742 | 0.830 | 0.887 |
| Malek, grazing cattle layers, no Living England | 0.558 | 0.857 | 0.934 | 0.974 |
| **DT2: Malek grazing layers refined with Living England (10 km blocks)** | **0.653** | **0.868** | **0.934** | **0.974** |

The grassland map is what raises the 1 km agreement (from 0.56 to 0.65); at 10 km and above
Living England keeps Malek's regional totals by construction.

**Emit.** Heads x inventory factors per category, with the scenario's changes
(`livestock/model.py`). England: **491.7 kt CH4/yr** (86 % enteric) = 13.8 Mt CO2e (AR5); dairy
220 kt, beef and other cattle 194 kt, sheep 77 kt, goats 0.8 kt. The NAEI's 2020 agriculture map
gives 547 kt for England, which also contains pigs, poultry, horses and deer (roughly 30–40 kt),
so DT2 is 10 % below it, as expected.

**Learn.** A site's cattle and sheep numbers can be corrected from methane observations with a
linear-Gaussian (Kalman) update of two factors (`livestock/assimilation.py`): from NAEI cells, or
from one observed area total such as an aircraft mass balance or a satellite inversion. Learned
factors are kept per site and can be persisted (`DT2_STATE_FILE`). Around Crewe (Cheshire dairy
country) the NAEI map lifts the cattle factor to 1.22–1.27, because the dairy share there is
higher than England's average; learning on half the cells there halves the error on the other half
(tested).

## Assumptions

1. **Units of the Malek layers are LSU/ha** (the unit of the record's legend). This is
   consistent for sheep (England 1.5 M LSU = 15 M head x 0.1) but not for cattle, where the
   layers sum to 10.9 M LSU against about 4 M in England. DT2 therefore uses the layers only as
   relative weights and takes absolute numbers from the June Survey.
2. **Malek's housed-cattle layer ("cattle_other") is left out** of the weights (weight 0, the
   calibration's choice). It holds blocks of up to 854 LSU/ha filling whole kilometre squares
   (around Bodmin Moor, for example), clipped at 5 LSU/ha in the shipped layer, and lowers the
   agreement with the NAEI map at every weight tried. Housed cattle are therefore placed like
   grazing cattle.
3. **One herd structure for all of England.** The dairy share is the same everywhere, because
   no open map separates dairy from beef. Site learning corrects it where observations exist.
4. **Census rows to inventory categories:** other dairy females 2+ years = dairy heifers, dairy
   females 1–2 = dairy replacements, beef females 2+ outside the herd = heifers for breeding,
   beef females 1–2 = beef females for slaughter, male cattle 2+ = bulls for breeding, males 1–2
   = steers, other sheep 1+ = ewes.
5. **All calves under one year use the dairy-calf factor**; the inventory gives none for beef
   calves.
6. **Goats' farmyard manure uses the sheep MCF (2 %)**; the inventory lists cattle/pig and
   sheep FYM only. The published "all other cattle" system shares sum to 99 % and are rescaled
   to 100 %.
7. **Year mix:** livestock distribution ~2020, head counts June 2020, emission factors 2023
   (latest inventory edition). The per-head factors change by a few per cent a year.
8. **Pasture share = grazing days / 365**, with excretion spread evenly over the year; the housed
   remainder keeps the inventory's proportions between housed systems.
9. **Grassland loss:** animals leave with the improved and semi-natural grassland they grazed,
   at unchanged stocking (no intensification on the remaining grass). Rough grazing is kept.
10. **Feed additives** are passed as an effective herd-average reduction of enteric methane; DT2
    does not model diets.
11. **NAEI as validation data** contains pigs, poultry, horses and deer; site learning removes 5 %
    of each observed cell for them by default (`other_fraction`).
12. **England** is where Living England has more than 50 ha in a 1 km cell (130,524 km²).

## Layout

| Path | What it is |
|---|---|
| `dt2_server.py` | MCP server named `dt2` (13 tools) |
| `livestock/factors.py` | inventory factors, manure systems, the calculator's Eq. 1a/4 (`farm_methane`) |
| `livestock/herd.py` | June Survey 2020 England rows mapped to inventory categories and groups |
| `livestock/grid.py` | the 1 km British National Grid |
| `livestock/maps.py` | data layers, Living England grazing groups, allocation |
| `livestock/model.py` | areas, scenarios, emissions per cell and per area |
| `livestock/calibration.py` | allocation calibration and skill against NAEI |
| `livestock/assimilation.py` | site learning (Kalman update) |
| `livestock/state.py` | learned site factors (`DT2_STATE_FILE` to persist) |
| `livestock/data/` | Malek LSU (2.6 MB), Living England (2.5 MB) and NAEI (0.6 MB) on the 1 km grid, shipped calibration |
| `scripts/extract_malek_livestock.py` | rebuilds the Malek layer from the Zenodo GeoTIFFs |
| `scripts/extract_living_england.py` | rebuilds the Living England layer from Natural England's feature service (~10 min) |
| `scripts/extract_naei_ch4.py` | cuts the NAEI 1 km methane map to the grid |
| `scripts/calibrate_allocation.py` | regenerates `calibration_naei_2020.json` (seconds) |
| `dt2_agent.ipynb` | acts as the orchestrator: launches the server and calls every tool (executed) |

## Tools

| Tool | What it returns |
|---|---|
| `list_categories` | categories, inventory factors, manure systems and methane potential; England census rows |
| `farm_methane` | a herd's methane from head counts, the Farm Carbon Calculator's Tier 2 way, with optional pasture share and enteric reduction |
| `area_methane` | heads, LSU, enteric and manure CH4 per group, CO2e (AR5, AR6), Living England grassland, stocking rate, for a BNG box, point and radius, or England |
| `methane_scenario` | baseline vs scenario: herd change per group, pasture share, anaerobic digestion, enteric reduction, grassland loss, stocking cap |
| `methane_hotspots` | the highest-emitting 1 km cells with their animals, grassland and NAEI value |
| `cell_profile` | one 1 km cell at a point |
| `grassland_map` | every Living England class and the grazing groups in an area |
| `validate_naei` | r at 1–20 km and ratio of totals against NAEI over an area, plus the shipped hold-out scores |
| `calibration_report` | the shipped calibration and best alternatives |
| `get_parameters`, `reset_parameters` | a site's learned livestock factors |
| `assimilate_naei`, `assimilate_total` | learn a site's factors from NAEI cells or an observed total |

All tools take and return typed JSON, and results carry provenance (factor, census, map and
grassland sources, the allocation, and whether the site's factors are learned). Positive =
emission to the atmosphere.

## Run

```bash
pip install -r dt2_agent/requirements.txt
python dt2_agent/dt2_server.py          # stdio
python dt2_agent/dt2_server.py --http   # streamable HTTP on http://127.0.0.1:8000/mcp
DT2_STATE_FILE=~/.dt2/state.json python dt2_agent/dt2_server.py   # keep learned factors
```

Register with Claude Code: `claude mcp add dt2 -- python /path/to/dt2_agent/dt2_server.py`

To rebuild the data: download the Zenodo record's GeoTIFFs, then

```bash
pip install rasterio
python dt2_agent/scripts/extract_malek_livestock.py /path/to/zenodo_13734518/
python dt2_agent/scripts/extract_living_england.py
python dt2_agent/scripts/extract_naei_ch4.py 10agriculturech424_2020.asc 2020
python dt2_agent/scripts/calibrate_allocation.py
```

## Test

```bash
pip install pytest
pytest dt2_agent
```

`test_livestock_models.py` pins the factors to Table A 5.1.8, checks the manure decomposition,
the calculator's Eq. 1a, the census totals, the data layers, conservation of heads, the England
totals, the scenarios, the shipped calibration, that Living England beats Malek alone on the
hold-out squares, recovery of synthetic site factors, that NAEI learning improves unseen cells,
and that the package loads no plotting library or GDAL and writes no files.
`test_dt2_server.py` calls every tool in memory, checks input validation and per-site learning,
and runs the server over stdio with a persistent state file. `test_dt2_end_to_end.py` sends one
orchestrator query (methane within 10 km of Crewe, and with 20 % fewer dairy cattle and half the
housed manure digested) in memory, over stdio, over HTTP and as raw JSON-RPC over stdio and HTTP,
and checks every answer against the model run directly.

## Limitations to keep in mind

- Dairy and beef are not separated spatially (assumption 3); expect DT2 to be low in dairy
  districts and high in suckler and upland areas until a site has learned.
- Pigs, poultry, horses and deer are not modelled.
- Nitrous oxide from manure and grazing returns is not modelled (the calculator's Eqs 5–7);
  DT2 is a methane twin for now.
- The Malek maps are a single epoch (~2020). Year-to-year change comes only from scenarios and
  learning, not from new livestock maps.
- The NAEI map is itself modelled from census data, so it is a reference, not truth; agreement
  with it says the pattern is consistent with the census, not that either is right cell by cell.
