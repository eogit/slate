"""Tests for the persona demo: run with `pytest demo`.

No language model is involved. A scripted MCP client drives the bridge server the way the
headless orchestrator does, against the real twin servers, and the helpers that check a run
are tested on their own.
"""

import json
import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import Client, StdioServerParameters

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import persona_demo as pd  # noqa: E402
from questions import QUESTIONS  # noqa: E402


def test_every_persona_has_a_multi_twin_question():
    assert set(QUESTIONS) == set(pd.per.PERSONA_IDS)
    for q in QUESTIONS.values():
        assert len(q["twins"]) >= 2 and q["question"] and q["why"]


def test_trace_numbers():
    values = [37.04, 0.6403, 1293.2, 2021.0]
    found, other = pd.trace_numbers("37.0 t, 640 kg, 1,293 t, 2021, 3 farms, 55.5 t", values)
    assert found == ["37.0", "640", "1,293"]
    assert other == ["55.5"]


def test_bridge_end_to_end(tmp_path):
    env = dict(os.environ, SLATE_OUT=str(tmp_path), SLATE_PERSONA="farmer",
               SLATE_QUESTION="What do my potatoes on peat emit?")
    params = StdioServerParameters(command=sys.executable,
                                   args=[str(HERE / "slate_bridge_server.py")], env=env)

    async def go():
        async with Client(params) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert {"set_persona", "record_assumptions", "write_report",
                    "dt8__ghg_balance"} <= names
            r = await c.call_tool("dt8__ghg_balance", {"crop": "Potato"})
            assert r.is_error and "record_assumptions" in r.content[0].text
            r = await c.call_tool("set_persona", {"persona": "ngo", "rationale": "x"})
            assert r.is_error and "fixed" in r.content[0].text
            await c.call_tool("record_assumptions", {"assumptions": [
                {"topic": "Crop", "assumption": "Potato", "rationale": "asked"}]})
            r = await c.call_tool("dt8__ghg_balance", {"crop": "Potato"})
            assert not r.is_error and r.content[0].text.startswith("[R1]")
            net = json.loads(r.content[0].text[5:])["net_t_co2e_ha_yr"]
            r = await c.call_tool("write_report", {
                "title": "Potatoes on peat", "audience": "a farmer",
                "question_as_understood": "x", "key_findings": [f"Net {net:.1f} t CO2e/ha/yr [R1]"],
                "results_markdown": "r", "interpretation_markdown": "i", "caveats": []})
            assert r.is_error and "persona_section_markdown" in r.content[0].text
            r = await c.call_tool("write_report", {
                "title": "Potatoes on peat", "audience": "a farmer",
                "question_as_understood": "x", "key_findings": [f"Net {net:.1f} t CO2e/ha/yr [R1]"],
                "results_markdown": "r", "interpretation_markdown": "i", "caveats": [],
                "persona_section_markdown": "Talk to your landlord."})
            assert not r.is_error

    anyio.run(go)
    log = json.loads((tmp_path / "run_log.json").read_text())
    assert log["persona"] == "farmer" and log["persona_fixed"]
    assert [c["tool"] for c in log["calls"]] == ["ghg_balance"]
    md = Path(log["report_markdown"]).read_text()
    assert "What this could mean for your farm" in md and "ghg_balance" in md
    c = pd.check("farmer", {"twins": ["dt8"]}, tmp_path, {})
    assert c["report"] and c["persona_section"] and not c["multi_twin"]
    assert c["key_finding_numbers_traced"] == 1
