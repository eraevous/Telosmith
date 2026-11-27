# Building and checking a manifest: `aec manifest build` and `aec manifest check`

```
aec manifest build --trust-config [--root DIR]   start ROOT's configured MCP server, build the manifest, write it
aec manifest check --trust-config [--root DIR]   build it in memory, compare with the committed file, never write
```

This is rule 3 of the accepted schema page (`docs/integrations/manifest.md`, `AEC-D-manifest-schema@3`): the manifest
is generated from the things that own the truth, then checked, so it can't drift from them by hand. This page
states the rules the two commands follow. It answers the blockers in Kate's round-12 records
(`AEC-R-manifest-rebuild-drift@2`, `-cache-policy@2`, `-collection-safety@2`, independent). It is the implementer's
account (`AEC-R-manifest-build-impl@1`); it changes nothing on the accepted page.

## What the build reads

Only ROOT's own `.aec/config.json`, its `manifest` section (a manifest under review is never a source of anything
that runs):

```json
{"version": 1,
 "manifest": {
   "path": ".aec/manifest.json",
   "tool": {"id": "demo", "name": "Demo", "description": "What the tool does."},
   "command": ["python", "-m", "demo", "mcp"],
   "pass_env": [],
   "authority": {"needs": [], "accepts": [], "grants": []},
   "runtime": {"network": "never", "model_calls": "never"},
   "other": [],
   "skills": ["skills/demo-skill"],
   "a2a": null}}
```

- `a2a` is `null` or the arguments `aec a2a card` takes: `url` (required), and optionally `binding`, `provider`,
  `streaming`, `push_notifications`, `input_modes`, `output_modes`, `documentation_url` and `skills`. Name,
  description and version come from `tool` and the server, and the authority extension from `authority`; setting
  `name`, `description`, `version` or `authority` inside `a2a` is a config error rather than being dropped silently.
  An argument `aec a2a card` doesn't take is a config error too. These refusals happen before anything is launched
  (Kate's `AEC-R-manifest-config-provenance@1`, proposed).
- `authority` takes only `needs`, `accepts` and `grants`. Any other key is a config error: the manifest has no place
  for it, so it would otherwise vanish.
- `pass_env` names environment variables the server needs. Names only; their values are never written or shown.

## Where each field comes from

The accepted page's terms are kept. Kate asked that config-derived fields not be called hand-declared.

| Kind | Fields | Source |
|---|---|---|
| generated | `sockets.mcp` (all of it except `command`), `tool.version`, `sockets.a2a.agentCard`, `sockets.skills[].name` and `.description` | the server's answers, `aec a2a card`, the skill folders' `SKILL.md` |
| config-derived | `tool.id`, `tool.name`, `tool.description`, `sockets.authority`, `sockets.skills[].path`, `sockets.mcp.command` | `manifest.*` in the config, copied (`command` is the argv the build launched) |
| hand-declared | `sockets.other`, `runtime` | `manifest.*` in the config: statements people make that nothing can derive (the accepted page's "only `other` and `runtime` are hand-declared") |

`check` compares the whole file with a fresh build, so all three kinds are compared. Hand-declared fields are also
validated by `aec manifest validate`, which the build runs on its own result before writing.

## Collection

- **One session.** One fresh server process per run, in ROOT, closed at the end.
- **Protocol.** MCP 2026-07-28 only, the revision Telosmith pins (`aec.mcp.STATELESS`, DEC-177). There is no
  `initialize` handshake in that revision. Every request carries
  `_meta["io.modelcontextprotocol/protocolVersion"] = "2026-07-28"`.
  - `server/discover` comes first. Its `supportedVersions` must include 2026-07-28 and becomes
    `mcp.protocolVersions`. Its `capabilities` becomes `mcp.capabilities`. Its
    `_meta["io.modelcontextprotocol/serverInfo"]` (name and version) becomes `mcp.serverInfo`.
  - A server that speaks only the handshake era fails collection. Out of scope here.
- **Capabilities to lists.**

  | capability | requests | manifest list |
  |---|---|---|
  | `tools` | `tools/list` | `tools` |
  | `resources` | `resources/list`, `resources/templates/list` | `resources`, `resourceTemplates` |
  | `prompts` | `prompts/list` | `prompts` |

  A list whose capability isn't advertised is `[]`, with no policy entry.
- **Pagination.** Each list follows `nextCursor` until a result has none. Pages are joined in order.
- **Limits.** 10 seconds per request, as one deadline: notifications the server sends meanwhile don't extend it. 100 pages per list.
  The deadline starts before the request is written and covers the write, so a server that stops reading its input
  can't block the build. It is checked before each message is taken, so notifications already queued can't
  outlast it.
  stdout is read as bytes: at most 8 MiB in one line and 64 MiB in the session. The session's output is everything
  the server writes until it exits: after the last answer, stdin is closed, the server is given 10 seconds to exit
  (then killed), stdout is read to its end, and an overrun anywhere in it fails the collection, as does a line after
  the last answer that isn't UTF-8 JSON, or stdout still open 10 seconds after the server exits. On POSIX the server
  runs in its own process group, which is killed at the end, so a descendant holding the pipes can't keep the build
  waiting. A pipe is closed only once its reader has stopped. Past a cap, stdout
  is still drained (and dropped) so the server can't block on a full pipe. stderr is read in chunks and discarded
  as it arrives, so it never accumulates.
- **Failures.** Exit 2 and nothing is written for any of these:
  - a cursor that isn't a non-empty string, or one already seen;
  - more than 100 pages;
  - a JSON-RPC error;
  - a result that isn't an object with `resultType: "complete"`;
  - a line that isn't JSON;
  - a line that isn't UTF-8, a line over 8 MiB, or more than 64 MiB of stdout;
  - a timeout;
  - the process exiting before it answers.
  After any failure the server process is killed rather than waited for.

## List policy

- Each list result's `ttlMs` and `cacheScope` (MCP 2026-07-28 list-result fields) go to `mcp.listPolicy.<list>`, as
  the accepted page says. Every page's values are type-checked first (`ttlMs` a non-negative integer, not a boolean
  or float; `cacheScope` a non-empty string), since `0`, `false` and `0.0` compare equal. Each key is then handled
  on its own:
  - present on every page with one value: kept;
  - present on no page: left out. No default is supplied, and absence isn't read as a value;
  - present on some pages only, or with different values on different pages: a collection failure.
- `aec manifest validate` checks the types: `ttlMs` a non-negative integer, `cacheScope` a non-empty string.
- A policy that changes, appears or disappears is drift like any other field.
- Out of scope: caching. A TTL never lets the build skip a fresh collection.
- Not verified: the mapping against the 2026-07-28 schema text itself. The accepted page says the same.

## Comparison (`check`)

- The fresh build is compared with the committed file, path by path:
  - object key order is ignored;
  - array order and length count;
  - nothing is treated as volatile, so a server whose listing changes between runs fails `check`, by design.
- Each difference is reported by JSON path and kind:
  - `added`: in the build, not in the file;
  - `removed`: in the file, not in the build (Kate: a removed field fails);
  - `changed`: different values.
- Values are never printed. Each key in a JSON path goes through the same plain-text rule as values
  (`aec.manifest._echo`), since a committed file or a server can choose its keys: a key that isn't short and plain
  shows as `[not shown]`.
- The committed file is also validated on its own (`aec manifest validate`), so a problem it has is reported even
  where the build happens to match it.
- Exit codes, for both commands:
  - 0: the same (`check`), or written (`build`);
  - 1: different, or the committed file invalid or unreadable (`check`); or the built result fails
    `aec manifest validate` (both). Collection worked in that last case; what it produced, or the config it copied,
    is what's wrong. Nothing is written;
  - 2: refused, a config problem, a collection failure, or the write failing (`build`, reported by exception type;
    the old file stays).
- `check` never writes: not on success, a difference, an invalid or unreadable file, or a refusal.
- The target path is taken from the config section the build validated, not from a second read after collection.

## Trust boundary and disclosure

- **Running config is a trust decision.** Neither command launches anything without `--trust-config`; without it,
  both exit 2 before reading the config.
  - A pull request can change `.aec/config.json`, so passing the flag means the invoker trusts that checkout's config.
  - This is not a sandbox. The command runs with the invoker's rights.
  - The config must be the repository's own file: a symlinked `.aec` or `.aec/config.json`, or one that resolves
    outside ROOT, is refused before it is read.
- **CI.** No workflow runs `check` yet. Wiring it in is a CI-policy decision for Zach.
  - A CI job on pull requests from forks would run the PR's own config.
- **The child process gets:**
  - working directory ROOT;
  - environment: `PATH`, plus `SYSTEMROOT` on Windows, plus the names in `pass_env`, and nothing else;
  - stdin and stdout: the protocol only;
  - stderr: read and dropped, never shown.
- **Diagnostics:**
  - name JSON paths and config keys;
  - show text from the server or the file only under `aec manifest validate`'s plain-text rule (`[not shown]`
    otherwise);
  - report exceptions by type, never by message;
  - pass each quoted value in a config error through the same plain-text rule;
  - never show a server's error message.
- **Before writing,** the build runs `aec manifest validate` on the whole result, which refuses the credential and
  host-path shapes it recognises. That catches recognisable shapes only (accepted page, rule 7).
- **Paths.** The manifest path and skill paths are relative to ROOT and stay inside it, symlinks included. The
  write goes to a temporary file in the same folder, then replaces the target, so a failure leaves the old file.

## Not done here

- A CI job (above).
- Handshake-era servers.
- Generating `other` or `runtime`: they are hand-declared by definition.
- Retiring `examples/manifest/telosmith.manifest.json` in favour of a built one: a follow-up, once Telosmith's own
  config gains a `manifest` section.
