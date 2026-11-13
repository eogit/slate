"""Tests for the DT1 MCP server: run with `pytest dt1_agent`."""

import sys
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters

SERVER = Path(__file__).with_name("dt1_server.py")
EXPECTED = "Hello from Claude's DT1 agent!"


async def _query(target):
    async with Client(target) as client:
        names = [t.name for t in (await client.list_tools()).tools]
        result = await client.call_tool("hello")
        return names, result


def test_hello_in_memory():
    sys.path.insert(0, str(SERVER.parent))
    from dt1_server import server

    names, result = anyio.run(_query, server)
    assert names == ["hello"]
    assert not result.is_error
    assert result.content[0].text == EXPECTED


def test_hello_over_stdio():
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    names, result = anyio.run(_query, params)
    assert names == ["hello"]
    assert result.content[0].text == EXPECTED
