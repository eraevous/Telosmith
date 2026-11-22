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

- Protocol revisions 2024-11-05, 2025-03-26, 2025-06-18 and 2025-11-25 through the `initialize` handshake. A
  client asking for another revision there is answered with the newest of these, and the client decides whether to
  go on (the MCP negotiation rule).
- Protocol revision 2026-07-28 (stateless, SEP-2575), a subset of it, on the same server: no handshake. Every request names its
  revision in `params._meta["io.modelcontextprotocol/protocolVersion"]`; that key is what tells the two eras apart,
  so a request without it is handled as before.
  - `server/discover` answers `supportedVersions` (`["2026-07-28"]` only: the handshake revisions can't be chosen
    through `_meta`), `capabilities`, `instructions` and the cache policy `ttlMs: 0` with the server's `cacheScope`.
  - The era is chosen for each request on its own, never latched for the connection. Reading a request without the
    key as the earlier era is a compatibility exception: SEP-2575 says servers should reject a missing version.
  - `tools/list` adds the cache policy `ttlMs` and `cacheScope` (`McpServer(..., list_ttl_ms=0,
    cache_scope="public")` by default: no reuse promised; the list holds nothing user-specific).
  - Every result carries `resultType: "complete"` and the server's name and version in
    `_meta["io.modelcontextprotocol/serverInfo"]`.
  - Another revision in that key gets error `-32022` with `data: {"supported": [...], "requested": "..."}`; a
    non-string revision or a non-object `clientCapabilities` gets `-32602`; `ping` and `initialize` get `-32601`
    in this revision (it removed them).
  - Not done: a missing `clientCapabilities` is accepted (read as none), the server never needs a client capability
    so `-32021` never arises, and `clientInfo` is not read. `subscriptions/listen`, logging and multi-round
    `input_required` results are not implemented (a tools-only server doesn't need them).
  - Source: the 2026-07-28 changelog and SEP-2575 on modelcontextprotocol.io, read 2026-11-21 through a summary; no
    independent 2026-07-28 client has run against it yet (item 6).
- Arguments are checked against the tool's `inputSchema` before the handler runs: top-level `required`, and per
  property `type`, `enum` and `minimum` (plus `additionalProperties: false` when declared). A bad call comes back as
  a result with `isError`, as MCP 2025-11-25 asks, so the caller can correct it; the handler never sees it. Richer
  schema rules (nested objects, patterns) stay the handler's job.
- A tool's unexpected exception comes back as `<tool> failed: internal error (<ExceptionType>)`. Its message can
  carry paths, so it goes to the server's stderr, not to the client.
- Methods: `initialize`, `ping`, `tools/list`, `tools/call`, and `server/discover` for 2026-07-28; notifications are never answered. No resources, prompts,
  batches or HTTP transport: relay-kit's `tools/mcp_server.py` (relay-kit/mcp@2) has those for its records store.
- Record text is data, not instructions; every record result carries a notice saying so. A recorded `authored_by` or
  `decided_by` is a claim in the file, not proof of who acted.

Next slices of item 5: the A2A Agent Card, the Agent Skills folder, and the authority socket field (DEC-185). Item 6
(the compatibility test in Lydian) uses this server as one of its two sides.
