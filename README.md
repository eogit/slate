# SLATE

An agentic digital twin for land use, forestry and peatland Earth observation. Its
applications are exposed as MCP servers so that an orchestrator can discover and call them.

## Agents

| Folder | Agent | Tools |
|---|---|---|
| `dt1_agent/` | DT1, a hello-world agent proving the MCP plumbing end to end | `hello` |
| `dt2_agent/` | DT2, livestock methane twin for England (enteric and manure CH4 of cattle, sheep and goats on a 1 km grid; Malek et al. livestock maps, Living England grassland, UK inventory factors as in the Farm Carbon Calculator) | `area_methane`, `methane_scenario`, `farm_methane`, `methane_hotspots`, `cell_profile`, `grassland_map`, `validate_naei`, `assimilate_naei`, `assimilate_total` and catalogue and parameter tools |
| `dt4_agent/` | DT4, forest above-ground biomass and carbon twin: ESA Biomass CCI v7, NFI and Forestry England species and stand ages, HadUK-Grid climate, yield curves and 3-PG per species group, management and disturbance scenarios (Thetford, Kielder) | `forest_inventory`, `get_agb`, `biomass_change`, `attribute_change`, `simulate_stand`, `management_scenario`, `afforestation_scenario`, `calibrate_site`, `validate`, `assimilate_agb` and catalogue and parameter tools |
| `dt6_agent/` | DT6, trees-outside-woodland biomass and carbon twin: National Trees Outside Woodland map, repeat Environment Agency lidar heights (1998 onwards), size-age curves and a crown light-use model calibrated crown by crown, ash-dieback and planting scenarios (ten pilot tiles across England) | `tree_inventory`, `carbon_stock`, `canopy_change`, `attribute_change`, `simulate_trees`, `ash_dieback_scenario`, `planting_scenario`, `calibrate_area`, `validate`, `assimilate_heights` and catalogue and parameter tools |
| `dt8_agent/` | DT8, drained-peatland greenhouse-gas twin (CO2, CH4 with flood-killed litter, N2O) | `simulate_co2`, `annual_ch4`, `run_ch4_drivers`, `annual_n2o`, `ghg_balance`, `water_table_scenario`, `validate_inventory`, self-learning and parameter tools |
| `orchestrator/` | The orchestrator agent: interprets a plain-language question, asks follow-up questions or states its assumptions, calls the twins over MCP and writes a short report with figures | Claude agent; see `orchestrator/README.md` |
| `demo/` | Persona demonstration: one question per persona that needs several twins, answered by the orchestrator with a real Claude model loop; recorded reports and a walkthrough | see `demo/README.md` |

See each folder's README for how to run, register and test the agent.
