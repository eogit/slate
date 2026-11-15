"""End-to-end tests of the DT2 agent as an orchestrator sees it: run with `pytest dt2_agent`.

One orchestrator query, "how much methane do the cattle, sheep and goats within 10 km of Crewe
emit, and what if the dairy herd shrank by 20 % and half the housed cattle manure went to
anaerobic digestion?", is sent to the DT2 MCP server over every transport an orchestrator
might use:

* the MCP Python client, in memory, over stdio (server launched as a subprocess) and over
  streamable HTTP (server launched with --http);
* raw JSON-RPC 2.0 messages, with no MCP client library, over stdio and over HTTP.

Each answer must contain enteric and manure methane for every livestock group, in t CH4 and
t CO2e, and must equal the livestock model run directly with the same inputs.
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
import pytest
from mcp import Client, StdioServerParameters

HERE = Path(__file__).resolve().parent
SERVER = HERE / "dt2_server.py"
sys.path.insert(0, str(HERE))

from livestock import calibration, model  # noqa: E402

AREA = {"lat": 53.10, "lon": -2.44, "radius_km": 10}
INTERVENTIONS = {"herd_change_pct": {"dairy": -20}, "ad_pct_of_housed": 50}
QUERY = {"area": AREA, "interventions": INTERVENTIONS}
GROUPS = ("dairy", "beef_other", "sheep", "goats")


def reference():
    """The model run directly, without the server."""
    cfg = calibration.calibrated_config()
    a = model.Area(**AREA)
    base = model.run(a, cfg)
    sc = model.run(a, cfg, sc=model.Scenario(herd_change_pct={"dairy": -20},
                                             ad_pct_of_housed=50))
    return base, sc


def check_answer(ans):
    base, sc = reference()
    for got, exp in ((ans["baseline"], base), (ans["scenario"], sc)):
        for g in GROUPS:
            for k in ("heads", "enteric_t_ch4", "manure_t_ch4"):
                assert math.isfinite(got["groups"][g][k])
                assert got["groups"][g][k] == pytest.approx(exp["groups"][g][k], rel=1e-9)
        for k in ("total_t_ch4", "t_co2e_ar5", "t_co2e_ar6"):
            assert got[k] == pytest.approx(exp[k], rel=1e-9)
    assert ans["change_t_ch4"] == pytest.approx(sc["total_t_ch4"] - base["total_t_ch4"])
    assert ans["change_t_ch4"] < 0
    assert ans["scenario"]["groups"]["sheep"]["total_t_ch4"] == pytest.approx(
        ans["baseline"]["groups"]["sheep"]["total_t_ch4"])
    assert "zenodo.13734518" in ans["baseline"]["provenance"]["livestock_maps"]
    assert "A 5.1.8" in ans["baseline"]["provenance"]["emission_factors"]


async def _orchestrate(target):
    async with Client(target) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert {"area", "interventions"} <= set(tools["methane_scenario"].input_schema[
            "properties"])
        r = await client.call_tool("methane_scenario", QUERY)
        assert not r.is_error
        assert json.loads(r.content[0].text)["change_t_ch4"] == pytest.approx(
            r.structured_content["change_t_ch4"])
        return r.structured_content


def test_query_in_memory():
    import dt2_server

    check_answer(anyio.run(_orchestrate, dt2_server.server))


def test_query_over_stdio():
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    check_answer(anyio.run(_orchestrate, params))


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def http_server():
    port = _free_port()
    proc = subprocess.Popen([sys.executable, str(SERVER), "--http"],
                            env={**os.environ, "DT2_PORT": str(port)},
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
        pytest.fail("DT2 HTTP server did not start")
    yield f"http://127.0.0.1:{port}/mcp"
    proc.terminate()
    proc.wait(timeout=10)


def test_query_over_http(http_server):
    check_answer(anyio.run(_orchestrate, http_server))


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "raw-orchestrator", "version": "0"}}}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}


def _call(i, args, name="methane_scenario"):
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
        assert receive(1)["result"]["serverInfo"]["name"] == "dt2"
        send(INITIALIZED)
        send(_call(2, QUERY))
        a = receive(2)["result"]
        assert not a.get("isError")
        check_answer(a["structuredContent"])
        send(_call(3, {"area": {"lat": 53.1, "lon": -2.44, "radius_km": 999},
                       "interventions": {}}))          # radius outside the valid range
        assert receive(3)["result"]["isError"]
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
    assert init["result"]["serverInfo"]["name"] == "dt2"
    _post(http_server, INITIALIZED, sid)
    a, _ = _post(http_server, _call(2, QUERY), sid)
    check_answer(a["result"]["structuredContent"])
