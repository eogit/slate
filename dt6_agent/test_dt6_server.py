"""Tests of the DT6 MCP server: run with ``pytest dt6_agent``.

Every tool is called in memory through the MCP client, inputs outside their ranges must come
back as tool errors (not crashes), learning is kept per site, and over stdio the learned
productivity shift survives a server restart when ``DT6_STATE_FILE`` is set.
"""

import json
import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import Client, StdioServerParameters

HERE = Path(__file__).resolve().parent
SERVER = HERE / "dt6_server.py"
sys.path.insert(0, str(HERE))

TOOLS = {"list_landscapes", "tree_inventory", "carbon_stock", "canopy_change",
         "attribute_change", "simulate_trees", "ash_dieback_scenario", "planting_scenario",
         "calibrate_area", "validate", "assimilate_heights", "get_parameters",
         "reset_parameters"}
BRECK_BOX = [0.58, 52.40, 0.62, 52.42]


@pytest.fixture(scope="module")
def server():
    import dt6_server

    return dt6_server.server


def call(target, name, args=None):
    async def go():
        async with Client(target) as client:
            return await client.call_tool(name, args or {})

    return anyio.run(go)


def ok(target, name, args=None):
    r = call(target, name, args)
    assert not r.is_error, r.content
    return r.structured_content


def test_tool_catalogue(server):
    async def go():
        async with Client(server) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in anyio.run(go)}
    assert set(tools) == TOOLS
    for t in tools.values():
        assert t.description and t.output_schema, t.name
    assert {"pilot", "area", "tow_class"} <= set(tools["carbon_stock"].input_schema["properties"])


def test_list_landscapes(server):
    r = ok(server, "list_landscapes")
    assert len(r["landscapes"]) == 10
    for ls in r["landscapes"]:
        assert ls["objects"] > 500 and len(ls["lidar_epochs"]) >= 2
        assert {c["growth_model"] for c in ls["calibration"]} == {"size_age", "crown_lue"}


def test_inventory_and_stock(server):
    whole = ok(server, "tree_inventory", {"pilot": "breckland"})
    part = ok(server, "tree_inventory", {"pilot": "breckland", "area": {"bbox": BRECK_BOX}})
    assert 0 < part["objects"] < whole["objects"]
    assert whole["land_area_ha"] == pytest.approx(2500)
    assert sum(c["objects"] for c in whole["by_class"]) == whole["objects"]
    st = ok(server, "carbon_stock", {"pilot": "breckland"})
    assert st["agb_p05_t"] < st["agb_t"] < st["agb_p95_t"]
    assert st["agb_t"] == pytest.approx(whole["agb_t"], rel=1e-9)
    assert st["ebcf_role"] == "state"
    lone = ok(server, "carbon_stock", {"pilot": "breckland", "tow_class": "lone_tree"})
    assert lone["objects"] < st["objects"]
    one = ok(server, "carbon_stock", {"pilot": "breckland",
                                      "area": {"point": [0.6, 52.41], "radius_m": 0}})
    assert one["objects"] == 1


def test_change_and_attribution(server):
    ch = ok(server, "canopy_change", {"pilot": "cheshire", "year1": 2001, "year2": 2021})
    assert ch["epoch1"] == 2001 and ch["epoch2"] == 2021 and ch["objects_compared"] > 100
    assert ch["ebcf_role"] == "impact"
    at = ok(server, "attribute_change", {
        "pilot": "cheshire", "year1": 2001, "year2": 2021,
        "evidence": [{"pressure": "felling", "year_from": 2005, "year_to": 2015,
                      "bbox": [-2.9, 53.18, -2.83, 53.22], "source": "test licence"}]})
    assert at["ebcf_role"] == "pressure"
    assert at["reductions"] == ch["significant_reductions"]
    assert at["unattributed_objects"] <= at["reductions"]


def test_simulate_both_models(server):
    r = ok(server, "simulate_trees", {"pilot": "breckland", "area": {"bbox": BRECK_BOX},
                                      "years": 10, "n_members": 10})
    assert [x["growth_model"] for x in r["runs"]] == ["size_age", "crown_lue"]
    for run in r["runs"]:
        assert len(run["years"]) == 11 and run["mean_annual_net_t_co2_yr"] < 0
        # trees keep growing, though slow growth and 0.5 %/yr mortality can offset each other
        assert run["height_median_m"]["mean"][-1] > run["height_median_m"]["mean"][0]
        assert run["living_c_t"]["p05"][0] <= run["living_c_t"]["mean"][0] <= run["living_c_t"]["p95"][0]
    assert r["ebcf_role"] == "response"


def test_ash_and_planting(server):
    r = ok(server, "ash_dieback_scenario", {"pilot": "tyne_valley", "years": 15,
                                            "n_members": 10, "ash_share": 0.3})
    base, ash = r["runs"]
    assert ash["living_c_t"]["mean"][-1] < base["living_c_t"]["mean"][-1]
    p = ok(server, "planting_scenario", {"pilot": "somerset_levels", "n_trees": 500,
                                         "kind": "riparian", "years": 40, "n_members": 10})
    assert len(p["runs"]) == 2 and all(x["cumulative_net_t_co2"][0] < 0 for x in p["runs"])


def test_calibrate_and_validate(server):
    c = ok(server, "calibrate_area", {"pilot": "fens", "growth_model": "size_age"})
    assert c["results"][0]["objects"] > 500
    v = ok(server, "validate", {"pilots": ["fens", "oxford"]})
    assert {r["pilot"] for r in v["rows"]} == {"fens", "oxford"} and len(v["rows"]) == 4


def test_learning_is_per_site(server):
    import dt6_server
    from trees import inventory

    inv = inventory.load("breckland")
    obs = [{"tow_id": str(inv.tow_id[i]), "year": 2026.0, "height_m": float(inv.h_fz[i]) + 3,
            "sd_m": 0.5} for i in range(25)]
    r = ok(server, "assimilate_heights", {"pilot": "breckland", "site": "farm_a",
                                          "observations": obs, "growth_model": "size_age"})
    shift = r["results"][0]["productivity_shift"]
    assert r["results"][0]["n_matched"] == 25 and shift > 0 and r["results"][0]["persisted"]
    a = ok(server, "get_parameters", {"pilot": "breckland", "site": "farm_a"})
    b = ok(server, "get_parameters", {"pilot": "breckland", "site": "farm_b"})
    sa = next(p for p in a["parameters"] if p["growth_model"] == "size_age")
    sb = next(p for p in b["parameters"] if p["growth_model"] == "size_age")
    assert sa["learned_shift"] == pytest.approx(shift) and sb["learned_shift"] == 0
    assert sa["source"].startswith("learned")
    after = ok(server, "reset_parameters", {"pilot": "breckland", "site": "farm_a"})
    assert all(p["learned_shift"] == 0 for p in after["parameters"])
    dt6_server.store.reset("farm_a")


@pytest.mark.parametrize("name,args", [
    ("tree_inventory", {"pilot": "atlantis"}),
    ("carbon_stock", {"pilot": "fens", "area": {"bbox": [10, 10, 11, 11]}}),
    ("canopy_change", {"pilot": "fens", "year1": 2019, "year2": 2019}),
    ("canopy_change", {"pilot": "fens", "year1": 1990, "year2": 2019}),
    ("simulate_trees", {"pilot": "fens", "years": 500}),
    ("planting_scenario", {"pilot": "fens", "n_trees": 10, "kind": "orchard"}),
    ("assimilate_heights", {"pilot": "fens", "site": "x", "observations": [
        {"year": 2025, "height_m": 10}]}),
    ("attribute_change", {"pilot": "fens", "year1": 2017, "year2": 2021, "evidence": [
        {"pressure": "aliens", "year_from": 2018, "year_to": 2020, "bbox": [0, 0, 1, 1]}]}),
])
def test_bad_inputs_are_tool_errors(server, name, args):
    assert call(server, name, args).is_error


def test_stdio_state_survives_restart(tmp_path):
    state = tmp_path / "dt6_state.json"
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)],
                                   env={**os.environ, "DT6_STATE_FILE": str(state)})
    from trees import inventory

    inv = inventory.load("fens")
    obs = [{"tow_id": str(inv.tow_id[i]), "year": 2026.0, "height_m": float(inv.h_fz[i]) + 2,
            "sd_m": 0.5} for i in range(10)]
    r = call(params, "assimilate_heights", {"pilot": "fens", "site": "restart",
                                            "growth_model": "size_age",
                                            "observations": obs}).structured_content
    shift = r["results"][0]["productivity_shift"]
    assert json.loads(state.read_text())["sites"]["restart"]["size_age"]["theta_shift"] == pytest.approx(shift)
    again = call(params, "get_parameters", {"pilot": "fens", "site": "restart"}).structured_content
    sa = next(p for p in again["parameters"] if p["growth_model"] == "size_age")
    assert sa["learned_shift"] == pytest.approx(shift) and sa["source"].startswith("learned")
