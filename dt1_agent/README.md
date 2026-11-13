# DT1 agent

A minimal agent for the digital twin orchestration experiments. It is independent of the
peatland model and exists to prove the MCP plumbing end to end.

- `dt1_server.py`: MCP server named `dt1` with one tool, `hello`, which returns
  `Hello from Claude's DT1 agent!`
- `dt1_agent.ipynb`: acts as the orchestrator. It launches the server over stdio, lists its
  tools and calls `hello`.

## Run

```bash
pip install -r dt1_agent/requirements.txt
python dt1_agent/dt1_server.py          # stdio (for orchestrators that launch it)
python dt1_agent/dt1_server.py --http   # streamable HTTP on http://127.0.0.1:8000/mcp
```

## Register with an MCP client

Claude Code: `claude mcp add dt1 -- python /path/to/dt1_agent/dt1_server.py`

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "dt1": { "command": "python", "args": ["/path/to/dt1_agent/dt1_server.py"] }
  }
}
```

## Test

```bash
pip install pytest
pytest dt1_agent
```

`test_dt1_server.py` checks that the server offers exactly one tool, `hello`, and that it returns
the greeting, both in memory and over stdio as a launched subprocess.
