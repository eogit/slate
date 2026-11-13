# SLATE

An agentic digital twin for land use, forestry and peatland Earth observation. Its
applications are exposed as MCP servers so that an orchestrator can discover and call them.

## Agents

| Folder | Agent | Tools |
|---|---|---|
| `dt1_agent/` | DT1, a hello-world agent proving the MCP plumbing end to end | `hello` |
| `dt8_agent/` | DT8, drained-peatland greenhouse-gas twin (CO2, CH4 with flood-killed litter, N2O) | `simulate_co2`, `annual_ch4`, `run_ch4_drivers`, `annual_n2o`, `ghg_balance`, `water_table_scenario`, `validate_inventory`, self-learning and parameter tools |

See each folder's README for how to run, register and test the agent.
