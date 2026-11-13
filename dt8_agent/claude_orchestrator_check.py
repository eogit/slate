"""Use a headless Claude Code agent as the orchestrator of DT8 and check its answer.

The agent gets only the DT8 MCP server and a plain-language question. The script records every
tool call the agent makes, checks each ghg_balance result against the peatland model run
directly with the same arguments, and checks that the agent's final answer quotes the drained
and scenario net balances. Needs the `claude` CLI, signed in; not part of the pytest suite.

    python dt8_agent/claude_orchestrator_check.py [--out run.json]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_dt8_end_to_end import GASES, reference  # noqa: E402

QUESTION = (
    "You are an orchestrator for a land-use digital twin. Use the dt8 peatland agent to answer: "
    "what are the annual CO2, CH4 and N2O emissions of a potato field on drained East Anglian fen "
    "peat, and how do they change if the mean water table is raised to 30 cm and fertiliser is "
    "cut to 100 kg N/ha? Give each gas in its own units and in t CO2e/ha/yr, and the net balance.")


def _parse(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def run(out: Path | None) -> int:
    if not shutil.which("claude"):
        print("claude CLI not found")
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "mcp.json"
        cfg.write_text(json.dumps({"mcpServers": {"dt8": {
            "command": sys.executable, "args": [str(HERE / "dt8_server.py")]}}}))
        proc = subprocess.run(
            ["claude", "-p", QUESTION, "--mcp-config", str(cfg), "--strict-mcp-config",
             "--allowedTools", "mcp__dt8__*", "--output-format", "stream-json", "--verbose",
             "--max-turns", "10"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=600, cwd=tmp)
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
    nets = []
    for i, (name, args) in calls.items():
        print(f"call {name} {json.dumps(args)}")
        if name != "mcp__dt8__ghg_balance" or not (results.get(i) or "").startswith("{"):
            continue
        got = json.loads(results[i])
        exp = reference(**{k: v for k, v in args.items() if k != "site"})
        bad = [k for k in GASES if abs(got[k] - exp[k]) > 1e-9 * max(1.0, abs(exp[k]))]
        print("   all three gases match the model" if not bad else f"   MISMATCH {bad}")
        ok &= not bad
        nets.append(exp["net_t_co2e_ha_yr"])
    answer = (final or {}).get("result", "")
    quoted = [n for n in nets if f"{n:.1f}" in answer or f"{n:.2f}" in answer]
    print(f"ghg_balance calls: {len(nets)}; net balances quoted in the answer: {len(quoted)}")
    ok &= len(nets) >= 2 and len(quoted) == len(nets)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    sys.exit(run(ap.parse_args().out))
