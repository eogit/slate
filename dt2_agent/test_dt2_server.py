"""Tests for the DT2 MCP server: run with `pytest dt2_agent`."""

import json
import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import Client, StdioServerParameters

SERVER = Path(__file__).with_name("dt2_server.py")
TOOLS = {"list_categories", "farm_methane", "area_methane", "methane_scenario",
         "methane_hotspots", "cell_profile", "grassland_map", "validate_naei",
         "calibration_report", "get_parameters", "reset_parameters", "assimilate_naei",
         "assimilate_total"}
CREWE = {"lat": 53.10, "lon": -2.44, "radius_km": 10}


@pytest.fixture(scope="module")
def server():
    sys.path.insert(0, str(SERVER.parent))
    import dt2_server

    return dt2_server.server


def call(target, name, args=None):
    async def go():
        async with Client(target) as client:
            return await client.call_tool(name, args or {})

    return anyio.run(go)


def test_tool_catalogue(server):
    async def go():
        async with Client(server) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in anyio.run(go)}
    assert set(tools) == TOOLS
    for t in tools.values():
        assert t.description and t.output_schema, t.name   # every tool is typed both ways


def test_list_categories(server):
    s = call(server, "list_categories").structured_content
    cats = {c["code"]: c for c in s["categories"]}
    assert cats["dairy_cows"]["enteric_kg_ch4_head_yr"] == 123.28
    assert cats["dairy_cows"]["methane_potential_kg_head_yr"] == pytest.approx(316.9, abs=0.1)
    assert sum(r["thousand_head"] for r in s["england_census_2020"]
               if r["group"] in ("dairy", "beef_other")) == 5168
    assert s["group_factors_kg_head_yr"]["dairy"]["enteric"] > \
        s["group_factors_kg_head_yr"]["beef_other"]["enteric"]


def test_farm_methane(server):
    r = call(server, "farm_methane", {"heads": {"dairy_cows": 200, "calves": 60}})
    s = r.structured_content
    assert s["enteric_kg_ch4"] == pytest.approx(200 * 123.28 + 60 * 42.53)
    assert s["t_co2e"] == pytest.approx(s["total_kg_ch4"] * 28 / 1000)
    g = call(server, "farm_methane", {"heads": {"dairy_cows": 200},
                                      "pasture_pct": {"dairy_cows": 60}}).structured_content
    assert g["manure_kg_ch4"] < 200 * 38.03
    assert call(server, "farm_methane", {"heads": {"llama": 3}}).is_error
    assert call(server, "farm_methane", {"heads": {"ewes": -1}}).is_error


def test_area_methane_and_validation(server):
    s = call(server, "area_methane", {"area": CREWE}).structured_content
    assert s["cells_km2"] == pytest.approx(314, abs=4)        # pi x 10^2 km2
    assert s["total_t_ch4"] == pytest.approx(s["enteric_t_ch4"] + s["manure_t_ch4"])
    assert s["t_co2e_ar6"] == pytest.approx(27 * s["total_t_ch4"])
    assert s["stocking_lsu_per_grazing_ha"] > 1.0             # Cheshire dairy country
    e = call(server, "area_methane").structured_content
    assert e["area"] == "England" and e["total_t_ch4"] == pytest.approx(491_651, rel=1e-3)
    assert call(server, "area_methane", {"area": {"lat": 53.1, "lon": -2.4}}).is_error
    assert call(server, "area_methane",
                {"area": {"bbox_bng": [0, 0, 1000, 1000]}}).is_error   # sea, no England cell
    v = call(server, "validate_naei", {"area": {"bbox_bng": [300000, 300000, 400000, 400000]}})
    assert v.structured_content["skill"]["r_10km"] > 0.8
    assert v.structured_content["shipped_holdout"]["r_1km"] == pytest.approx(0.653, abs=0.001)


def test_scenario_hotspots_cells_grassland(server):
    s = call(server, "methane_scenario",
             {"area": CREWE, "interventions": {"herd_change_pct": {"dairy": -20},
                                               "ad_pct_of_housed": 50}}).structured_content
    assert s["change_t_ch4"] < 0 and s["change_pct"] < -5
    assert s["scenario"]["groups"]["dairy"]["heads"] == pytest.approx(
        0.8 * s["baseline"]["groups"]["dairy"]["heads"])
    assert call(server, "methane_scenario",
                {"interventions": {"herd_change_pct": {"pigs": 10}}}).is_error
    h = call(server, "methane_hotspots", {"area": CREWE, "n": 5}).structured_content
    vals = [c["total_t_ch4"] for c in h["cells"]]
    assert len(vals) == 5 and vals == sorted(vals, reverse=True)
    c = call(server, "cell_profile", {"lat": 53.10, "lon": -2.44}).structured_content
    assert abs(c["easting"] - 370500) < 1000 and c["naei_agriculture_t_ch4"] > 0
    assert call(server, "cell_profile", {"lat": 55.8, "lon": -4.0}).is_error   # Scotland
    g = call(server, "grassland_map", {"area": CREWE}).structured_content
    assert g["grazing_groups_ha"]["improved_ha"] == pytest.approx(
        g["living_england_ha"]["Improved Grassland"])


def test_calibration_report(server):
    s = call(server, "calibration_report").structured_content
    assert s["chosen"]["block_km"] == 10
    assert s["holdout"]["r_1km"] > s["reference_holdout"][
        "malek_all_layers_no_living_england"]["r_1km"]
    assert len(s["best_trials"]) == 10


def test_learning_is_per_site(server):
    call(server, "reset_parameters", {"site": "crewe"})
    before = call(server, "area_methane", {"area": CREWE, "site": "crewe"}).structured_content
    r = call(server, "assimilate_naei", {"area": CREWE, "site": "crewe"}).structured_content
    assert r["posterior"]["cattle"] > 1.1 and r["persisted"]
    after = call(server, "area_methane", {"area": CREWE, "site": "crewe"}).structured_content
    other = call(server, "area_methane", {"area": CREWE}).structured_content
    assert after["total_t_ch4"] > before["total_t_ch4"]
    assert other["total_t_ch4"] == pytest.approx(before["total_t_ch4"])   # default unchanged
    assert "learned" in after["provenance"]["site_factors"]
    t = call(server, "assimilate_total", {"area": CREWE, "site": "crewe2",
                                          "observed_t_ch4": 2000, "sd_t_ch4": 100,
                                          "persist": False}).structured_content
    assert t["diagnostics"]["predicted_after_t_ch4"] == pytest.approx(2000, rel=0.1)
    assert call(server, "get_parameters", {"site": "crewe2"}).structured_content["cattle"] == 1.0
    reset = call(server, "reset_parameters", {"site": "crewe"}).structured_content
    assert reset["cattle"] == 1.0 and "crewe" not in reset["known_sites"]
    assert call(server, "get_parameters", {"site": "bad site!"}).is_error


def test_stdio_with_persistent_state(tmp_path):
    state = tmp_path / "state.json"
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)],
                                   env={**os.environ, "DT2_STATE_FILE": str(state)})

    async def go():
        async with Client(params) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            r = await client.call_tool("assimilate_naei", {"area": CREWE, "site": "farm1"})
            return names, r

    names, r = anyio.run(go)
    assert names == TOOLS and not r.is_error
    saved = json.loads(state.read_text())["sites"]["farm1"]["params"]
    assert saved["cattle"] == pytest.approx(r.structured_content["posterior"]["cattle"])
