"""End-to-end tests of the DT6 agent as an orchestrator sees it: run with ``pytest dt6_agent``.

One orchestrator query with input parameters, "for the Cheshire pilot, how much carbon is
held in trees outside woodland now, and how much would ash dieback (30 % of broadleaves are
ash) cost over the next 30 years, by both growth models?", is sent to the DT6 MCP server over
every transport an orchestrator might use:

* the MCP Python client, in memory, over stdio (server launched as a subprocess) and over
  streamable HTTP (server launched with --http);
* raw JSON-RPC 2.0 messages, with no MCP client library, over stdio and over HTTP.

The query is two tool calls: ``carbon_stock`` (state) and ``ash_dieback_scenario``
(response). Every answer must equal what the ``trees`` package gives when it is run directly
with the same inputs: the inventory and allometry for the stock, and the scenario engine with
each crown's calibrated productivity for the baseline and dieback runs.
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
SERVER = HERE / "dt6_server.py"
sys.path.insert(0, str(HERE))

from trees import allometry, inventory, scenario, state  # noqa: E402

AREA = {"bbox": [-2.88, 53.19, -2.85, 53.21]}
STOCK_QUERY = {"pilot": "cheshire", "area": AREA}
ASH_QUERY = {"pilot": "cheshire", "area": AREA, "growth_model": "both", "ash_share": 0.3,
             "years": 30, "n_members": 10, "seed": 5}


# --------------------------------------------------------------------------- #
# reference: the trees package run directly, without the server
# --------------------------------------------------------------------------- #
def _mask(inv):
    w, s, e, n = AREA["bbox"]
    return (inv.lon >= w) & (inv.lon <= e) & (inv.lat >= s) & (inv.lat <= n)


def reference_stock():
    inv = inventory.load("cheshire")
    m = _mask(inv)
    agb = float((inv.n_trees[m] * allometry.agb_kg(inv.height_m[m], inv.crown_diam_m[m],
                                                   inv.p_conifer)).sum() / 1000)
    agc, bgc = allometry.living_carbon_t(agb * 1000)
    return {"objects": int(m.sum()), "agb_t": agb, "total_living_c_t": agc + bgc}


def reference_ash():
    out = {}
    for name in ("size_age", "crown_lue"):
        _, inv, fit, _ = state.crown_fit("cheshire", name)
        m = _mask(inv)
        sub = inv.select(m)
        sub_fit = type(fit)(**{k: v[m] for k, v in fit.as_dict().items()})
        bank = state.height_bank("cheshire", name)
        kw = dict(start_year=2025, years=30, n_members=10, seed=5)
        base = scenario.simulate(bank, sub, sub_fit, **kw)
        ash = scenario.simulate(bank, sub, sub_fit, ash={"ash_share": 0.3, "m_max": 0.8,
                                                         "tau_years": 10.0}, **kw)
        out[name] = (base, ash)
    return out


REF_STOCK = reference_stock()
REF_ASH = reference_ash()


def check_stock(answer):
    assert answer["objects"] == REF_STOCK["objects"] > 50
    assert answer["agb_t"] == pytest.approx(REF_STOCK["agb_t"], rel=1e-12)
    assert answer["total_living_c_t"] == pytest.approx(REF_STOCK["total_living_c_t"], rel=1e-12)
    assert answer["ebcf_role"] == "state"
    assert "LIDAR" in answer["provenance"]["observations"]


def check_ash(answer):
    runs = answer["runs"]
    assert [r["growth_model"] for r in runs] == ["size_age", "size_age", "crown_lue", "crown_lue"]
    for i, name in enumerate(("size_age", "crown_lue")):
        base, ash = REF_ASH[name]
        rb, ra = runs[2 * i], runs[2 * i + 1]
        for run, ref in ((rb, base), (ra, ash)):
            assert run["cumulative_net_t_co2"][0] == pytest.approx(
                round(ref["cumulative_net_t_co2"]["mean"][-1], 3), abs=1e-9)
            assert run["living_c_t"]["mean"][-1] == pytest.approx(
                round(ref["living_c_t"]["mean"][-1], 3), abs=1e-9)
        assert ra["living_c_t"]["mean"][-1] < rb["living_c_t"]["mean"][-1]
    assert answer["ebcf_role"] == "response"


def check_pair(stock, ash):
    check_stock(stock)
    check_ash(ash)


# --------------------------------------------------------------------------- #
# MCP client transports
# --------------------------------------------------------------------------- #
async def _orchestrate(target):
    async with Client(target) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert {"pilot", "ash_share", "years"} <= set(
            tools["ash_dieback_scenario"].input_schema["properties"])
        a = await client.call_tool("carbon_stock", STOCK_QUERY)
        b = await client.call_tool("ash_dieback_scenario", ASH_QUERY)
        assert not a.is_error and not b.is_error
        assert json.loads(a.content[0].text)["agb_t"] == pytest.approx(
            a.structured_content["agb_t"])
        return a.structured_content, b.structured_content


def test_query_in_memory():
    import dt6_server

    check_pair(*anyio.run(_orchestrate, dt6_server.server))


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
                            env={**os.environ, "DT6_PORT": str(port)},
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
        pytest.fail("DT6 HTTP server did not start")
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
        assert receive(1)["result"]["serverInfo"]["name"] == "dt6"
        send(INITIALIZED)
        send(_call(2, "carbon_stock", STOCK_QUERY))
        send(_call(3, "ash_dieback_scenario", ASH_QUERY))
        a, b = receive(2)["result"], receive(3)["result"]
        assert not a.get("isError") and not b.get("isError")
        check_pair(a["structuredContent"], b["structuredContent"])
        send(_call(4, "carbon_stock", {"pilot": "cheshire", "area": {"bbox": [0, 0, 1, 1]}}))
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
    assert init["result"]["serverInfo"]["name"] == "dt6"
    _post(http_server, INITIALIZED, sid)
    a, _ = _post(http_server, _call(2, "carbon_stock", STOCK_QUERY), sid)
    b, _ = _post(http_server, _call(3, "ash_dieback_scenario", ASH_QUERY), sid)
    check_pair(a["result"]["structuredContent"], b["result"]["structuredContent"])
