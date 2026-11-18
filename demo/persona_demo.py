"""Run the SLATE persona demonstration: one multi-twin question per persona.

For each persona in ``questions.py`` the orchestrator gets the question, with the persona fixed
as an application that knows its user would fix it, and must answer it by interrogating several
digital twins and synthesising their outputs into one report written for that persona.

Two backends drive the orchestrator's model loop:

* ``claude-code`` (default): a headless Claude Code agent is the language model. It is given the
  orchestrator's own system prompt and, through ``slate_bridge_server.py``, exactly the
  orchestrator's tools over MCP. Needs the ``claude`` CLI, signed in. No API key is needed.
* ``api``: the orchestrator's own tool loop on the Claude API (``orchestrator.py``). Needs
  ``ANTHROPIC_API_KEY``.

Either way the twins are the real MCP servers, every call goes through the orchestrator's
dispatcher (persona and assumption gates, [R#] references, provenance) and the report is the
orchestrator's own Markdown and HTML report. Follow-up questions are answered with the
orchestrator's defaults, which are recorded in the report.

After the runs the script checks each one (report written, at least two twins called, persona
section present) and traces the numbers in the key findings back to the agent results, then
writes ``demo/runs/WALKTHROUGH.md``.

    python demo/persona_demo.py                      # all six personas, in parallel
    python demo/persona_demo.py farmer ngo           # some of them
    python demo/persona_demo.py --backend api
    python demo/persona_demo.py --summarise-only     # rebuild the walkthrough from saved runs
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "orchestrator"))
sys.path.insert(0, str(HERE))

import personas as per  # noqa: E402
from agent_pool import AgentPool  # noqa: E402
from prompts import system_prompt  # noqa: E402
from questions import QUESTIONS  # noqa: E402

RUNS = HERE / "runs"
MODEL = "claude-opus-5-5"
TWIN_NAMES = {"dt2": "DT2 livestock methane", "dt4": "DT4 forest biomass",
              "dt6": "DT6 trees outside woodland", "dt8": "DT8 peatland GHG"}

BRIDGE_NOTE = """

Tool names in this deployment

The tools above are served to you over MCP by the `slate` server, so every name carries the
prefix `mcp__slate__`: `set_persona` is `mcp__slate__set_persona`, `dt2__area_methane` is
`mcp__slate__dt2__area_methane`, and so on. You have no other tools. Follow-up questions go
through `mcp__slate__ask_user`; the run is unattended, so expect your defaults to be used.
Your work ends when `mcp__slate__write_report` succeeds; after that reply with one line.
"""


def intro(persona: str) -> str:
    today = datetime.now(timezone.utc).strftime("%d %B %Y")
    p = per.get(persona)
    return (f"Today is {today}. The application has fixed the persona as '{persona}'"
            + (f" ({p.label})" if p else "") + "; do not call set_persona.")


# --------------------------------------------------------------------------- #
# backends
# --------------------------------------------------------------------------- #
async def run_claude_code(persona: str, q: dict, out: Path, system: str, max_turns: int,
                          model: str) -> dict:
    cfg = out / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"slate": {
        "command": sys.executable, "args": [str(HERE / "slate_bridge_server.py")],
        "env": {"SLATE_OUT": str(out), "SLATE_QUESTION": q["question"],
                "SLATE_PERSONA": persona}}}}))
    prompt = f"{intro(persona)} Question from the user:\n\n{q['question']}"
    cmd = ["claude", "-p", prompt, "--model", model, "--system-prompt", system + BRIDGE_NOTE,
           "--tools", "", "--mcp-config", str(cfg), "--strict-mcp-config",
           "--allowedTools", "mcp__slate__*", "--output-format", "stream-json", "--verbose",
           "--max-turns", str(max_turns)]
    t0 = time.time()
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, cwd=out,
        env={**os.environ, "MCP_TOOL_TIMEOUT": "600000", "MCP_TIMEOUT": "120000"})
    stdout, stderr = await proc.communicate()
    events = [json.loads(l) for l in stdout.decode().splitlines() if l.startswith("{")]
    keep = [e for e in events if e.get("type") in ("assistant", "user", "result")
            and e.get("subtype") != "thinking_tokens"]      # streaming deltas duplicate these
    (out / "transcript.jsonl").write_text("\n".join(json.dumps(e) for e in keep))
    steps, final = [], {}
    for ev in events:
        content = ev.get("message", {}).get("content", [])
        for c in content if isinstance(content, list) else []:
            if c.get("type") == "tool_use":
                steps.append(c["name"].removeprefix("mcp__slate__"))
        if ev.get("type") == "result":
            final = ev
    return {"backend": "claude-code", "model": model, "seconds": round(time.time() - t0),
            "turns": final.get("num_turns"), "tool_sequence": steps,
            "final_message": final.get("result"), "is_error": final.get("is_error", True),
            "stderr_tail": stderr.decode()[-2000:] if proc.returncode else ""}


async def run_api(persona: str, q: dict, out: Path, model: str) -> dict:
    import anthropic
    from orchestrator import Orchestrator, no_answer
    t0 = time.time()
    async with AgentPool() as pool:
        orch = Orchestrator(anthropic.AsyncAnthropic(), pool, ask=no_answer, out_dir=out,
                            persona=persona, model=model)
        r = await orch.run(q["question"])
    log = {"question": r.question, "persona": r.persona, "persona_fixed": r.persona_fixed,
           "persona_rationale": r.persona_rationale, "clarifications": r.clarifications,
           "assumptions": r.assumptions,
           "calls": [{"ref": c.ref, "agent": c.agent, "tool": c.tool, "arguments": c.arguments,
                      "ok": c.ok, "result": c.result} for c in r.calls],
           "figures": {k: {"path": str(v.path), "caption": v.caption}
                       for k, v in r.figures.items()},
           "report_markdown": str(r.markdown_path) if r.markdown_path else None,
           "report_html": str(r.html_path) if r.html_path else None}
    (out / "run_log.json").write_text(json.dumps(log, indent=1, default=str))
    return {"backend": "api", "model": model, "seconds": round(time.time() - t0),
            "stop": r.stop, "usage": r.usage, "is_error": r.html_path is None}


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #
NUM = re.compile(r"(?<![\w.])[-−]?\d[\d,]*(?:\.\d+)?")


def _values(x, acc):
    if isinstance(x, bool):
        return acc
    if isinstance(x, (int, float)):
        acc.append(float(x))
    elif isinstance(x, dict):
        for v in x.values():
            _values(v, acc)
    elif isinstance(x, list):
        for v in x:
            _values(v, acc)
    elif isinstance(x, str):
        try:
            _values(json.loads(x), acc)
        except ValueError:
            pass
    return acc


def trace_numbers(text: str, values: list[float]) -> tuple[list[str], list[str]]:
    """Numbers in `text` that equal an agent value at the quoted precision (also x1000 or
    /1000 for unit changes, and sign-flipped for emission/removal wording)."""
    found, other = [], []
    for tok in NUM.findall(text):
        s = tok.replace(",", "").replace("−", "-")
        try:
            v = float(s)
        except ValueError:
            continue
        if (1990 <= v <= 2100 and "." not in s) or (abs(v) < 10 and "." not in s):
            continue                       # years and small counts are not data
        dec = len(s.split(".")[1]) if "." in s else 0
        tol = 0.5 * 10 ** (-dec) + 1e-9
        hit = any(abs(abs(c * k) - abs(v)) <= tol for c in values for k in (1, 1e3, 1e-3, 100))
        (found if hit else other).append(tok)
    return found, other


def check(persona: str, q: dict, out: Path, meta: dict) -> dict:
    log_path = out / "run_log.json"
    log = json.loads(log_path.read_text()) if log_path.exists() else {}
    calls = log.get("calls", [])
    ok_calls = [c for c in calls if c["ok"]]
    twins = sorted({c["agent"] for c in ok_calls})
    md = Path(log["report_markdown"]).read_text() if log.get("report_markdown") else ""
    p = per.get(persona)
    section_ok = p is None or f"## {p.section_title}" in md or p.section_title in md
    kf = md.split("## Key findings", 1)[1].split("\n## ", 1)[0] if "## Key findings" in md else ""
    values = _values([c["result"] for c in ok_calls], [])
    traced, untraced = trace_numbers(kf, values)
    return {"persona": persona, "report": bool(md), "twins_called": twins,
            "twins_expected": q["twins"], "multi_twin": len(twins) >= 2,
            "persona_section": section_ok, "agent_calls": len(calls),
            "failed_calls": len(calls) - len(ok_calls),
            "assumptions": len(log.get("assumptions", [])),
            "clarifications": len(log.get("clarifications", [])),
            "figures": len(log.get("figures", {})),
            "key_finding_numbers_traced": len(traced), "key_finding_numbers_other": untraced,
            "passed": bool(md) and len(twins) >= 2 and section_ok, **meta}


# --------------------------------------------------------------------------- #
# walkthrough
# --------------------------------------------------------------------------- #
def walkthrough(selected: list[str]) -> Path:
    lines = ["# SLATE persona demonstration: one question, several twins, one answer", "",
             "Each persona below asks a question that no single digital twin can answer. The "
             "orchestrator splits it up, interrogates the twins it needs over MCP, puts their "
             "outputs on a common basis and writes one report for that persona. Everything "
             "below is generated by `demo/persona_demo.py`; the full reports, with the "
             "orchestrator's own log of every agent call, are linked.", ""]
    rows = ["| Persona | Question | Twins called | Agent calls | Numbers in key findings "
            "traced to agent outputs | Check |", "|---|---|---|---|---|---|"]
    body = []
    for persona in selected:
        out = RUNS / persona
        if not (out / "check.json").exists():
            continue
        c = json.loads((out / "check.json").read_text())
        log = json.loads((out / "run_log.json").read_text())
        q = QUESTIONS[persona]
        p = per.get(persona)
        label = p.label if p else "General public"
        n_num = c["key_finding_numbers_traced"] + len(c["key_finding_numbers_other"])
        rows.append(f"| {label} | {q['title']} | "
                    f"{', '.join(TWIN_NAMES.get(t, t) for t in c['twins_called'])} | "
                    f"{c['agent_calls']} | {c['key_finding_numbers_traced']} of {n_num} | "
                    f"{'pass' if c['passed'] else 'FAIL'} |")
        md_path = Path(log["report_markdown"]) if log.get("report_markdown") else None
        rel = md_path.relative_to(RUNS) if md_path else None
        body += [f"## {label}", "", f"**Question.** {q['question']}", "",
                 f"**Why it needs several twins.** {q['why']}", "",
                 "**How the orchestrator answered it.**", ""]
        for a in log.get("clarifications", []):
            body.append(f"- Follow-up asked: {a['question']} ({a['answer']})")
        body.append(f"- Recorded {c['assumptions']} assumptions before calling any twin.")
        seq = {}
        for call in log["calls"]:
            seq.setdefault(call["agent"], []).append(
                call["tool"] + ("" if call["ok"] else " (error, corrected)"))
        for agent, tools in seq.items():
            body.append(f"- {TWIN_NAMES.get(agent, agent)}: {', '.join(tools)}")
        body.append(f"- Figures: {c['figures']}. Backend: {c.get('backend')}, "
                    f"{c.get('seconds', '?')} s.")
        if md_path and md_path.exists():
            md = md_path.read_text()
            kf = md.split("## Key findings", 1)[1].split("\n## ", 1)[0].strip() \
                if "## Key findings" in md else ""
            body += ["", "**Synthesised answer (key findings).**", "", kf, ""]
            if p and f"## {p.section_title}" in md:
                sec = md.split(f"## {p.section_title}", 1)[1].split("\n## ", 1)[0].strip()
                body += [f"**{p.section_title}.**", "", sec, ""]
            body += [f"Full report: [{rel}]({rel}) (HTML alongside).", ""]
        body.append("")
    lines += rows + ["", "\"Traced\" means the number equals a value returned by a twin at "
                     "the precision quoted (allowing kilo/milli unit changes). The rest are "
                     "derived (sums, ratios, per-hectare conversions the report says it made) "
                     "or rounded, and are worth spot-checking in the full report.", ""] + body
    path = RUNS / "WALKTHROUGH.md"
    path.write_text("\n".join(lines))
    return path


# --------------------------------------------------------------------------- #
async def main_async(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("personas", nargs="*", help=f"any of {', '.join(QUESTIONS)} (default: all)")
    ap.add_argument("--backend", choices=["claude-code", "api"], default="claude-code")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--max-turns", type=int, default=40)
    ap.add_argument("--parallel", type=int, default=6)
    ap.add_argument("--summarise-only", action="store_true")
    a = ap.parse_args(argv)
    selected = a.personas or list(QUESTIONS)
    unknown = [p for p in selected if p not in QUESTIONS]
    if unknown:
        ap.error(f"unknown persona(s): {unknown}")
    if a.summarise_only:
        print(walkthrough(list(QUESTIONS)))
        return 0
    if a.backend == "claude-code" and not shutil.which("claude"):
        print("The claude CLI is needed for --backend claude-code.", file=sys.stderr)
        return 2
    async with AgentPool() as pool:                 # the prompt is built from the live agents
        system = system_prompt(pool.agents, pool.skipped)
    sem = asyncio.Semaphore(a.parallel)

    async def one(persona):
        async with sem:
            q = QUESTIONS[persona]
            out = RUNS / persona
            if out.exists():
                shutil.rmtree(out)
            out.mkdir(parents=True)
            print(f"[{persona}] started", file=sys.stderr)
            if a.backend == "api":
                meta = await run_api(persona, q, out, a.model)
            else:
                meta = await run_claude_code(persona, q, out, system, a.max_turns, a.model)
            c = check(persona, q, out, meta)
            (out / "check.json").write_text(json.dumps(c, indent=1))
            print(f"[{persona}] {'PASS' if c['passed'] else 'FAIL'}: twins {c['twins_called']}, "
                  f"{c['agent_calls']} calls, {c['seconds']} s", file=sys.stderr)
            return c

    results = await asyncio.gather(*(one(p) for p in selected))
    print(walkthrough(list(QUESTIONS)))
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
