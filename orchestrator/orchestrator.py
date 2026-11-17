"""SLATE orchestrator agent: plain-language questions in, a short evidence-based report out.

The orchestrator is a Claude agent (Claude API, tool use) whose tools are

* every tool of every available digital-twin agent (DT2 livestock methane, DT4 forest biomass,
  DT6 trees outside woodland, DT8 peatland greenhouse gases), reached over MCP and named
  ``<agent>__<tool>``;
* five tools of its own:
  - ``ask_user``: follow-up questions, each with the default it would otherwise assume;
  - ``set_persona``: which of the personas it is trained for (policy-maker, farmer or land
    manager, green finance manager, research scientist, NGO; see ``personas.py``) the user is,
    or 'general'. It must be called before the first agent call, unless the application
    fixed the persona;
  - ``record_assumptions``: the assumptions it makes to turn the question into agent inputs.
    It must be called before the first agent call, so every run states its assumptions;
  - ``make_figure``: bar and line charts and point maps of England from agent numbers;
  - ``write_report``: the final report (key findings, results, interpretation, caveats).

The orchestrator itself, not the model, logs the question, the follow-up questions and answers,
the assumptions, every agent call and the agents' provenance, and appends them to the report.

Usage
-----
    export ANTHROPIC_API_KEY=...            # or `ant auth login`
    python orchestrator/orchestrator.py "How much methane do the cattle around Crewe emit?"
    python orchestrator/orchestrator.py --non-interactive --out reports/ "..."
    python orchestrator/orchestrator.py --persona farmer "..."

Without a question it asks for one. In interactive mode follow-up questions are asked on the
terminal (press Enter to accept the proposed default); with ``--non-interactive`` the defaults
are used and recorded as assumptions. Reports are written as Markdown and self-contained HTML.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import figures as fig  # noqa: E402
import personas as per  # noqa: E402
import report as rep  # noqa: E402
from agent_pool import AgentPool, CallRecord, result_text  # noqa: E402
from prompts import system_prompt  # noqa: E402

MODEL = "claude-opus-5-5"
EFFORT = "high"
MAX_TURNS = 40
MAX_QUESTION_ROUNDS = 2

AskFn = Callable[[list[dict]], "list[str] | Awaitable[list[str]]"]

# --------------------------------------------------------------------------- #
# the orchestrator's own tools
# --------------------------------------------------------------------------- #
LOCAL_TOOLS = [
    {
        "name": "ask_user",
        "description": (
            "Ask the user one to three short follow-up questions when information that would "
            "change the answer materially is missing and cannot reasonably be assumed. Give "
            "for each question the default you will assume if the user does not answer."),
        "input_schema": {
            "type": "object",
            "properties": {"questions": {"type": "array", "minItems": 1, "maxItems": 3, "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "default_assumption": {"type": "string"}},
                "required": ["question", "default_assumption"]}}},
            "required": ["questions"]},
    },
    {
        "name": "set_persona",
        "description": (
            "Set the persona of the user (see 'User personas' in the instructions): 'policy' "
            "(policy-maker in land use and agricultural policy), 'farmer' (farmer, owner or "
            "tenant, or land manager), 'finance' (green finance manager, carbon and nature "
            "credits, tokenisation), 'research' (research scientist), 'ngo' (conservation, "
            "nature restoration or environmental NGO) or 'general'. Must be called before "
            "the first agent call unless the persona was fixed by the application."),
        "input_schema": {
            "type": "object",
            "properties": {
                "persona": {"type": "string", "enum": per.PERSONA_IDS},
                "rationale": {"type": "string",
                              "description": "The cues in the question that point to it."}},
            "required": ["persona", "rationale"]},
    },
    {
        "name": "record_assumptions",
        "description": (
            "Record the assumptions made to turn the user's question into agent inputs (places "
            "and coordinates, years, baselines, scenario sizes, units, interpretations). Must "
            "be called before the first agent call; call it again for assumptions added later. "
            "Use an empty list if there are none."),
        "input_schema": {
            "type": "object",
            "properties": {"assumptions": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "assumption": {"type": "string"},
                    "rationale": {"type": "string"},
                    "agents": {"type": "array", "items": {"type": "string"}}},
                "required": ["topic", "assumption", "rationale"]}}},
            "required": ["assumptions"]},
    },
    {
        "name": "make_figure",
        "description": (
            "Draw a figure from numbers returned by the agents. kind 'bar': categories and "
            "series (name -> values, optional errors name -> half-widths); kind 'line': x and "
            "series; kind 'map': points with lat, lon, value and optional label, drawn on an "
            "England outline. Returns the figure id to list in write_report."),
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["bar", "line", "map"]},
                "title": {"type": "string"},
                "caption": {"type": "string", "description": "One or two sentences, with the "
                                                              "[R#] references of the data."},
                "categories": {"type": "array", "items": {"type": "string"}},
                "series": {"type": "object",
                           "additionalProperties": {"type": "array", "items": {"type": "number"}}},
                "errors": {"type": "object",
                           "additionalProperties": {"type": "array", "items": {"type": "number"}}},
                "x": {"type": "array", "items": {"type": "number"}},
                "xlabel": {"type": "string"},
                "ylabel": {"type": "string"},
                "points": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"lat": {"type": "number"}, "lon": {"type": "number"},
                                   "value": {"type": "number"}, "label": {"type": "string"}},
                    "required": ["lat", "lon"]}},
                "value_label": {"type": "string"},
                "note": {"type": "string"}},
            "required": ["kind", "title", "caption"]},
    },
    {
        "name": "write_report",
        "description": "Write the final short report. Call once, at the end.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "audience": {"type": "string", "description": "e.g. 'a dairy farmer', 'Defra "
                                                               "policy team', 'an NGO'"},
                "question_as_understood": {"type": "string"},
                "key_findings": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "results_markdown": {"type": "string"},
                "interpretation_markdown": {"type": "string"},
                "persona_section_markdown": {
                    "type": "string",
                    "description": "The persona section (its title is added by the "
                                   "orchestrator); required unless the persona is 'general'."},
                "caveats": {"type": "array", "items": {"type": "string"}},
                "figure_ids": {"type": "array", "items": {"type": "string"}},
                "next_steps": {"type": "array", "items": {"type": "string"}}},
            "required": ["title", "audience", "question_as_understood", "key_findings",
                         "results_markdown", "interpretation_markdown", "caveats"]},
    },
]


# --------------------------------------------------------------------------- #
# run state
# --------------------------------------------------------------------------- #
@dataclass
class RunResult:
    question: str
    markdown: str | None = None
    markdown_path: Path | None = None
    html_path: Path | None = None
    clarifications: list[dict] = field(default_factory=list)
    assumptions: list[dict] = field(default_factory=list)
    calls: list[CallRecord] = field(default_factory=list)
    figures: dict[str, rep.Figure] = field(default_factory=dict)
    assumptions_recorded: bool = False
    persona: str | None = None              # a key of personas.PERSONAS or 'general'
    persona_rationale: str = ""
    persona_fixed: bool = False             # set by the application, not chosen by the model
    stop: str = ""
    usage: dict = field(default_factory=dict)


def terminal_ask(questions: list[dict]) -> list[str]:
    """Ask on the terminal; Enter accepts the proposed default."""
    answers = []
    print("\nThe orchestrator needs a little more information "
          "(press Enter to accept the suggestion in brackets):")
    for q in questions:
        why = f"  ({q['why_it_matters']})" if q.get("why_it_matters") else ""
        a = input(f"\n- {q['question']}{why}\n  [{q['default_assumption']}] > ").strip()
        answers.append(a)
    return answers


def no_answer(questions: list[dict]) -> list[str]:
    return ["" for _ in questions]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "report"


class Orchestrator:
    """One orchestration: question -> (follow-ups) -> assumptions -> agent calls -> report."""

    def __init__(self, client, pool: AgentPool, *, ask: AskFn = terminal_ask,
                 out_dir: Path = Path("reports"), model: str = MODEL, effort: str = EFFORT,
                 max_turns: int = MAX_TURNS, max_question_rounds: int = MAX_QUESTION_ROUNDS,
                 persona: str | None = None,
                 log: Callable[[str], None] = lambda s: print(s, file=sys.stderr)):
        self.client = client
        self.pool = pool
        self.ask = ask
        self.out_dir = Path(out_dir)
        self.model = model
        self.effort = effort
        self.max_turns = max_turns
        self.max_question_rounds = max_question_rounds
        if persona is not None:
            per.get(persona)                         # raises on an unknown persona
        self.persona = persona
        self.log = log

    # -- local tools --------------------------------------------------------
    async def _ask_user(self, run: RunResult, args: dict, rounds: list[int]) -> str:
        if rounds[0] >= self.max_question_rounds:
            return ("No more follow-up questions in this run. Proceed with your default "
                    "assumptions and record them with record_assumptions.")
        rounds[0] += 1
        qs = args["questions"]
        answers = self.ask(qs)
        if inspect.isawaitable(answers):
            answers = await answers
        lines = []
        for q, a in zip(qs, answers):
            given = a.strip() if a else ""
            shown = given or f"no answer; default assumed: {q['default_assumption']}"
            run.clarifications.append({"question": q["question"], "answer": shown})
            lines.append(f"Q: {q['question']}\nA: {given or '(no answer - use your default: ' + q['default_assumption'] + '; record it as an assumption)'}")
        return "\n\n".join(lines)

    def _set_persona(self, run: RunResult, a: dict) -> tuple[str, bool]:
        chosen = a["persona"]
        if run.persona_fixed:
            if chosen == run.persona:
                return f"Persona is {run.persona} (fixed by the application).", False
            return (f"The persona is fixed by the application as '{run.persona}'; keep "
                    f"writing for that persona."), True
        p = per.get(chosen)                          # raises on an unknown persona
        run.persona, run.persona_rationale = chosen, a.get("rationale", "")
        self.log(f"[persona] {chosen}: {run.persona_rationale}")
        if p is None:
            return "Persona set to general: no persona section in the report.", False
        return (f"Persona set to {p.label}. Adapt questions, assumptions, framing and the "
                f"report section '{p.section_title}' to it."), False

    def _make_figure(self, run: RunResult, a: dict) -> str:
        fid = str(len(run.figures) + 1)
        stem = _slug(run.question)[:30]
        path = self.out_dir / f"{stem}-fig{fid}.png"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        kind = a["kind"]
        if kind == "bar":
            cats, series = a.get("categories") or [], a.get("series") or {}
            if not cats or not series or any(len(v) != len(cats) for v in series.values()):
                raise ValueError("bar needs categories and series of the same length")
            fig.bar(path, a["title"], cats, series, a.get("ylabel", ""), a.get("note", ""),
                    a.get("errors"))
        elif kind == "line":
            x, series = a.get("x") or [], a.get("series") or {}
            if not x or not series or any(len(v) != len(x) for v in series.values()):
                raise ValueError("line needs x and series of the same length")
            fig.line(path, a["title"], x, series, a.get("xlabel", ""), a.get("ylabel", ""),
                     a.get("note", ""))
        else:
            pts = a.get("points") or []
            if not pts:
                raise ValueError("map needs points")
            fig.point_map(path, a["title"], pts, a.get("value_label", ""), a.get("note", ""))
        run.figures[fid] = rep.Figure(id=fid, path=path, caption=a["caption"])
        return f"Figure {fid} created ({kind}: {a['title']}). List '{fid}' in figure_ids."

    def _write_report(self, run: RunResult, a: dict) -> str:
        if run.persona is None:
            run.persona, run.persona_rationale = per.GENERAL, "not set before the report"
        persona = per.get(run.persona)
        section = (a.get("persona_section_markdown") or "").strip()
        if persona is not None and not section:
            raise ValueError(f"persona_section_markdown is required for persona "
                             f"'{run.persona}' (section '{persona.section_title}')")
        content = rep.ReportContent(
            title=a["title"], audience=a["audience"],
            question_as_understood=a["question_as_understood"],
            key_findings=a["key_findings"], results_markdown=a["results_markdown"],
            interpretation_markdown=a["interpretation_markdown"], caveats=a.get("caveats", []),
            figure_ids=[str(f) for f in a.get("figure_ids", [])],
            next_steps=a.get("next_steps", []), persona_section_markdown=section)
        md = rep.render_markdown(
            content, question=run.question, clarifications=run.clarifications,
            persona=run.persona, persona_rationale=run.persona_rationale,
            persona_fixed=run.persona_fixed,
            assumptions=run.assumptions, calls=run.calls, figures=run.figures,
            agents_used={k: v.name for k, v in self.pool.agents.items()})
        stem = f"{datetime.now(timezone.utc):%Y%m%d-%H%M}-{_slug(a['title'])}"
        used = {k: v for k, v in run.figures.items() if k in content.figure_ids}
        run.markdown = md
        run.markdown_path, run.html_path = rep.write(self.out_dir, stem, md, used, a["title"])
        return f"Report written to {run.html_path}"

    # -- the loop -----------------------------------------------------------
    async def run(self, question: str) -> RunResult:
        run = RunResult(question=question)
        if self.persona is not None:
            run.persona, run.persona_fixed = self.persona, True
            run.persona_rationale = "set by the application"
        tools = LOCAL_TOOLS + self.pool.tool_definitions()
        system = system_prompt(self.pool.agents, self.pool.skipped)
        today = datetime.now(timezone.utc).strftime("%d %B %Y")
        intro = f"Today is {today}."
        if self.persona is not None:
            p = per.get(self.persona)
            intro += (f" The application has fixed the persona as '{self.persona}'"
                      + (f" ({p.label})" if p else "") + "; do not call set_persona.")
        messages: list[dict] = [{"role": "user", "content":
                                 f"{intro} Question from the user:\n\n{question}"}]
        rounds = [0]
        nudged = False
        for _ in range(self.max_turns):
            response = await self.client.beta.messages.create(
                model=self.model, max_tokens=16000, system=system, tools=tools,
                messages=messages, thinking={"type": "adaptive"},
                output_config={"effort": self.effort}, cache_control={"type": "ephemeral"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            self._usage(run, response)
            if response.stop_reason == "refusal":
                run.stop = "refusal"
                return run
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "pause_turn":
                continue
            uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
            if not uses:
                if run.markdown is not None:
                    run.stop = "done"
                    return run
                if nudged:
                    run.stop = "no_report"
                    return run
                nudged = True
                messages.append({"role": "user", "content": (
                    "Please continue: if you need information from the user, use ask_user; "
                    "otherwise finish by calling write_report.")})
                continue
            results = []
            for b in uses:
                content, is_error = await self._dispatch(run, b.name, dict(b.input), rounds)
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": content,
                                **({"is_error": True} if is_error else {})})
            messages.append({"role": "user", "content": results})
            if run.markdown is not None and all(b.name == "write_report" for b in uses):
                run.stop = "done"
                return run
        run.stop = "max_turns"
        return run

    async def _dispatch(self, run: RunResult, name: str, args: dict,
                        rounds: list[int]) -> tuple[str, bool]:
        try:
            if name == "ask_user":
                return await self._ask_user(run, args, rounds), False
            if name == "set_persona":
                return self._set_persona(run, args)
            if name == "record_assumptions":
                run.assumptions.extend(args.get("assumptions", []))
                run.assumptions_recorded = True
                n = len(args.get("assumptions", []))
                self.log(f"[assumptions] {n} recorded")
                for x in args.get("assumptions", []):
                    self.log(f"  - {x['topic']}: {x['assumption']}")
                return f"{n} assumptions recorded (total {len(run.assumptions)}).", False
            if name == "make_figure":
                return self._make_figure(run, args), False
            if name == "write_report":
                return self._write_report(run, args), False
            if self.pool.owns(name):
                missing = [s for s, ok in (("set_persona", run.persona is not None),
                                           ("record_assumptions (an empty list if you make "
                                            "none)", run.assumptions_recorded)) if not ok]
                if missing:
                    return f"Call {' and '.join(missing)} first, then repeat this call.", True
                ref = f"R{len(run.calls) + 1}"
                agent, tool = name.split("__", 1)
                self.log(f"[{ref}] {agent}.{tool} {json.dumps(args)[:200]}")
                ok, result = await self.pool.call(name, args)
                run.calls.append(CallRecord(ref=ref, agent=agent, tool=tool, arguments=args,
                                            ok=ok, result=result,
                                            assumptions=[a["topic"] for a in run.assumptions]))
                if not ok:
                    return f"[{ref}] error from {agent}: {result}", True
                return f"[{ref}] " + result_text(result), False
            return f"Unknown tool {name}", True
        except Exception as exc:                     # report the failure to the model
            return f"{name} failed: {exc}", True

    @staticmethod
    def _usage(run: RunResult, response) -> None:
        u = getattr(response, "usage", None)
        if u is None:
            return
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                  "cache_creation_input_tokens"):
            v = getattr(u, k, None)
            if isinstance(v, int):
                run.usage[k] = run.usage.get(k, 0) + v


# --------------------------------------------------------------------------- #
# command line
# --------------------------------------------------------------------------- #
async def main_async(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("question", nargs="*", help="the question; asked for if omitted")
    p.add_argument("--out", default="reports", help="output folder (default: reports/)")
    p.add_argument("--non-interactive", action="store_true",
                   help="do not ask follow-up questions; use the defaults")
    p.add_argument("--persona", choices=per.PERSONA_IDS,
                   help="fix the user persona instead of letting the orchestrator infer it")
    p.add_argument("--agents", help="agent registry JSON (default: orchestrator/agents.json)")
    p.add_argument("--model", default=MODEL)
    p.add_argument("--effort", default=EFFORT, choices=["low", "medium", "high", "xhigh", "max"])
    a = p.parse_args(argv)
    question = " ".join(a.question).strip() or input("Your question: ").strip()
    if not question:
        return 1

    import anthropic
    from agent_pool import load_registry
    registry = load_registry(Path(a.agents)) if a.agents else None
    async with AgentPool(registry) as pool:
        print(f"Agents: {', '.join(v.name for v in pool.agents.values())}"
              + (f"; not available: {', '.join(pool.skipped)}" if pool.skipped else ""),
              file=sys.stderr)
        orch = Orchestrator(anthropic.AsyncAnthropic(), pool, out_dir=Path(a.out),
                            ask=no_answer if a.non_interactive else terminal_ask,
                            model=a.model, effort=a.effort, persona=a.persona)
        try:
            result = await orch.run(question)
        except anthropic.AuthenticationError:
            print("No valid Anthropic credentials: set ANTHROPIC_API_KEY or run `ant auth login`.",
                  file=sys.stderr)
            return 2
    if result.html_path:
        print(f"\nReport: {result.html_path}\n        {result.markdown_path}")
        return 0
    print(f"\nNo report was produced (stop: {result.stop}).", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
