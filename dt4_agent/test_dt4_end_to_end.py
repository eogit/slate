"""End-to-end tests of the DT4 agent as an orchestrator sees it: run with ``pytest dt4_agent``.

One orchestrator query with input parameters, "for Kielder, how much biomass is there now,
and which management regime stores the most carbon over the next 40 years, by both growth
models?", is sent to the DT4 MCP server over every transport an orchestrator might use:

* the MCP Python client, in memory, over stdio (server launched as a subprocess) and over
  streamable HTTP (server launched with --http);
* raw JSON-RPC 2.0 messages, with no MCP client library, over stdio and over HTTP.

The query is two tool calls: ``get_agb`` (state) and ``management_scenario`` (response).
Every answer must equal what the ``forest`` package gives when it is run directly with the
same inputs: the CCI v7 area statistics for the AGB, and the scenario engine with the
calibrated productivity for each regime and growth model.
"""

import json
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
SERVER = HERE / "dt4_server.py"
sys.path.insert(0, str(HERE))

from forest import cci, landscapes, make_model, scenario, state  # noqa: E402

AGB_QUERY = {"landscape": "kielder", "year": 2024}
SCENARIO_QUERY = {"landscape": "kielder", "horizon_years": 40, "n_members": 20, "seed": 7,
                  "regimes": ["no_intervention", "clearfell_no_thin", "continuous_cover"]}


# --------------------------------------------------------------------------- #
# reference: the forest package run directly, without the server
# --------------------------------------------------------------------------- #
def reference_agb():
    cube = cci.load("kielder")
    return cci.area_stats(cube, 2024, cube.woodland)


def reference_scenario():
    ls = landscapes.get("kielder")
    st = reference_agb()
    out = {}
    for m in ("yield_curve", "3pg"):
        b = state.baseline("kielder", m)
        model = make_model(m, ls.species, ls)
        for regime in SCENARIO_QUERY["regimes"]:
            r = scenario.simulate(model, start_year=2024, years=40, age=b["age_median"],
                                  theta=b["theta"], theta_sd=b["theta_sd"],
                                  agb0=st["agb_mean_mg_ha"], agb0_sd=st["agb_sd_mg_ha"],
                                  regime=regime, n_members=20, seed=7)
            cum = r.net_flux_co2[1:].sum(axis=0)
            out[(m, regime)] = {"cum": [cum.mean(), np.percentile(cum, 5), np.percentile(cum, 95)],
                                "removals": r.removals_dm.sum(axis=0).mean(),
                                "final_c": r.total_c[-1].mean()}
    return out


REF_AGB = reference_agb()
REF_SCENARIO = reference_scenario()


def check_agb(answer):
    for k in ("agb_mean_mg_ha", "agb_sd_mg_ha", "area_ha", "n_pixels"):
        assert answer[k] == pytest.approx(REF_AGB[k], rel=1e-12), k
    assert answer["agb_mean_mg_ha"] == pytest.approx(116.7961, abs=1e-3)
    assert answer["ebcf_role"] == "state"
    assert "CCI v7" in answer["provenance"]["observations"]


def check_scenario(answer):
    assert answer["start_agb_mg_ha"] == pytest.approx(REF_AGB["agb_mean_mg_ha"])
    assert len(answer["outcomes"]) == 6
    for o in answer["outcomes"]:
        ref = REF_SCENARIO[(o["growth_model"], o["regime"])]
        assert o["cumulative_net_t_co2_ha"] == pytest.approx([round(v, 3) for v in ref["cum"]],
                                                             abs=1e-9)
        assert o["removals_total_t_dm_ha"] == pytest.approx(round(ref["removals"], 3), abs=1e-9)
        assert o["final_total_c_t_ha"] == pytest.approx(ref["final_c"], rel=1e-9)
    for m in ("yield_curve", "3pg"):
        best = min(SCENARIO_QUERY["regimes"], key=lambda r: REF_SCENARIO[(m, r)]["cum"][0])
        assert answer["best_for_carbon"][m] == best
    assert answer["ebcf_role"] == "response"


def check_pair(agb, scen):
    check_agb(agb)
    check_scenario(scen)


# --------------------------------------------------------------------------- #
# MCP client transports
# --------------------------------------------------------------------------- #
async def _orchestrate(target):
    async with Client(target) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert {"landscape", "regimes", "horizon_years"} <= set(
            tools["management_scenario"].input_schema["properties"])
        a = await client.call_tool("get_agb", AGB_QUERY)
        b = await client.call_tool("management_scenario", SCENARIO_QUERY)
        assert not a.is_error and not b.is_error
        assert json.loads(a.content[0].text)["agb_mean_mg_ha"] == pytest.approx(
            a.structured_content["agb_mean_mg_ha"])
        return a.structured_content, b.structured_content


def test_query_in_memory():
    import dt4_server

    check_pair(*anyio.run(_orchestrate, dt4_server.server))


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
                            env={**os.environ, "DT4_PORT": str(port)},
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
        pytest.fail("DT4 HTTP server did not start")
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


def _call(i, name, args):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call",
            "params": {"name": name, "arguments": args}}


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
        assert receive(1)["result"]["serverInfo"]["name"] == "dt4"
        send(INITIALIZED)
        send(_call(2, "get_agb", AGB_QUERY))
        send(_call(3, "management_scenario", SCENARIO_QUERY))
        a, b = receive(2)["result"], receive(3)["result"]
        assert not a.get("isError") and not b.get("isError")
        check_pair(a["structuredContent"], b["structuredContent"])
        send(_call(4, "get_agb", {"landscape": "kielder", "year": 2013}))   # no 2013 map
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
    with urllib.request.urlopen(req, timeout=60) as resp:
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
    assert init["result"]["serverInfo"]["name"] == "dt4"
    _post(http_server, INITIALIZED, sid)
    a, _ = _post(http_server, _call(2, "get_agb", AGB_QUERY), sid)
    b, _ = _post(http_server, _call(3, "management_scenario", SCENARIO_QUERY), sid)
    check_pair(a["result"]["structuredContent"], b["result"]["structuredContent"])
