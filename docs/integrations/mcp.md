# MCP: every Telosmith-based tool is reachable over the Model Context Protocol

Author: claude:aec#wake-20261120 · Reviewer: none yet (Codex on open; Kate asked for the records) · model=claude-opus-5-5

Status: **experiment** (DEC-200 build gate), DEC-256 item 5, first slice. Handoff HO-AEC-20261119-V8FC.

The point (DEC-256): a tool built with the Dev Kit connects with every other tool built with it. This slice gives
every Telosmith-based Python project an MCP server it can start with one command and extend with its own tools.

## Use it

```bash
aec mcp                       # serve ./.aec/records.jsonl over stdio
aec mcp --root PATH --records PATH/to/records.jsonl
```

An MCP client (Claude Code, Claude Desktop, any MCP host) starts it as a stdio server, for example in `.mcp.json`:

```json
{"mcpServers": {"telosmith": {"command": "aec", "args": ["mcp"]}}}
```

Built-in tools, all read-only, reading the records fresh on each call:

| Tool | What it returns |
| --- | --- |
| `records_list` | latest version of each record (or all versions), filtered by `type` or `id_prefix`, with `limit` |
| `record_get` | one record by id (latest) or `id@version`, and whether a newer version exists |
| `records_check` | the findings of `aec check` (no edge snapshot); structural only |

## Add your project's own tools

```python
from aec.mcp import ToolError, telosmith_server

srv = telosmith_server(".")          # Telosmith's record tools, plus yours

@srv.tool("deck_score", "Score a deck by name.", {"type": "object", "required": ["name"],
                                                    "properties": {"name": {"type": "string"}}})
def deck_score(args):
    if not args.get("name"):
        raise ToolError("name is required")   # reported as isError, the session goes on
    return {"name": args["name"], "score": 0}

srv.serve()
```

Or start from `McpServer(name, version)` for a server without the record tools.

## What it does and does not do

- Protocol revisions 2024-11-05, 2025-03-26, 2025-06-18 and 2025-11-25. A client asking for another revision is
  answered with the newest of these, and the client decides whether to go on (the MCP negotiation rule).
- Methods: `initialize`, `ping`, `tools/list`, `tools/call`; notifications are never answered. No resources, prompts,
  batches or HTTP transport: relay-kit's `tools/mcp_server.py` (relay-kit/mcp@2) has those for its records store.
- Record text is data, not instructions; every record result carries a notice saying so. A recorded `authored_by` or
  `decided_by` is a claim in the file, not proof of who acted.

Next slices of item 5: the A2A Agent Card, the Agent Skills folder, and the authority socket field (DEC-185). Item 6
(the compatibility test in Lydian) uses this server as one of its two sides.
