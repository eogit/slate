"""Tests for the SLATE orchestrator: run with `pytest orchestrator`.

The language model is replaced by a scripted stand-in that issues the tool calls a real model
would, so the tests need no API key and are deterministic. Everything else is real: the
digital-twin agents are launched as MCP servers over stdio, their results flow back through
the orchestrator, figures are drawn and the report is rendered.

`test_live_claude` runs the real model and is skipped unless ANTHROPIC_API_KEY is set.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from agent_pool import AgentPool, load_registry  # noqa: E402
from orchestrator import LOCAL_TOOLS, Orchestrator, no_answer  # noqa: E402
from prompts import system_prompt  # noqa: E402

QUESTION = ("I'm with an NGO. How much methane do the cattle and sheep around Crewe emit, "
            "and how much would anaerobic digestion of slurry and a smaller dairy herd save?")


def tool_use(i, name, args):
    return SimpleNamespace(type="tool_use", id=f"tu{i}", name=name, input=args)


def text(t):
    return SimpleNamespace(type="text", text=t)


def msg(*blocks, stop="tool_use"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=100, output_tokens=50))


def last_results(messages):
    """tool_result contents of the last user message, by tool_use_id."""
    return {r["tool_use_id"]: r for r in messages[-1]["content"]}


def payload(result):
    """The JSON after the [R#] tag of a tool result."""
    return json.loads(result["content"].split("] ", 1)[1])


class ScriptedClaude:
    """Stands in for AsyncAnthropic: each step sees the conversation and returns a message."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        self.requests.append(kw)
        return self.steps.pop(0)(kw["messages"])


CREWE = {"lat": 53.10, "lon": -2.44, "radius_km": 15}


def script(state):
    steps = [
        # 1. one follow-up question
        lambda m: msg(tool_use(1, "ask_user", {"questions": [{
            "question": "How far around Crewe should I look?",
            "why_it_matters": "the total scales with the area",
            "default_assumption": "10 km radius"}]})),
        # 2. an agent call before stating assumptions is refused
        lambda m: msg(tool_use(2, "dt2__area_methane", {"area": CREWE})),
        # 3. assumptions, then the calls in parallel
        lambda m: (state.update(gate=last_results(m)["tu2"]), msg(tool_use(
            30, "set_persona", {"persona": "ngo", "rationale": "the user is with an NGO"}),
            tool_use(3, "record_assumptions", {
            "assumptions": [
                {"topic": "Area", "assumption": "15 km radius around Crewe (53.10 N, 2.44 W)",
                 "rationale": "the user's answer"},
                {"topic": "Scenario", "assumption": "dairy herd -20 %, half of housed cattle "
                 "manure to anaerobic digestion", "rationale": "the question names both "
                 "measures without sizes; 20 % and 50 % are plausible policy-scale changes"}]})))[1],
        lambda m: msg(
            tool_use(4, "dt2__methane_scenario", {"area": CREWE, "interventions": {
                "herd_change_pct": {"dairy": -20}, "ad_pct_of_housed": 50}}),
            tool_use(5, "dt2__methane_hotspots", {"area": CREWE, "n": 5}),
            tool_use(6, "dt2__area_methane", {"area": {"lat": 0, "lon": 0}})),   # invalid
        # 4. figures from the returned numbers
        lambda m: (state.update(res=last_results(m)), msg(
            tool_use(7, "make_figure", {
                "kind": "bar", "title": "Livestock methane around Crewe",
                "caption": "Baseline and scenario by livestock group [R1].",
                "categories": ["dairy", "beef_other", "sheep"],
                "series": {g: [payload(state["res"]["tu4"])[g]["groups"][c]["total_t_ch4"]
                               for c in ("dairy", "beef_other", "sheep")]
                           for g in ("baseline", "scenario")},
                "ylabel": "t CH4 per year"}),
            tool_use(8, "make_figure", {
                "kind": "map", "title": "Methane hotspots", "caption": "Top cells [R2].",
                "points": [{"lat": c["lat"], "lon": c["lon"], "value": c["total_t_ch4"]}
                           for c in payload(state["res"]["tu5"])["cells"]],
                "value_label": "t CH4 per km2 per year"})))[1],
        # 5. a second question round, then more than allowed
        lambda m: msg(tool_use(9, "ask_user", {"questions": [{
            "question": "Is a 20 % herd reduction realistic for you?",
            "default_assumption": "yes"}]})),
        lambda m: msg(tool_use(10, "ask_user", {"questions": [{
            "question": "Anything else?", "default_assumption": "no"}]})),
        # 6. the report
        lambda m: (state.update(third_ask=last_results(m)["tu10"]), msg(tool_use(11, "write_report", {
            "title": "Livestock methane around Crewe",
            "audience": "an NGO",
            "question_as_understood": "Methane from livestock within 15 km of Crewe and the "
                                      "effect of digestion and a smaller dairy herd.",
            "key_findings": ["Scenario lowers methane [R1]."],
            "results_markdown": "Numbers from [R1] and [R2].",
            "interpretation_markdown": "Dairy dominates.",
            "persona_section_markdown": "The scenario quantifies methane only; habitat "
                                        "and species effects were not modelled.",
            "caveats": ["Dairy share is England's average."],
            "figure_ids": ["1", "2"]})))[1],
        lambda m: msg(text("Done."), stop="end_turn"),
    ]
    return steps


@pytest.fixture(scope="module")
def run_result(tmp_path_factory):
    out = tmp_path_factory.mktemp("reports")
    state = {}
    claude = ScriptedClaude(script(state))
    asked = []

    def ask(questions):
        asked.append(questions)
        return ["15 km"] if len(asked) == 1 else [""]

    async def go():
        async with AgentPool() as pool:
            orch = Orchestrator(claude, pool, ask=ask, out_dir=out, log=lambda s: None)
            return await orch.run(QUESTION), pool

    result, pool = asyncio.run(go())
    return SimpleNamespace(result=result, pool=pool, claude=claude, state=state, asked=asked,
                           out=out)


def test_agents_discovered(run_result):
    pool = run_result.pool
    assert {"dt2", "dt8"} <= set(pool.agents)
    for missing in {"dt4", "dt6"} - set(pool.agents):
        assert missing in pool.skipped         # forest agents arrive with their own PR
    names = {t["name"] for t in pool.tool_definitions()}
    assert {"dt2__area_methane", "dt2__methane_scenario", "dt8__ghg_balance"} <= names
    sp = system_prompt(pool.agents, pool.skipped)
    assert "DT2 livestock methane" in sp and "dt8__" in sp and "record_assumptions" in sp


def test_request_shape(run_result):
    kw = run_result.claude.requests[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["fallbacks"] == "default"
    assert [t["name"] for t in kw["tools"][:len(LOCAL_TOOLS)]] == [t["name"] for t in LOCAL_TOOLS]
    # tools and system prompt identical on every turn (prompt caching)
    assert all(r["tools"] == kw["tools"] and r["system"] == kw["system"]
               for r in run_result.claude.requests)


def test_follow_up_questions_and_limits(run_result):
    r = run_result.result
    assert r.clarifications[0] == {"question": "How far around Crewe should I look?",
                                   "answer": "15 km"}
    assert r.clarifications[1]["answer"].startswith("no answer; default assumed")
    assert len(run_result.asked) == 2                      # third round was refused
    assert "No more follow-up questions" in run_result.state["third_ask"]["content"]


def test_assumptions_are_required_before_agent_calls(run_result):
    gate = run_result.state["gate"]
    assert gate.get("is_error") and "record_assumptions" in gate["content"]
    assert "set_persona" in gate["content"]
    assert run_result.result.persona == "ngo" and not run_result.result.persona_fixed
    assert [a["topic"] for a in run_result.result.assumptions] == ["Area", "Scenario"]
    assert all(c.assumptions == ["Area", "Scenario"] for c in run_result.result.calls)


def test_agent_results_flow_back(run_result):
    calls = run_result.result.calls
    assert [c.ref for c in calls] == ["R1", "R2", "R3"]
    scen = calls[0].result
    assert calls[0].ok and scen["change_t_ch4"] < 0
    assert calls[1].ok and len(calls[1].result["cells"]) == 5
    assert not calls[2].ok                                  # invalid area reported, not raised
    assert run_result.state["res"]["tu6"]["is_error"]


def test_report(run_result):
    r = run_result.result
    assert r.stop == "done" and r.html_path.exists() and r.markdown_path.exists()
    md = r.markdown
    for section in ("## Key findings", "## Results", "## What this means", "## Caveats",
                    "**Follow-up questions**", "**Assumptions made before calling the agents**",
                    "**Agent calls**", "**Data and models (as reported by the agents)**"):
        assert section in md, section
    assert "| R1 | DT2 livestock methane | `methane_scenario` |" in md
    assert "zenodo.13734518" in md                          # provenance comes from the agent
    assert "15 km radius around Crewe" in md
    assert "## Nature recovery and advocacy relevance" in md        # NGO persona section
    assert "do not assess species, habitat condition" in md          # NGO persona caveat
    page = r.html_path.read_text()
    assert page.count("data:image/png;base64,") == 2        # both figures embedded
    assert "<table>" in page
    assert len(r.figures) == 2 and all(f.path.stat().st_size > 10_000 for f in r.figures.values())


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
def test_live_claude(tmp_path):
    import anthropic

    async def go():
        async with AgentPool() as pool:
            orch = Orchestrator(anthropic.AsyncAnthropic(), pool, ask=no_answer,
                                out_dir=tmp_path, log=lambda s: None)
            return await orch.run("What would cutting the dairy herd by 10 % around Nantwich "
                                  "do to methane emissions?")

    r = asyncio.run(go())
    assert r.stop == "done" and r.assumptions_recorded and r.calls
    assert any(c.agent == "dt2" for c in r.calls)
