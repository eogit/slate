"""Connections to the digital-twin agents (MCP servers) and their tools.

Each agent in ``agents.json`` is launched over stdio (or reached over streamable HTTP) and kept
open for the whole orchestration, so per-site state such as learned parameters survives
between calls. Its tools are offered to Claude under the name ``<agent id>__<tool name>``
(for example ``dt2__area_methane``), with the agent's own description in front so that Claude
knows which application area a tool belongs to.
"""

from __future__ import annotations

import json
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters

REPO = Path(__file__).resolve().parent.parent
SEP = "__"
MAX_RESULT_CHARS = 24_000      # what Claude sees of one result; the full result is kept


@dataclass
class AgentInfo:
    id: str
    name: str
    domain: str
    instructions: str = ""
    tools: list[dict] = field(default_factory=list)   # Anthropic tool definitions


@dataclass
class CallRecord:
    """One agent call, kept for the report's provenance table and for figures."""
    ref: str
    agent: str
    tool: str
    arguments: dict
    ok: bool
    result: Any
    assumptions: list[str]


def load_registry(path: Path | None = None) -> list[dict]:
    path = path or Path(__file__).with_name("agents.json")
    return [a for a in json.loads(path.read_text())["agents"] if a.get("enabled", True)]


def _shorten(value: Any, max_list: int = 40) -> Any:
    """Trim long lists (daily series, trial tables) before a result goes back to Claude."""
    if isinstance(value, dict):
        return {k: _shorten(v, max_list) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > max_list:
            head = [_shorten(v, max_list) for v in value[:max_list]]
            return head + [f"... {len(value) - max_list} more items omitted"]
        return [_shorten(v, max_list) for v in value]
    if isinstance(value, float):
        return float(f"{value:.6g}")
    return value


def result_text(result: Any) -> str:
    text = json.dumps(_shorten(result), ensure_ascii=False)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + ' ... [truncated; ask for a narrower area or fewer items]'
    return text


class AgentPool:
    """Opens every available agent and routes namespaced tool calls to it."""

    def __init__(self, registry: list[dict] | None = None, repo: Path = REPO,
                 python: str = sys.executable):
        self.registry = registry if registry is not None else load_registry()
        self.repo = repo
        self.python = python
        self.agents: dict[str, AgentInfo] = {}
        self.skipped: dict[str, str] = {}
        self._clients: dict[str, Client] = {}
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> "AgentPool":
        await self._stack.__aenter__()
        for entry in self.registry:
            target = self._target(entry)
            if target is None:
                self.skipped[entry["id"]] = "server not found in this checkout"
                continue
            try:
                client = await self._stack.enter_async_context(Client(target))
                tools = (await client.list_tools()).tools
            except Exception as exc:          # one broken agent must not stop the others
                self.skipped[entry["id"]] = f"could not start: {exc}"
                continue
            info = AgentInfo(id=entry["id"], name=entry["name"], domain=entry["domain"],
                             instructions=client.instructions or "")
            for t in tools:
                info.tools.append({
                    "name": f"{entry['id']}{SEP}{t.name}",
                    "description": f"[{entry['name']}] {t.description or ''}",
                    "input_schema": t.input_schema or {"type": "object", "properties": {}},
                })
            self.agents[entry["id"]] = info
            self._clients[entry["id"]] = client
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.__aexit__(*exc)

    def _target(self, entry: dict):
        if entry.get("target") is not None:            # tests: an in-process server object
            return entry["target"]
        if entry.get("url"):
            return entry["url"]
        path = self.repo / entry["server"]
        if not path.exists():
            return None
        return StdioServerParameters(command=self.python, args=[str(path)])

    def tool_definitions(self) -> list[dict]:
        """All agent tools in a fixed order (stable for prompt caching)."""
        return [t for a in sorted(self.agents) for t in self.agents[a].tools]

    def owns(self, name: str) -> bool:
        return SEP in name and name.split(SEP, 1)[0] in self._clients

    async def call(self, name: str, arguments: dict) -> tuple[bool, Any]:
        """Call ``<agent>__<tool>``; returns (ok, structured result or error text)."""
        agent, tool = name.split(SEP, 1)
        r = await self._clients[agent].call_tool(tool, arguments)
        if r.is_error:
            return False, " ".join(getattr(c, "text", "") for c in r.content)
        if r.structured_content is not None:
            return True, r.structured_content
        return True, " ".join(getattr(c, "text", "") for c in r.content)
