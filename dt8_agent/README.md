# DT8 agent: peatland condition and greenhouse-gas emissions

DT8 serves the drained-peatland greenhouse-gas twin (CO2, CH4, N2O) to an orchestrator over MCP.

- `peatland/`: a server-safe copy of the model code (the physics is unchanged).
  - `co2.py`: GPP, autotrophic and heterotrophic respiration and NEE per crop (JULES-CROP
    reduction). Dead plant material decomposes through the residue pool `C_res` in Rh.
  - `ch4.py`: the CH4 model in the configuration of Section 14 of
    `peatland_ch4_model_with_litter_extension.ipynb`: 14 land-cover classes plus reed, the
    rewetted-fen calibration of `k_prod`, Inventory validation, SI outputs, peat-depth and SOC
    validity flags (and the peat-capped hypothesis test, off by default), self-learning, and the
    pool of flood-intolerant vegetation killed by standing water. The plant-functional-type
    extension (Section 15) and the Walter–Heimann and JULES intercomparison (Section 11) are left
    out.
  - `soil_temp.py`: the Dolschak et al. (2015) air-to-soil temperature transfer function and its
    calibration routine (Section 3b).
  - `n2o.py`: peat-N mineralisation plus fertiliser N2O, calibrated to the IPCC/UK Tier-2 factors.
    It reads Rh from the CO2 model and feeds nothing back.
  - `inventory.py`: comparison with the UK Peatland Inventory (CEH report) for all three gases.
  - `state.py`: calibrated and learned parameters per site, optionally saved to JSON.
- `dt8_server.py`: MCP server named `dt8`.
- `dt8_agent.ipynb`: acts as the orchestrator. It launches the server, lists the tools and calls
  each of them (executed, outputs included).

## Where the code comes from

| Module | Source |
|---|---|
| `co2.py` | `peatland_pignn.py` (digital_twin `main`) and `peatland_crop_validation.py` (`peatland-ghg-twin`) |
| `n2o.py`, `inventory.py` | `peatland_n2o.py` and Section 9 of `peatland_digital_twin.ipynb` (`peatland-ghg-twin`) |
| `ch4.py`, `soil_temp.py` | `peatland_ch4_model_with_litter_extension.ipynb`, Sections 1–10 and 14 |

The three-gas coupling (balance by crop, water-table scenario) follows `peatland_digital_twin.ipynb`.
The tests pin the copy to the numbers printed in both notebooks, for example annual NEE per crop,
`k_prod` = 203.65, the CH4 skill against Inventory Eq. 3 (NSE 0.88), the 14-class CH4 table, the
self-learning results (`k_prod` 448 → 198, `Q10_CH4` 2.0 → 3.54) and the N2O Tier-2 calibration.

### What changed to make the code server-safe

- No matplotlib or pandas import, no figures or CSV files written to the working directory, no
  prints: every function returns its result.
- Calibrations (`k_prod`, the N2O emission fractions) return parameter sets instead of overwriting
  module globals, so two callers cannot change each other's model.
- Package-relative imports instead of sibling-module imports.
- Learned parameters are stored per site in `ParameterStore`; set `DT8_STATE_FILE` to persist them.
- The CO2 respiration used by the N2O self-learning is cached instead of re-simulated every step.

## Tools

| Tool | What it returns |
|---|---|
| `list_crops` | CO2/N2O crops (phenology, fertiliser N) and the 15 CH4 land-cover classes |
| `simulate_co2` | Annual GPP, Ra, Rh, Reco, NEE for a crop, optionally at a prescribed water table and with the daily series |
| `annual_ch4` | Annual CH4 for a class at a mean water table: base model, flood-killed litter, total |
| `run_ch4_drivers` | CH4 on your own daily drivers (WTD, LAI, soil or air temperature), SI totals, validity flags |
| `annual_n2o` | Annual N2O for a crop, optionally with a different fertiliser rate |
| `ghg_balance` | CO2 + CH4 + N2O in t CO2e/ha/yr (AR6 GWP100) for a crop |
| `water_table_scenario` | Three-gas balance across water-table depths and the net-GHG optimum (a management response, not an observation) |
| `validate_inventory` | Model against Inventory Eqs 1 and 3, the CH4 Tier-2 classes and the N2O Tier-2 factors |
| `get_parameters`, `reset_parameters` | The site's current parameters and where they came from |
| `self_learn_synthetic` | Recovery of CH4 or N2O parameters from a wrong prior on synthetic data |
| `assimilate_ch4` | Update a site's `k_prod` and `Q10_CH4` from observed daily CH4 fluxes |

All tools take and return typed JSON (input validation, output schemas), and every result carries
provenance: model version, source code, drivers, and whether the parameters are calibrated or
learned. Positive fluxes are emissions to the atmosphere. Water-table depth is positive below the
surface.

## Run

```bash
pip install -r dt8_agent/requirements.txt
python dt8_agent/dt8_server.py          # stdio (for orchestrators that launch it)
python dt8_agent/dt8_server.py --http   # streamable HTTP on http://127.0.0.1:8000/mcp
DT8_STATE_FILE=~/.dt8/state.json python dt8_agent/dt8_server.py   # keep learned parameters
```

Register with Claude Code: `claude mcp add dt8 -- python /path/to/dt8_agent/dt8_server.py`

## Test

```bash
pip install pytest
pytest dt8_agent
```

`test_peatland_models.py` checks the copy against both notebooks and checks that importing and
running the models loads no plotting library, prints nothing and writes no files.
`test_dt8_server.py` calls every tool in memory, checks input validation and per-site learning,
and runs the server over stdio with a persistent state file.

## Limitations to keep in mind

- Drivers are the regional Fenland climatology unless you pass your own series to
  `run_ch4_drivers`. CO2 and N2O do not yet take user driver series.
- The CH4 and CO2/N2O modules use different crop tables (14 classes in the CH4 notebook, 10 crops
  in the coupled twin). `ghg_balance` uses the coupled-twin crop LAI for all three gases, as the
  coupled notebook does.
- Which generic classes count as flood intolerant is a mapping made here: sown grassland and all
  arable crops are, reed, upland rough grazing and fallow are not. The notebook decides it from
  each site's species list, which `peatland.ch4.is_flood_intolerant` also accepts.
- The litter extension's parameters are a priori. With winter standing water the pool fills over
  several years and can add more CH4 than the base model, because killed biomass is not removed
  from LAI and harvests are not removed from the pool (Section 14.1).
- The independent field validation (Section 13) needs the site spreadsheet, which is not in the
  repository, so it is not wrapped as a tool.
