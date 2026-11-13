"""DT1 agent: a minimal MCP server for the digital twin orchestration experiments.

It exposes one tool, ``hello``, that returns a fixed greeting. An orchestrator (or
any MCP client, such as Claude Desktop or Claude Code) can launch it over stdio:

    python dt1_agent/dt1_server.py

Run with ``--http`` to serve over streamable HTTP instead (default port 8000).
"""

import sys

from mcp.server.mcpserver import MCPServer

GREETING = "Hello from Claude's DT1 agent!"

server = MCPServer(
    name="dt1",
    instructions="DT1 digital twin agent. Call the 'hello' tool to check it is alive.",
    version="0.1.0",
)


@server.tool(description="Return a greeting from the DT1 agent.")
def hello() -> str:
    return GREETING


if __name__ == "__main__":
    server.run("streamable-http" if "--http" in sys.argv else "stdio")
