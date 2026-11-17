"""Tests for the user personas: run with `pytest orchestrator`.

The profiles are checked for completeness and sources; then each persona is run end to end
with the scripted stand-in for Claude (see test_orchestrator.py) against the real MCP agents,
checking that the persona is selected or fixed, gates agent calls, shapes the follow-up
questions, and adds its section, caveats and context sources to the report.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import personas as per  # noqa: E402
from agent_pool import AgentPool  # noqa: E402
from orchestrator import LOCAL_TOOLS, Orchestrator  # noqa: E402
from prompts import system_prompt  # noqa: E402
from test_orchestrator import ScriptedClaude, last_results, msg, text, tool_use  # noqa: E402


# --------------------------------------------------------------------------- #
# the profiles
# --------------------------------------------------------------------------- #
def test_five_personas_plus_general():
    assert list(per.PERSONAS) == ["policy", "farmer", "finance", "research", "ngo"]
    assert per.PERSONA_IDS == ["policy", "farmer", "finance", "research", "ngo", "general"]
    assert per.get("general") is None
    with pytest.raises(ValueError):
        per.get("banker")


@pytest.mark.parametrize("pid", list(per.PERSONAS))
def test_profiles_are_complete_and_sourced(pid):
    p = per.PERSONAS[pid]
    for name in ("who", "label", "audience", "section_title", "section_brief"):
        assert getattr(p, name).strip(), name
    for name in ("recognise_by", "decisions", "needs", "follow_ups", "framing", "caveats",
                 "context", "sources"):
        assert len(getattr(p, name)) >= 3, name
    for f in p.follow_ups:
        assert f.question.endswith("?") and f.default and f.when
    for _, key in p.context:
        assert key in per.SOURCES, key
    for key in p.sources:
        assert key in per.SOURCES and per.SOURCES[key].url.startswith("https://"), key
    refs = per.sources_markdown(pid)
    assert len(refs) == len(p.sources) and all("https://" in r for r in refs)


def test_persona_knowledge_is_grounded():
    """Spot checks that the profiles carry the facts they are meant to be grounded in."""
    pol, farm, fin = (per.PERSONAS[k] for k in ("policy", "farmer", "finance"))
    pol_text = " ".join(f for f, _ in pol.context)
    assert "Land Use Framework" in pol_text and "16.5%" in pol_text and "LULUCF" in pol_text
    farm_text = " ".join(f for f, _ in farm.context) + " ".join(farm.caveats)
    assert "tenan" in farm_text and "landlord" in farm_text and "SFI26" in farm_text
    fin_text = " ".join(f for f, _ in fin.context)
    for term in ("Woodland Carbon Code", "Peatland Code", "Pending Issuance Units", "ICVCM",
                 "VCMI", "TNFD", "FCA", "Property (Digital Assets etc) Act 2025"):
        assert term in fin_text, term
    assert any("not carbon or nature credits" in c for c in fin.caveats)
    assert any("not investment" in c for c in fin.caveats)
    assert any("not financial, legal or agronomic advice" in c for c in farm.caveats)
    res = per.PERSONAS["research"]
    res_text = " ".join(f for f, _ in res.context)
    for term in ("FAIR", "UKRI", "NERC", "Tier 1", "GWP100", "CEOS", "Gemini"):
        assert term in res_text, term
    assert any("parameter state" in c for c in res.caveats)
    assert any("structural uncertainty" in c for c in res.caveats)
    ngo = per.PERSONAS["ngo"]
    ngo_text = " ".join(f for f, _ in ngo.context)
    for term in ("State of Nature 2023", "19%", "more, bigger, better", "30by30", "2042",
                 "party politics", "IUCN Global Standard"):
        assert term in ngo_text, term
    assert any("do not assess species" in c for c in ngo.caveats)


def test_personas_in_system_prompt_and_tools():
    sp = system_prompt({}, {})
    assert "User personas" in sp and "set_persona" in sp
    for p in per.PERSONAS.values():
        assert f"Persona `{p.id}`" in sp and p.section_title in sp
    tool = next(t for t in LOCAL_TOOLS if t["name"] == "set_persona")
    assert tool["input_schema"]["properties"]["persona"]["enum"] == per.PERSONA_IDS
    wr = next(t for t in LOCAL_TOOLS if t["name"] == "write_report")
    assert "persona_section_markdown" in wr["input_schema"]["properties"]


def test_unknown_fixed_persona_is_rejected():
    with pytest.raises(ValueError):
        Orchestrator(None, SimpleNamespace(agents={}, skipped={}), persona="banker")


# --------------------------------------------------------------------------- #
# end-to-end runs per persona
# --------------------------------------------------------------------------- #
def run(steps, *, persona=None, answers=None, tmp, question=None):
    claude = ScriptedClaude(steps)
    asked = []

    def ask(qs):
        asked.append(qs)
        return (answers or {}).get(len(asked), [""] * len(qs))

    async def go():
        async with AgentPool() as pool:
            orch = Orchestrator(claude, pool, ask=ask, out_dir=tmp, persona=persona,
                                log=lambda s: None)
            return await orch.run(question or QUESTIONS[persona or "farmer"])

    return SimpleNamespace(result=asyncio.run(go()), claude=claude, asked=asked)


QUESTIONS = {
    "farmer": "I rent 40 ha of peat near Ely and grow potatoes. Would raising the water table "
              "cut my farm's emissions?",
    "finance": "We are looking at tokenising Peatland Code units from rewetted Fenland. What "
               "abatement per hectare could a rewetting project deliver?",
    "research": "For a paper on Fenland peat rewetting: how sensitive is the net GHG balance "
                "to the mean water-table depth, and how was the model validated?",
    "policy": "For the Land Use Framework, how much livestock methane comes from the area "
              "around Crewe?",
}


def report_args(title, section=None, **extra):
    a = {"title": title, "audience": extra.pop("audience", "the user"),
         "question_as_understood": "As asked.", "key_findings": ["See [R1]."],
         "results_markdown": "From [R1].", "interpretation_markdown": "Interpretation.",
         "caveats": ["Model estimate."]}
    if section is not None:
        a["persona_section_markdown"] = section
    return a | extra


def test_farmer_persona_selected_by_model(tmp_path):
    state = {}
    steps = [
        # persona and a tenure question in the same turn
        lambda m: msg(
            tool_use(1, "set_persona", {"persona": "farmer",
                                        "rationale": "rents land and grows potatoes"}),
            tool_use(2, "ask_user", {"questions": [{
                "question": per.PERSONAS["farmer"].follow_ups[2].question,
                "default_assumption": "not known"}]})),
        lambda m: (state.update(first=last_results(m)), msg(
            tool_use(3, "record_assumptions", {"assumptions": [
                {"topic": "Water table", "assumption": "raise mean water table to 0.3 m",
                 "rationale": "a level compatible with some cropping"}]}),
            tool_use(4, "dt8__ghg_balance", {"crop": "Potato"}),
            tool_use(5, "dt8__ghg_balance", {"crop": "Potato", "mean_wtd_m": 0.3})))[1],
        lambda m: msg(tool_use(6, "write_report", report_args(
            "Raising the water table on a rented Fenland potato farm",
            section="Talk to your landlord before rewetting; the Peatland Code may apply.",
            audience="a tenant farmer"))),
        lambda m: msg(text("Done."), stop="end_turn"),
    ]
    r = run(steps, answers={1: ["Farm Business Tenancy, 10 years left"]}, tmp=tmp_path)
    res = r.result
    assert res.stop == "done" and res.persona == "farmer" and not res.persona_fixed
    assert "Persona set to Farmer" in state["first"]["tu1"]["content"]
    assert res.clarifications[0]["answer"] == "Farm Business Tenancy, 10 years left"
    assert [c.ok for c in res.calls] == [True, True]
    md = res.markdown
    assert "(persona: Farmer (owner-occupier or tenant) or land manager)" in md
    assert "## What this could mean for your farm" in md
    assert "Talk to your landlord before rewetting" in md
    assert md.index("## What this means") < md.index("## What this could mean for your farm") \
        < md.index("## Caveats")
    for c in per.PERSONAS["farmer"].caveats:
        assert c in md
    assert "**Persona.** Farmer (owner-occupier or tenant) or land manager (inferred by the " \
           "orchestrator; rents land and grows potatoes)" in md
    assert "Agricultural Tenancies Act 1995" in md        # persona context sources
    assert "Peatland Code" in r.result.html_path.read_text()


def test_fixed_finance_persona(tmp_path):
    state = {}
    steps = [
        # the application fixed the persona: an attempt to change it is refused, and agent
        # calls need only the assumptions
        lambda m: (state.update(first_user=m[0]["content"]),
                   msg(tool_use(1, "set_persona", {"persona": "policy", "rationale": "x"})))[1],
        lambda m: (state.update(refused=last_results(m)["tu1"]), msg(
            tool_use(2, "record_assumptions", {"assumptions": []}),
            tool_use(3, "dt8__water_table_scenario", {"crop": "Potato",
                                                      "mean_wtd_m": [0.05, 0.3, 0.66]})))[1],
        # a report without the persona section is sent back
        lambda m: (state.update(calls=last_results(m)),
                   msg(tool_use(4, "write_report", report_args("Rewetting abatement"))))[1],
        lambda m: (state.update(missing=last_results(m)["tu4"]), msg(tool_use(
            5, "write_report", report_args(
                "Rewetting abatement",
                section="Modelled abatement is not a Peatland Code unit; a token must map "
                        "one-to-one to registry units."))))[1],
        lambda m: msg(text("Done."), stop="end_turn"),
    ]
    r = run(steps, persona="finance", tmp=tmp_path)
    res = r.result
    assert "fixed the persona as 'finance'" in state["first_user"]
    assert state["refused"]["is_error"] and "fixed by the application" in \
        state["refused"]["content"]
    assert res.persona == "finance" and res.persona_fixed
    assert not state["calls"]["tu3"].get("is_error") and res.calls[0].ok
    assert state["missing"]["is_error"] and "persona_section_markdown" in \
        state["missing"]["content"]
    md = res.markdown
    assert res.stop == "done" and "## Credit and market relevance" in md
    assert "(set by the application)" in md
    assert "Model estimates are not carbon or nature credits" in md
    assert "Integrity Council for the Voluntary Carbon Market" in md
    # requests stay cacheable: identical system prompt and tools on every turn
    reqs = r.claude.requests
    assert all(q["system"] == reqs[0]["system"] and q["tools"] == reqs[0]["tools"] for q in reqs)


def test_policy_persona_must_be_set_before_agent_calls(tmp_path):
    state = {}
    crewe = {"lat": 53.10, "lon": -2.44, "radius_km": 10}
    steps = [
        lambda m: msg(tool_use(1, "record_assumptions", {"assumptions": [
            {"topic": "Area", "assumption": "10 km around Crewe", "rationale": "default"}]})),
        lambda m: msg(tool_use(2, "dt2__area_methane", {"area": crewe})),
        lambda m: (state.update(gate=last_results(m)["tu2"]), msg(
            tool_use(3, "set_persona", {"persona": "policy",
                                        "rationale": "mentions the Land Use Framework"}),
            tool_use(4, "dt2__area_methane", {"area": crewe})))[1],
        lambda m: (state.update(after=last_results(m)), msg(tool_use(5, "write_report", report_args(
            "Livestock methane around Crewe", section="Relevant to the Land Use Framework and "
            "the agriculture sector of the inventory; evidence is calibrated, not validated "
            "locally.", audience="Defra land use policy team"))))[1],
        lambda m: msg(text("Done."), stop="end_turn"),
    ]
    r = run(steps, tmp=tmp_path)
    res = r.result
    gate = state["gate"]
    assert gate["is_error"] and "set_persona" in gate["content"] \
        and "record_assumptions" not in gate["content"]
    assert not state["after"]["tu4"].get("is_error")
    assert [c.ref for c in res.calls] == ["R1"] and res.calls[0].ok
    md = res.markdown
    assert res.persona == "policy" and "## Policy relevance" in md
    assert "Results from pilot landscapes are indicative" in md
    assert "Land Use Framework. https://www.gov.uk/government/publications/land-use-framework" \
        in md


def test_research_persona_selected_by_model(tmp_path):
    state = {}
    steps = [
        lambda m: msg(tool_use(1, "set_persona", {
            "persona": "research", "rationale": "writing a paper; asks about sensitivity and "
                                                "validation"})),
        lambda m: msg(
            tool_use(2, "record_assumptions", {"assumptions": [
                {"topic": "Sensitivity design", "assumption": "one-at-a-time sweep of mean "
                 "water-table depth, 0.05-0.9 m", "rationale": "persona default"}]}),
            tool_use(3, "dt8__water_table_scenario", {"crop": "Potato",
                                                      "mean_wtd_m": [0.05, 0.3, 0.6, 0.9]}),
            tool_use(4, "dt8__validate_inventory", {})),
        lambda m: (state.update(res=last_results(m)), msg(tool_use(5, "write_report", report_args(
            "Sensitivity of the Fenland peat GHG balance to water-table depth",
            section="DT8 three-gas model, calibrated parameters [R1]; inventory comparison "
                    "[R2]. Reproduce with the logged calls.",
            audience="a peatland researcher"))))[1],
        lambda m: msg(text("Done."), stop="end_turn"),
    ]
    r = run(steps, persona=None, tmp=tmp_path, question=QUESTIONS["research"])
    res = r.result
    assert res.stop == "done" and res.persona == "research"
    assert all(c.ok for c in res.calls) and len(res.calls) == 2
    md = res.markdown
    assert "(persona: Research scientist)" in md
    assert "## Methods, uncertainty and reproducibility" in md
    for c in per.PERSONAS["research"].caveats:
        assert c in md
    assert "https://doi.org/10.1038/sdata.2016.18" in md          # FAIR principles cited
    assert "gwp100: IPCC AR6" in md                                 # agent provenance kept


def test_general_persona_has_no_persona_section(tmp_path):
    steps = [
        lambda m: msg(tool_use(1, "set_persona", {"persona": "general",
                                                  "rationale": "no signal about the user"}),
                      tool_use(2, "record_assumptions", {"assumptions": []}),
                      tool_use(3, "dt8__ghg_balance", {"crop": "Potato"})),
        lambda m: msg(tool_use(4, "write_report", report_args("Potato on peat"))),
        lambda m: msg(text("Done."), stop="end_turn"),
    ]
    res = run(steps, tmp=tmp_path, question="What does growing potatoes on peat emit?").result
    md = res.markdown
    assert res.stop == "done" and res.persona == "general"
    assert "(persona:" not in md and "General (no persona-specific framing)" in md
    for p in per.PERSONAS.values():
        assert f"## {p.section_title}" not in md
    assert "context sources for this persona" not in md
