"""The SLATE orchestrator's tools served as one MCP server, so any MCP-capable agent can drive it.

The orchestrator (``orchestrator/orchestrator.py``) normally runs its own tool loop against the
Claude API. This bridge exposes exactly the same tools over MCP instead: the orchestrator's
own tools (``set_persona``, ``ask_user``, ``record_assumptions``, ``make_figure``,
``write_report``) and every tool of every digital-twin agent (``dt2__area_methane``, ...). Each
call goes through ``Orchestrator._dispatch``, so the persona gate, the assumptions gate, the
[R#] references, the figures and the rendered report (with the orchestrator's own log of every
agent call and its provenance) are identical to an API run. Only the language-model loop is
outside: here it is a headless Claude Code agent (see ``persona_demo.py``).

Configuration comes from environment variables:

* ``SLATE_OUT``      output folder for the report, figures and ``run_log.json`` (required)
* ``SLATE_QUESTION`` the user's question, as it appears in the report (required)
* ``SLATE_PERSONA``  fix the persona as the application would (optional)

After every call the bridge rewrites ``run_log.json`` with the persona, follow-up questions,
assumptions and every agent call with its full result, so the run can be audited afterwards.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "orchestrator"))

from agent_pool import AgentPool  # noqa: E402
from orchestrator import LOCAL_TOOLS, Orchestrator, RunResult, no_answer  # noqa: E402

OUT = Path(os.environ.get("SLATE_OUT", "demo_out"))
QUESTION = os.environ.get("SLATE_QUESTION", "")
PERSONA = os.environ.get("SLATE_PERSONA") or None


class State:
    pool: AgentPool
    orch: Orchestrator
    run: RunResult
    rounds = [0]
    tools: list[dict]


S = State()


def write_log() -> None:
    r = S.run
    log = {
        "question": r.question,
        "persona": r.persona, "persona_fixed": r.persona_fixed,
        "persona_rationale": r.persona_rationale,
        "clarifications": r.clarifications,
        "assumptions": r.assumptions,
        "calls": [{"ref": c.ref, "agent": c.agent, "tool": c.tool, "arguments": c.arguments,
                   "ok": c.ok, "result": c.result} for c in r.calls],
        "figures": {k: {"path": str(v.path), "caption": v.caption} for k, v in r.figures.items()},
        "report_markdown": str(r.markdown_path) if r.markdown_path else None,
        "report_html": str(r.html_path) if r.html_path else None,
        "agents": {k: v.name for k, v in S.pool.agents.items()},
    }
    (OUT / "run_log.json").write_text(json.dumps(log, indent=1, default=str))


@asynccontextmanager
async def lifespan(_server):
    OUT.mkdir(parents=True, exist_ok=True)
    async with AgentPool() as pool:
        S.pool = pool
        S.orch = Orchestrator(None, pool, ask=no_answer, out_dir=OUT, persona=PERSONA,
                              log=lambda s: print(s, file=sys.stderr))
        S.run = RunResult(question=QUESTION)
        if PERSONA:
            S.run.persona, S.run.persona_fixed = PERSONA, True
            S.run.persona_rationale = "set by the application"
        S.tools = LOCAL_TOOLS + pool.tool_definitions()
        write_log()
        yield {}


async def list_tools(_ctx, _params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=[
        types.Tool(name=t["name"], description=t["description"], input_schema=t["input_schema"])
        for t in S.tools])


async def call_tool(_ctx, params) -> types.CallToolResult:
    text, is_error = await S.orch._dispatch(S.run, params.name, dict(params.arguments or {}),
                                            S.rounds)
    write_log()
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)],
                                is_error=is_error)


server = Server("slate", instructions="SLATE orchestrator tools and digital-twin agents.",
                lifespan=lifespan, on_list_tools=list_tools, on_call_tool=call_tool)


async def main() -> None:
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
