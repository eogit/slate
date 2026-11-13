"""End-to-end tests of the DT8 agent as an orchestrator sees it: run with `pytest dt8_agent`.

One orchestrator query, "what are the greenhouse-gas emissions of a potato field on drained peat,
and what if the water table were raised to 30 cm with less fertiliser?", is sent to the DT8 MCP
server over every transport an orchestrator might use:

* the MCP Python client, in memory, over stdio (server launched as a subprocess) and over
  streamable HTTP (server launched with --http);
* raw JSON-RPC 2.0 messages, with no MCP client library, over stdio and over HTTP.

Each answer must contain all three greenhouse gases, in their own units and in CO2e, and must
equal what the peatland model gives when it is run directly with the same inputs. The default
(drained) answer is also checked against the numbers printed in peatland_digital_twin.ipynb.
"""

import json
import math
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import anyio
import numpy as np
import pytest
from mcp import Client, StdioServerParameters

HERE = Path(__file__).resolve().parent
SERVER = HERE / "dt8_server.py"
sys.path.insert(0, str(HERE))

from peatland import ch4, co2, n2o  # noqa: E402
from peatland.state import baseline  # noqa: E402

DRAINED = {"crop": "Potato"}
SCENARIO = {"crop": "Potato", "mean_wtd_m": 0.30, "fertiliser_n_kg_ha_yr": 100}
GASES = ("nee_tc_ha_yr", "ch4_kg_ha_yr", "n2o_kg_n_ha_yr",
         "co2_t_co2e_ha_yr", "ch4_t_co2e_ha_yr", "n2o_t_co2e_ha_yr", "net_t_co2e_ha_yr")


# --------------------------------------------------------------------------- #
# reference: the peatland model run directly, without the server
# --------------------------------------------------------------------------- #
def reference(crop, mean_wtd_m=None, fertiliser_n_kg_ha_yr=None, years_since_rewetting=3):
    p = baseline()
    cl = co2.climate()
    if mean_wtd_m is None:
        sim = co2.simulate(crop)
        wtd = cl["WTD"]
        ch4_kg = ch4.daily_ch4(p["ch4"], cl["Tsoil"], wtd, sim["LAI"]).mean() * 3.65
        n2o_kg = n2o.annual_n2o(crop, p["n2o"], nfert=fertiliser_n_kg_ha_yr)
    else:
        wtd = ch4.water_table(mean_wtd_m)
        sim = co2.simulate(crop, WTD=np.maximum(wtd, 0.02), waterlogging=True)
        ch4_kg = ch4.daily_ch4(p["ch4"], cl["Tsoil"], wtd, sim["LAI"]).mean() * 3.65
        ch4_kg += ch4.litter_annual(p["ch4"], ch4.LITTER, cl["Tsoil"], wtd, sim["LAI"],
                                    years_since_rewetting)[0]
        n2o_kg = n2o.annual_n2o_drivers(crop, p["n2o"], cl["Tsoil"], wtd, sim["Rh"],
                                        fertiliser_n_kg_ha_yr)
    nee = sim["NEE"].mean() * 3.65                      # g C m-2 d-1 -> t C ha-1 yr-1
    e = dict(nee_tc_ha_yr=nee, ch4_kg_ha_yr=ch4_kg, n2o_kg_n_ha_yr=n2o_kg,
             co2_t_co2e_ha_yr=nee * 44 / 12,
             ch4_t_co2e_ha_yr=ch4_kg * 27 / 1000,      # AR6 GWP100 CH4 (non-fossil)
             n2o_t_co2e_ha_yr=n2o_kg * 44 / 28 * 273 / 1000)   # N2O-N -> N2O, GWP100 273
    e["net_t_co2e_ha_yr"] = e["co2_t_co2e_ha_yr"] + e["ch4_t_co2e_ha_yr"] + e["n2o_t_co2e_ha_yr"]
    return e


def check_answer(answer, query):
    """All three gases present, finite, consistent, and equal to the direct model run."""
    for k in GASES:
        assert k in answer and math.isfinite(answer[k]), k
    expected = reference(**query)
    for k in GASES:
        assert answer[k] == pytest.approx(expected[k], rel=1e-9, abs=1e-12), k
    assert answer["net_t_co2e_ha_yr"] == pytest.approx(
        answer["co2_t_co2e_ha_yr"] + answer["ch4_t_co2e_ha_yr"] + answer["n2o_t_co2e_ha_yr"])
    prov = answer["provenance"]["parameters"]
    assert all(g in prov for g in ("co2:", "ch4:", "n2o:"))


def check_pair(drained, scenario):
    check_answer(drained, DRAINED)
    check_answer(scenario, SCENARIO)
    # notebook (Section 5): Potato CO2 29.8, N2O 7.2, CH4 -0.03, net 37.0 t CO2e/ha/yr
    assert drained["co2_t_co2e_ha_yr"] == pytest.approx(29.8, abs=0.05)
    assert drained["n2o_t_co2e_ha_yr"] == pytest.approx(7.2, abs=0.05)
    assert drained["ch4_t_co2e_ha_yr"] == pytest.approx(-0.03, abs=0.005)
    assert drained["net_t_co2e_ha_yr"] == pytest.approx(37.0, abs=0.05)
    # raising the water table: less peat oxidation and N2O, more CH4
    assert scenario["co2_t_co2e_ha_yr"] < drained["co2_t_co2e_ha_yr"]
    assert scenario["n2o_kg_n_ha_yr"] < drained["n2o_kg_n_ha_yr"]
    assert scenario["ch4_kg_ha_yr"] > drained["ch4_kg_ha_yr"]
    assert scenario["fertiliser_n_kg_ha_yr"] == 100


# --------------------------------------------------------------------------- #
# MCP client transports
# --------------------------------------------------------------------------- #
async def _orchestrate(target):
    async with Client(target) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        schema = tools["ghg_balance"].input_schema["properties"]
        assert {"crop", "mean_wtd_m", "fertiliser_n_kg_ha_yr"} <= set(schema)
        a = await client.call_tool("ghg_balance", DRAINED)
        b = await client.call_tool("ghg_balance", SCENARIO)
        assert not a.is_error and not b.is_error
        # the text content is the same answer as JSON, for clients that ignore structured output
        assert json.loads(b.content[0].text)["net_t_co2e_ha_yr"] == pytest.approx(
            b.structured_content["net_t_co2e_ha_yr"])
        return a.structured_content, b.structured_content


def test_query_in_memory():
    import dt8_server

    check_pair(*anyio.run(_orchestrate, dt8_server.server))


def test_query_over_stdio():
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    check_pair(*anyio.run(_orchestrate, params))


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def http_server():
    port = _free_port()
    proc = subprocess.Popen([sys.executable, str(SERVER), "--http"],
                            env={**os.environ, "DT8_PORT": str(port)},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        pytest.fail("DT8 HTTP server did not start")
    yield f"http://127.0.0.1:{port}/mcp"
    proc.terminate()
    proc.wait(timeout=10)


def test_query_over_http(http_server):
    check_pair(*anyio.run(_orchestrate, http_server))


# --------------------------------------------------------------------------- #
# raw JSON-RPC 2.0, no MCP client library
# --------------------------------------------------------------------------- #
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "raw-orchestrator", "version": "0"}}}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}


def _call(i, args):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call",
            "params": {"name": "ghg_balance", "arguments": args}}


def test_raw_jsonrpc_over_stdio():
    proc = subprocess.Popen([sys.executable, str(SERVER)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        def send(msg):
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()

        def receive(i):
            while True:
                msg = json.loads(proc.stdout.readline())
                if msg.get("id") == i:
                    return msg

        send(INIT)
        init = receive(1)["result"]
        assert init["serverInfo"]["name"] == "dt8"
        send(INITIALIZED)
        send(_call(2, DRAINED))
        send(_call(3, SCENARIO))
        a, b = receive(2)["result"], receive(3)["result"]
        assert not a.get("isError") and not b.get("isError")
        check_pair(a["structuredContent"], b["structuredContent"])
        send(_call(4, {"crop": "Potato", "mean_wtd_m": 9}))      # outside the valid range
        assert receive(4)["result"]["isError"]
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


def _post(url, msg, session=None):
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream",
               "MCP-Protocol-Version": "2025-06-18"}
    if session:
        headers["Mcp-Session-Id"] = session
    req = urllib.request.Request(url, json.dumps(msg).encode(), headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode()
        sid = resp.headers.get("Mcp-Session-Id", session)
    if not body.strip():
        return None, sid
    if body.lstrip().startswith("{"):
        return json.loads(body), sid
    data = [ln[5:].strip() for ln in body.splitlines() if ln.startswith("data:")]
    msgs = [json.loads(d) for d in data if d]
    return next(m for m in msgs if m.get("id") == msg.get("id")), sid


def test_raw_jsonrpc_over_http(http_server):
    init, sid = _post(http_server, INIT)
    assert init["result"]["serverInfo"]["name"] == "dt8"
    _post(http_server, INITIALIZED, sid)
    a, _ = _post(http_server, _call(2, DRAINED), sid)
    b, _ = _post(http_server, _call(3, SCENARIO), sid)
    check_pair(a["result"]["structuredContent"], b["result"]["structuredContent"])
