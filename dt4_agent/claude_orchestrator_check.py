"""Use a headless Claude Code agent as the orchestrator of DT4 and check its answer.

The agent gets only the DT4 MCP server and a plain-language question. The script records every
tool call the agent makes and checks each ``get_agb``, ``management_scenario``,
``simulate_stand`` and ``validate`` result it received against the same tool run in this
process with the same arguments (the end-to-end tests pin those to the ``forest`` package). It then checks that the
agent's final answer quotes the 2024 AGB and names the best regime for carbon of each model.
Needs the `claude` CLI, signed in; not part of the pytest suite.

    python dt4_agent/claude_orchestrator_check.py [--out run.json]
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

QUESTION = (
    "You are an orchestrator for a land-use digital twin. Use the dt4 forest biomass agent to "
    "answer: how much above-ground biomass does Kielder Forest hold in 2024 according to ESA "
    "Biomass CCI v7, with its uncertainty? Over the next 40 years, which management regime "
    "removes the most CO2 from the atmosphere for a typical Kielder stand, according to the "
    "yield-curve model and according to 3-PG? And which of the two growth models predicted the "
    "2018-2024 CCI hold-out years better? Quote the numbers.")


def _parse(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def _close(a, b, rel=1e-9):
    if isinstance(a, dict) and isinstance(b, dict):
        return all(_close(a[k], b[k], rel) for k in b if k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close(x, y, rel) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=rel, abs_tol=1e-9)
    return a == b


def _direct(name, args):
    """The same tool run in this process (in-memory MCP client, no subprocess)."""
    import anyio
    from mcp import Client

    import dt4_server

    async def go():
        async with Client(dt4_server.server) as client:
            return (await client.call_tool(name, args)).structured_content

    return anyio.run(go)


def run(out: Path | None) -> int:
    if not shutil.which("claude"):
        print("claude CLI not found")
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "mcp.json"
        cfg.write_text(json.dumps({"mcpServers": {"dt4": {
            "command": sys.executable, "args": [str(HERE / "dt4_server.py")]}}}))
        proc = subprocess.run(
            ["claude", "-p", QUESTION, "--mcp-config", str(cfg), "--strict-mcp-config",
             "--allowedTools", "mcp__dt4__*", "--output-format", "stream-json", "--verbose",
             "--max-turns", "12"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=900, cwd=tmp)
    events = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
    calls, results, final = {}, {}, None
    for ev in events:
        content = ev.get("message", {}).get("content", [])
        for c in content if isinstance(content, list) else []:
            if c.get("type") == "tool_use":
                calls[c["id"]] = (c["name"], c.get("input", {}))
            elif c.get("type") == "tool_result":
                body = c.get("content")
                if isinstance(body, list):
                    body = "".join(x.get("text", "") for x in body if x.get("type") == "text")
                results[c["tool_use_id"]] = body
        if ev.get("type") == "result":
            final = ev
    if out:
        out.write_text(json.dumps({"question": QUESTION, "tool_calls": [
            {"tool": n, "arguments": a, "result": _parse(results.get(i))}
            for i, (n, a) in calls.items()], "answer": final and final.get("result")}, indent=2))

    ok = final is not None and not final.get("is_error")
    agb_values, best = [], {}
    checked = 0
    for i, (name, args) in calls.items():
        tool = name.removeprefix("mcp__dt4__")
        print(f"call {tool} {json.dumps(args)}")
        body = results.get(i) or ""
        if not body.startswith("{"):
            continue
        got = json.loads(body)
        if tool in ("get_agb", "management_scenario", "simulate_stand", "validate"):
            exp = _direct(tool, args)
            match = _close(got, exp)
            print("   matches DT4 run directly" if match else "   MISMATCH")
            ok &= match
            checked += 1
        if tool == "get_agb" and args.get("year") == 2024 and not args.get("area"):
            agb_values.append(got["agb_mean_mg_ha"])
        if tool == "management_scenario":
            best.update(got["best_for_carbon"])
    answer = (final or {}).get("result", "") or ""
    quoted = any(f"{v:.0f}" in answer or f"{v:.1f}" in answer for v in agb_values)
    regimes = all(r.replace("_", " ") in answer.replace("_", " ") or r in answer
                  for r in best.values())
    print(f"checked tool results: {checked}; 2024 AGB quoted: {quoted}; "
          f"best regimes named: {regimes} ({best})")
    ok &= checked >= 2 and bool(agb_values) and quoted and bool(best) and regimes
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    sys.exit(run(ap.parse_args().out))
