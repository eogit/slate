"""Tests for the DT8 MCP server: run with `pytest dt8_agent`."""

import json
import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import Client, StdioServerParameters

SERVER = Path(__file__).with_name("dt8_server.py")
TOOLS = {"list_crops", "simulate_co2", "annual_ch4", "annual_n2o", "ghg_balance",
         "water_table_scenario", "validate_inventory", "get_parameters", "reset_parameters",
         "self_learn_synthetic", "assimilate_ch4", "run_ch4_drivers"}


@pytest.fixture(scope="module")
def server():
    sys.path.insert(0, str(SERVER.parent))
    import dt8_server

    return dt8_server.server


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


def test_list_crops(server):
    r = call(server, "list_crops")
    assert not r.is_error
    codes = [c["code"] for c in r.structured_content["crops"]]
    assert codes[:2] == ["WW", "Beet"] and len(codes) == 10
    veg = {v["code"]: v for v in r.structured_content["ch4_vegetation"]}
    assert len(veg) == 15 and not veg["reed"]["flood_intolerant"]
    assert veg["Grass_ungrazed"]["flood_intolerant"]


def test_simulate_co2(server):
    r = call(server, "simulate_co2", {"crop": "Potato", "include_daily": True})
    s = r.structured_content
    assert s["nee_tc_ha_yr"] == pytest.approx(8.1, abs=0.05)
    assert s["reco_tc_ha_yr"] == pytest.approx(s["ra_tc_ha_yr"] + s["rh_tc_ha_yr"])
    assert len(s["daily_g_c_m2_d"]["nee"]) == 365
    assert "calibrated baseline" in s["provenance"]["parameters"]
    wetter = call(server, "simulate_co2", {"crop": "Potato", "mean_wtd_m": 0.2}).structured_content
    assert wetter["nee_tc_ha_yr"] < s["nee_tc_ha_yr"]       # rewetting cuts peat oxidation


def test_annual_ch4_and_n2o(server):
    wet = call(server, "annual_ch4", {"mean_wtd_m": 0.1}).structured_content
    dry = call(server, "annual_ch4", {"mean_wtd_m": 0.7}).structured_content
    assert wet["ch4_kg_ha_yr"] == pytest.approx(132.8, abs=0.05)
    assert wet["ch4_litter_kg_ha_yr"] == 0.0                  # reed is flood tolerant
    assert dry["ch4_kg_ha_yr"] < 0 < wet["ch4_kg_ha_yr"]
    n = call(server, "annual_n2o", {"crop": "Celery"}).structured_content
    assert n["n2o_kg_n_ha_yr"] == pytest.approx(23.7, abs=0.05)
    less = call(server, "annual_n2o",
                {"crop": "Celery", "fertiliser_n_kg_ha_yr": 0}).structured_content
    assert less["n2o_kg_n_ha_yr"] < n["n2o_kg_n_ha_yr"]


def test_ghg_balance_matches_notebook(server):
    s = call(server, "ghg_balance", {"crop": "WW"}).structured_content
    assert s["co2_t_co2e_ha_yr"] == pytest.approx(33.1, abs=0.05)
    assert s["n2o_t_co2e_ha_yr"] == pytest.approx(4.3, abs=0.05)
    assert s["net_t_co2e_ha_yr"] == pytest.approx(37.3, abs=0.05)


def test_water_table_scenario(server):
    s = call(server, "water_table_scenario").structured_content
    assert s["evidence_role"].startswith("response")
    assert len(s["points"]) == 45
    assert s["optimum_wtd_m"] == pytest.approx(0.14, abs=0.01)    # notebook: optimum ~0.14 m


def test_validate_inventory(server):
    s = call(server, "validate_inventory").structured_content
    assert s["n2o_cropland_model_kg_n"] == pytest.approx(16.28, abs=0.01)
    assert s["ch4_rewetted_model_kg"] == pytest.approx(109, abs=0.5)
    assert len(s["water_table_profile"]) == 8


def test_bad_arguments_are_rejected(server):
    assert call(server, "annual_ch4", {"mean_wtd_m": 5}).is_error
    assert call(server, "simulate_co2", {"crop": "Banana"}).is_error
    assert call(server, "get_parameters", {"site": "../etc"}).is_error


def test_learning_is_per_site(server):
    site = "test-site-learn"
    r = call(server, "self_learn_synthetic",
             {"gas": "ch4", "epochs": 2, "persist": True, "site": site}).structured_content
    assert r["persisted"]
    p = call(server, "get_parameters", {"site": site}).structured_content
    assert p["ch4"]["k_prod"] == pytest.approx(r["learned"]["k_prod"])
    assert p["sources"]["ch4"].startswith("learned")
    default = call(server, "get_parameters").structured_content
    assert default["sources"]["ch4"] == "calibrated baseline"
    reset = call(server, "reset_parameters", {"site": site}).structured_content
    assert reset["sources"]["ch4"] == "calibrated baseline"


def test_assimilate_ch4(server):
    obs = [{"tsoil_c": 15.0, "wtd_m": 0.1, "lai": 3.0, "ch4_mg_m2_d": 30.0}] * 50
    r = call(server, "assimilate_ch4",
             {"observations": obs, "epochs": 2, "site": "test-assim"}).structured_content
    assert r["learned"]["k_prod"] != r["prior"]["k_prod"]
    call(server, "reset_parameters", {"site": "test-assim"})


def test_stdio_with_persistent_state(tmp_path):
    state = tmp_path / "dt8_state.json"
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)],
                                   env={**os.environ, "DT8_STATE_FILE": str(state)})

    async def go():
        async with Client(params) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            r = await client.call_tool("self_learn_synthetic",
                                       {"gas": "n2o", "epochs": 1, "persist": True,
                                        "site": "fen1"})
            return names, r

    names, r = anyio.run(go)
    assert names == TOOLS
    assert not r.is_error
    saved = json.loads(state.read_text())["sites"]["fen1"]["n2o"]["params"]
    assert saved["ef_peat"] == pytest.approx(r.structured_content["learned"]["ef_peat"])


def test_annual_ch4_crop_classes_and_litter(server):
    # Section 12 of the CH4 notebook: classes at 11.5 cm (no standing water in summer -> no litter
    # for the drained part of the year; winter water above the surface adds a little for crops)
    g = call(server, "annual_ch4", {"mean_wtd_m": 0.115, "vegetation": "Grass_ungrazed",
                                    "include_flood_litter": False}).structured_content
    assert g["ch4_kg_ha_yr"] == pytest.approx(142.97, abs=0.01)
    flooded = {"mean_wtd_m": 0.0, "vegetation": "Grass_ungrazed"}
    first = call(server, "annual_ch4", {**flooded, "years_since_rewetting": 0}).structured_content
    later = call(server, "annual_ch4", {**flooded, "years_since_rewetting": 1}).structured_content
    assert 0 < first["ch4_litter_kg_ha_yr"] < later["ch4_litter_kg_ha_yr"]   # pool still filling
    assert first["ch4_base_kg_ha_yr"] == pytest.approx(later["ch4_base_kg_ha_yr"])


def test_run_ch4_drivers(server):
    import numpy as np

    doy = np.arange(1, 366)
    wtd = list(np.clip(0.115 + 0.30 * np.clip(np.sin(2 * np.pi * (doy - 172) / 365), 0, None)
                       - 0.10, -0.15, 1.6))
    lai = list(0.8 + 2.7 * np.exp(-0.5 * ((doy - 200) / 70) ** 2))
    ts = list(10.0 + 7.0 * np.sin(2 * np.pi * (doy - 128) / 365))
    r = call(server, "run_ch4_drivers", {"wtd_m": wtd, "lai": lai, "tsoil_c": ts,
                                         "peat_depth_m": 0.35, "soc_pct": 25.0,
                                         "include_daily": True}).structured_content
    assert r["net_kg_ch4_ha_yr"] == pytest.approx(109.28, abs=0.01)   # same as reed at 11.5 cm
    assert r["net_kg_ch4_m2_yr"] == pytest.approx(r["net_kg_ch4_ha_yr"] / 1e4)
    assert r["flag_fractions"]["flag_wasted_peat"] == 1.0
    assert r["flag_fractions"]["flag_low_SOC"] == 0.0
    assert len(r["daily"]["net_nmol_m2_s"]) == 365
    tair = list(10.5 + 6.7 * np.sin(2 * np.pi * (doy - 115) / 365))
    a = call(server, "run_ch4_drivers",
             {"wtd_m": wtd, "lai": lai, "tair_c": tair}).structured_content
    assert a["soil_temperature_source"].startswith("air temperature")
    assert call(server, "run_ch4_drivers", {"wtd_m": wtd, "lai": lai[:100], "tsoil_c": ts}).is_error
    assert call(server, "run_ch4_drivers", {"wtd_m": wtd, "lai": lai}).is_error
