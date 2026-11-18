"""Tests of the DT4 MCP server: run with ``pytest dt4_agent``.

Every tool is called in memory through the MCP client, inputs outside their ranges must come
back as tool errors (not crashes), learning is kept per site, and over stdio the learned
productivity survives a server restart when ``DT4_STATE_FILE`` is set.
"""

import json
import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import Client, StdioServerParameters

HERE = Path(__file__).resolve().parent
SERVER = HERE / "dt4_server.py"
sys.path.insert(0, str(HERE))

TOOLS = {"list_species", "list_landscapes", "get_agb", "agb_timeseries", "carbon_stock",
         "biomass_change", "attribute_change", "simulate_stand", "management_scenario",
         "afforestation_scenario", "calibrate_site", "validate", "assimilate_agb",
         "get_parameters", "reset_parameters", "self_learn_synthetic", "forest_inventory"}


@pytest.fixture(scope="module")
def server():
    import dt4_server

    return dt4_server.server


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
    assert {"landscape", "year", "area", "species"} <= set(tools["get_agb"].input_schema["properties"])
    assert "species" in tools["management_scenario"].input_schema["properties"]


def test_catalogue_tools(server):
    s = ok(server, "list_species")
    assert {x["code"] for x in s["species"]} == {"SS", "NS", "CP", "SP", "LP", "DF", "LA",
                                                 "OK", "BE", "BI", "MB"}
    assert {r["name"] for r in s["regimes"]} == {"no_intervention", "thin_and_fell",
                                                 "clearfell_no_thin", "continuous_cover"}
    ls = ok(server, "list_landscapes")
    keys = {x["key"]: x for x in ls["landscapes"]}
    assert set(keys) == {"thetford", "kielder"}
    assert keys["kielder"]["dominant_species"] == "SS"
    assert len(keys["kielder"]["calibration"]) == 2 * 7          # 7 species groups x 2 models
    assert keys["kielder"]["woodland_source"] == "NFI woodland GB 2024"
    assert keys["kielder"]["composition"][0]["species"] == "SS"
    assert "HadUK-Grid" in keys["kielder"]["climate_source"]
    assert "Biomass CCI v7" in ls["provenance"]["assumptions"][0]
    assert "Forestry Commission" in ls["provenance"]["inventory"]


def test_forest_inventory(server):
    inv = ok(server, "forest_inventory", {"landscape": "thetford"})
    comp = {r["species"]: r for r in inv["composition"]}
    assert inv["composition"][0]["species"] == "CP"
    assert comp["CP"]["calibrated"] and comp["CP"]["age_median"] > 20
    assert sum(r["share"] for r in inv["composition"]) == pytest.approx(1.0)
    cp = next(c for c in inv["calibration"] if c["species"] == "CP" and c["growth_model"] == "yield_curve")
    assert cp["fe_yield_class_median"] == 14.0 and cp["holdout_2018_2024_free_age"]["n"] > 0
    part = ok(server, "forest_inventory", {"landscape": "kielder",
                                           "area": {"point": [-2.55, 55.2], "radius_m": 1000}})
    assert part["woodland_area_ha"] < 400


def test_state_tools(server):
    a = ok(server, "get_agb", {"landscape": "thetford", "year": 2020})
    assert a["agb_mean_mg_ha"] == pytest.approx(104.9151, abs=1e-3)
    sp = ok(server, "get_agb", {"landscape": "thetford", "year": 2020, "species": "SP"})
    assert sp["n_pixels"] < a["n_pixels"]
    assert a["agb_p05_mg_ha"] < a["agb_mean_mg_ha"] < a["agb_p95_mg_ha"]
    assert a["ebcf_role"] == "state"
    p = ok(server, "get_agb", {"landscape": "kielder", "year": 2024,
                               "area": {"point": [-2.55, 55.2], "radius_m": 500}})
    assert p["n_pixels"] < 200 and "radius 500 m" in p["area"]
    ts = ok(server, "agb_timeseries", {"landscape": "kielder"})
    assert [r["year"] for r in ts["series"]][:9] == [2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2015]
    assert ts["trend_mg_ha_yr_2015_2024"] > 0
    c = ok(server, "carbon_stock", {"landscape": "kielder", "year": 2024})
    assert c["living_c_t_ha"] == pytest.approx(c["above_ground_c_t_ha"] + c["below_ground_c_t_ha"])
    assert c["total_living_co2e_t"] == pytest.approx(c["living_co2e_t_ha"] * c["area_ha"])


def test_change_tools(server):
    ch = ok(server, "biomass_change", {"landscape": "kielder", "year1": 2015, "year2": 2024})
    assert ch["ebcf_role"] == "impact" and "impact" in ch
    at = ok(server, "attribute_change", {
        "landscape": "kielder", "year1": 2015, "year2": 2024,
        "evidence": [{"pressure": "harvest", "year_from": 2015, "year_to": 2024,
                      "bbox": [-2.70, 55.13, -2.50, 55.30], "source": "test felling layer"}]})
    assert at["ebcf_role"] == "pressure"
    assert 0 < at["attributions"][0]["share_of_loss"] < 1
    assert at["unattributed_share"] == pytest.approx(1 - at["attributions"][0]["share_of_loss"])


def test_simulate_stand_both_models(server):
    s = ok(server, "simulate_stand", {"landscape": "kielder", "age": 20, "years": 30})
    assert [r["growth_model"] for r in s["runs"]] == ["yield_curve", "3pg"]
    for r in s["runs"]:
        assert len(r["years"]) == 31 and r["years"][0] == 2024
        assert r["cumulative_net_t_co2_ha"][0] < 0          # growing forest = sink
        assert r["productivity_source"].startswith("calibrated baseline")
    custom = ok(server, "simulate_stand", {"landscape": "kielder", "age": 20, "years": 10,
                                           "growth_model": "yield_curve", "yield_class": 16})
    assert custom["runs"][0]["productivity"] == 16
    assert custom["runs"][0]["n_members"] == 1


def test_scenarios(server):
    m = ok(server, "management_scenario", {"landscape": "kielder", "horizon_years": 40,
                                           "n_members": 20})
    assert len(m["outcomes"]) == 8 and set(m["best_for_carbon"]) == {"yield_curve", "3pg"}
    assert m["ebcf_role"] == "response"
    nothing = [o for o in m["outcomes"] if o["regime"] == "no_intervention"]
    assert all(o["removals_total_t_dm_ha"] == 0 for o in nothing)
    sp = ok(server, "management_scenario", {"landscape": "kielder", "species": "NS",
                                            "regimes": ["clearfell_no_thin"], "horizon_years": 20,
                                            "growth_model": "yield_curve", "n_members": 5})
    assert sp["species"] == "NS" and "NS in kielder" in sp["provenance"]["parameters"]
    assert call(server, "management_scenario", {"landscape": "kielder", "species": "CP"}).is_error
    af = ok(server, "afforestation_scenario", {"landscape": "thetford", "species": "SS",
                                               "area_ha": 10, "horizon_years": 30})
    for model, total in af["total_cumulative_net_t_co2"].items():
        per_ha = next(r for r in af["per_hectare"] if r["growth_model"] == model)
        assert total[0] == pytest.approx(per_ha["cumulative_net_t_co2_ha"][0] * 10)
        assert per_ha["productivity_source"].startswith("a priori")


def test_calibrate_and_validate(server):
    c = ok(server, "calibrate_site", {"landscape": "thetford", "fit_end_year": 2017,
                                      "n_sample": 200})
    assert [r["growth_model"] for r in c["results"]] == ["yield_curve", "3pg"]
    assert all(r["holdout"]["n"] > 0 for r in c["results"])
    assert all(r["species"] == "CP" and r["n_age_known"] > 0 for r in c["results"])
    assert c["results"][0]["fe_yield_class_check"]["n"] > 0
    assert c["results"][1]["fe_yield_class_check"] is None
    v = ok(server, "validate")
    assert {"thetford/CP", "kielder/SS", "kielder/NS"} <= set(v["better_model"])
    assert len(v["rows"]) == 2 * (8 + 7)
    one = ok(server, "validate", {"landscapes": ["kielder"], "species": "LP"})
    assert len(one["rows"]) == 2 and one["rows"][0]["holdout_free_age"]["n"] > 0


def test_learning_is_per_site(server):
    area = {"point": [-2.55, 55.2], "radius_m": 300}
    a = ok(server, "assimilate_agb", {"landscape": "kielder", "site": "plotA",
                                      "growth_model": "yield_curve", "area": area})
    r = a["results"][0]
    assert r["persisted"] and r["posterior_productivity_sd"] > 0
    pa = ok(server, "get_parameters", {"landscape": "kielder", "site": "plotA"})
    yc = next(p for p in pa["parameters"] if p["growth_model"] == "yield_curve" and p["species"] == "SS")
    ns = next(p for p in pa["parameters"] if p["growth_model"] == "yield_curve" and p["species"] == "NS")
    assert ns["source"].startswith("calibrated")
    assert yc["source"].startswith("learned")
    assert yc["productivity"] == pytest.approx(r["posterior_productivity"])
    other = ok(server, "get_parameters", {"landscape": "kielder", "site": "plotB"})
    assert all(p["source"].startswith("calibrated") for p in other["parameters"])
    reset = ok(server, "reset_parameters", {"landscape": "kielder", "site": "plotA"})
    assert all(p["source"].startswith("calibrated") for p in reset["parameters"])


def test_assimilate_supplied_observations_without_persisting(server):
    obs = [{"year": 2018 + i, "agb_mg_ha": 60 + 8 * i, "sd_mg_ha": 10} for i in range(6)]
    a = ok(server, "assimilate_agb", {"landscape": "kielder", "site": "mine", "growth_model": "3pg",
                                      "observations": obs, "persist": False})
    assert a["results"][0]["data"] == "6 supplied AGB observations"
    p = ok(server, "get_parameters", {"landscape": "kielder", "site": "mine"})
    assert all(x["source"].startswith("calibrated") for x in p["parameters"])


@pytest.mark.parametrize("model", ["yield_curve", "3pg"])
def test_self_learning(server, model):
    s = ok(server, "self_learn_synthetic", {"growth_model": model})
    assert s["abs_error_after"] < 0.25 * s["abs_error_before"]


@pytest.mark.parametrize("name,args", [
    ("get_agb", {"landscape": "kielder", "year": 2013}),            # no CCI map
    ("get_agb", {"landscape": "dartmoor", "year": 2020}),           # unknown landscape
    ("get_agb", {"landscape": "kielder", "year": 2020, "area": {"point": [-4.0, 50.0]}}),
    ("biomass_change", {"landscape": "kielder", "year1": 2020, "year2": 2016}),
    ("simulate_stand", {"landscape": "kielder", "age": -5}),
    ("simulate_stand", {"landscape": "kielder", "age": 20, "fertility_rating": 1.5}),
    ("management_scenario", {"landscape": "kielder", "regimes": ["burn_it_all"]}),
    ("attribute_change", {"landscape": "kielder", "year1": 2015, "year2": 2020,
                          "evidence": [{"pressure": "aliens", "year_from": 2015, "year_to": 2020,
                                        "bbox": [0, 0, 1, 1]}]}),
])
def test_bad_inputs_are_tool_errors(server, name, args):
    assert call(server, name, args).is_error


def test_stdio_state_survives_restart(tmp_path):
    state = tmp_path / "dt4_state.json"
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)],
                                   env={**os.environ, "DT4_STATE_FILE": str(state)})
    obs = [{"year": 2015 + i, "agb_mg_ha": 50 + 10 * i, "sd_mg_ha": 8} for i in range(8)]
    learned = call(params, "assimilate_agb", {"landscape": "kielder", "site": "restart",
                                              "growth_model": "yield_curve",
                                              "observations": obs}).structured_content
    theta = learned["results"][0]["posterior_productivity"]
    assert json.loads(state.read_text())["sites"]["restart"]["yield_curve/SS"]["params"]["theta"] == theta
    again = call(params, "get_parameters", {"landscape": "kielder", "site": "restart",
                                            "species": "SS"}).structured_content
    yc = next(p for p in again["parameters"] if p["growth_model"] == "yield_curve")
    assert yc["productivity"] == pytest.approx(theta) and yc["source"].startswith("learned")
