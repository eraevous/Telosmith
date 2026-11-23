# Tool manifest schema (Agent Card plus MCP listings)

Author: claude:aec#wake-20261121-21 · Reviewer: none yet (Codex on open; Kate asked for the records) · model=claude-opus-5-5

Status: **decided** (`AEC-D-manifest-schema@3`, accepted). Zach, on Telosmith#103, 2026-11-22T20:41:53Z (comment
7085475083): "Option B is good. The path proposed is acceptable. put network use and model use in v1, with room for
never, optional, required, and unknown. leave dependency lists to the tool's existing package files rather than
maintaining a second list." Kate's round-9 records `AEC-R-manifest-*` (`independent`) still apply. DEC-256 item 7,
handoff HO-AEC-20261119-V8FC. `aec manifest validate` checks a manifest against this page (below); `aec manifest
build|check`, which start the server and compare a fresh build, come in a later PR.

## What it is for

A tool built with the Dev Kit connects with every other one (DEC-256). The manifest is the one file another tool,
an agent or a reviewer reads to learn **what sockets this tool has and what each one looks like on the wire**,
without running it. It does not replace the live sockets: a client still discovers an MCP server over MCP and an
agent through its A2A Agent Card. The manifest is the committed, checkable copy of those answers, plus the two things
no standard carries yet: the authority declaration (DEC-185) and the sockets that aren't MCP or A2A yet.

## The proposal

One JSON file per tool, `telosmith.manifest/1.0`. Worked example: [`examples/manifest/telosmith.manifest.json`](../../examples/manifest/telosmith.manifest.json)
(Telosmith itself; its `mcp` section is the real `tools/list` output of `aec mcp` on 2026-11-21, the rest written by
hand until `aec manifest build` exists).

```json
{
  "manifest": "telosmith.manifest/1.0",
  "tool":    {"id": "...", "name": "...", "version": "...", "description": "..."},
  "sockets": {
    "mcp":       {"transport": "stdio", "command": ["..."], "protocolVersions": ["..."], "serverInfo": {}, "capabilities": {},
                  "tools": [], "resources": [], "resourceTemplates": [], "prompts": [], "listPolicy": {}},
    "a2a":       {"agentCard": {}},
    "skills":    [{"path": "...", "name": "...", "description": "..."}],
    "authority": {"needs": [], "accepts": [], "grants": [], "protocol": "undecided (DEC-185)"},
    "other":     [{"id": "...", "kind": "...", "direction": "in|out", "location": "...", "planned": "..."}]
  },
  "runtime": {"network": "never", "model_calls": "never"}
}
```

**Rules**

1. **Each standard's section holds that standard's own objects, unchanged.** `mcp.tools` is the `tools` array of a
   `tools/list` result, field for field; `a2a.agentCard` is an A2A 1.0 Agent Card as `aec a2a card` writes it;
   `skills` points at `SKILL.md` folders that pass `aec skills check`. Telosmith owns only the envelope, so nothing
   translates one standard into another and nothing can be lost in that translation.
2. **Every socket key is present, with one empty form each:** `mcp` and `a2a` are `null` when the tool doesn't speak
   them; `skills` and `other` are `[]`; `authority` is always an object (empty lists inside). An absent key is an
   error, so "we don't speak A2A" is a statement in the file, not something a reader infers from a gap.
3. **Generated, then checked, not hand-written** (after acceptance, a follow-up PR): `aec manifest build` starts the
   tool's MCP server and copies its listings, builds the card, reads the skill folders and takes `tool`, `authority`
   and `runtime` from `.aec/config.json`. `aec manifest check` rebuilds and reports any difference, field by field,
   in CI. Key order inside objects doesn't count; array order does (MCP 2026-07-28 asks servers for a deterministic
   tool order). The build follows `nextCursor` to the end of every list; a failed or incomplete collection is an
   error, never a clean result. This is
   the lesson from October in this repository's AGENTS.md: a copy that something downstream maintains by hand drifts
   from the thing that owns the truth. Only `other` and `runtime` are hand-declared.
4. **One authority declaration.** `sockets.authority` uses the fields of the authority extension already in
   Telosmith#100 (`needs`, `accepts`, `grants`, `protocol`). When `a2a` is present, the card must carry the
   extension whose `uri` is `aec.a2a.AUTHORITY_EXTENSION_URI`, and its `params` must equal this object as JSON
   (no grant is written `"grants": []`). `protocol` stays `undecided (DEC-185)` and the declaration grants nothing, as in
   `docs/integrations/authority-socket.md`.
5. **Names agree.** `tool.version` equals `mcp.serverInfo.version` and, when present, the card's `version`.
6. **`other` is transitional.** Folder, file and CLI sockets that aren't MCP or A2A yet (Prospero's content folder,
   say) are listed with `kind`, `direction`, `location` and `planned` (the standard socket they will become). A
   checker reports them as transitional, never as errors. They are free text: nothing can call them.
7. **No secrets, no environment; the manifest never runs anything.** `mcp.command` is an argv list with no
   environment values, and the manifest never carries tokens, URLs with credentials or host paths. Validating a
   manifest never launches its `command`: build and check launch the command named in the repository's own
   `.aec/config.json`, so a manifest under review can't make the checker run something. A schema check can't prove a
   server's output holds no secret; the build refuses environment-shaped values it can recognise, and that is all.
8. **Versioning.** `manifest` is `telosmith.manifest/<major>.<minor>`, starting at `1.0`. The unknown-key rule
   covers the objects Telosmith owns (the envelope, `tool`, `skills` entries, `authority`, `other`, `runtime`) and is
   strict there, as in `.aec/config.json`; embedded MCP and A2A objects follow their own pinned schemas and may carry
   fields Telosmith doesn't know. Adding a Telosmith-owned key is a new minor: a checker reads every minor up to its
   own and refuses a newer one with a message naming both versions. Removing or renaming a key, or changing what one
   means, is a new major. This is also the contract-version policy Kate asked for before item 6
   (round 2): the built-in MCP tool names and shapes in `mcp.tools` become part of what a `/1` manifest promises.

9. **Runtime (decided).** `runtime` has exactly two keys, `network` and `model_calls`, each one of `never`,
   `optional`, `required` or `unknown`: whether the tool reaches the network, and whether it calls a language model,
   never, only when the caller turns it on, always, or not established. `unknown` is an honest answer, not a default
   to hide behind; a checker accepts it and lists it. There is no dependency list: the tool's own package files
   (`pyproject.toml`, `package.json` and the like) are the single source, so the manifest can't disagree with them.

## Checking a manifest: `aec manifest validate`

```
aec manifest validate FILE [--root DIR]
```

Exit 0 when FILE is a valid `telosmith.manifest/1.0` manifest, else 1 with each problem on stderr. It reads the file
(and, with `--root`, the skill folders it names) and runs nothing: not the manifest's `mcp.command`, not the
repository's. It checks rules 1 to 9 as far as a file can show them:

- exact keys in every object Telosmith owns (the envelope, `tool`, `sockets`, the `mcp` and `a2a` wrappers,
  `listPolicy`, `skills` and `other` entries, `authority`, `runtime`); MCP and A2A objects inside may carry more;
- every socket key present, in its one empty form; the version is major 1 and a minor this checker knows;
- the card passes `aec a2a check`, carries the authority extension exactly once (an empty declaration too), and its
  params equal `sockets.authority`; `protocol` is the placeholder; versions agree; `runtime` values are one of four;
- each MCP tool has a `name` and an `inputSchema`; each `listPolicy` entry has a non-negative integer `ttlMs` and a
  non-empty `cacheScope` when present;
- no credential-shaped string anywhere, keys included (tokens of common shapes, URLs with a password, assignments
  such as `TOKEN=` or `API_TOKEN="..."`), and no host paths in `command` (an `--option=/abs/path` value included),
  skill paths or `other` locations; no control characters in skill paths. A problem names where, never the value:
  input values are redacted before they are formatted, and the version string is never echoed;
- with `--root`, each skill folder passes `aec skills check` and its name and description equal the manifest's.

Printed as notes, not problems: `other` sockets (transitional), `unknown` runtime answers, and declared grants
(nothing is granted while the protocol is undecided). Not checked here: whether the file matches what the server and
builders produce now (rule 3). That is `aec manifest check`.

## Where it lives

Default `.aec/manifest.json`, beside the records and the config. A repository with several tools writes
`.aec/manifests/<tool id>.json` instead. The path becomes a config key in the build PR. Prospero's provisional file
lives inside its package (`prospero/packet/manifest.json`); migrating it is a follow-up in that repository, not part
of this decision.

## Prospero's provisional manifest, mapped

| Prospero today (`kairos.tool-manifest.provisional`) | This proposal |
|---|---|
| `tool`, `version`, `purpose` | `tool.id`, `tool.version`, `tool.description` |
| `sockets.information_in` (a content folder, MCP planned) | `sockets.other` (kind folder, direction in, `planned`: MCP resource) until it is an MCP resource, then `mcp.resources` |
| `sockets.information_out` (packets, decisions, history, review sheet) | `sockets.other` (direction out); the read-only `history` report is the likeliest first MCP tool |
| `sockets.services`, `communication` | `mcp.tools`, `a2a` (`null` today) |
| `sockets.know_how` | `skills` |
| `sockets.authority` (`needs`, `grants`, `note`) | `sockets.authority` (`needs`, `accepts`, `grants`, `protocol`); the note becomes the authority extension's description |
| `network`, `model_calls` (booleans) | `runtime.network`, `runtime.model_calls` (`never` for `false`) |
| `dependencies` | dropped: the tool's own package files (`pyproject.toml` and the like) are the list |

DEC-177's five socket kinds (information in and out, services, communication, know-how) plus DEC-185's authority are
all covered, but by standard rather than by kind: information and services are both MCP, communication is A2A.

## Options weighed

QAT: truth-weight (installed skill, 2026-10-15 upload) on A versus B, by hand against this page's evidence.

| | A. The Agent Card **is** the manifest | **B. An envelope holding each standard's objects (recommended)** | C. Separate files, no envelope |
|---|---|---|---|
| What it is | MCP listings, skills and authority ride as A2A card extensions | the shape above | `agent-card.json`, `mcp-tools.json`, skills folder, authority file side by side |
| Tools with no A2A endpoint | **fails**: a 1.0 card requires `supportedInterfaces` with a URL; Prospero and Telosmith today have none | `"a2a": null` | fine |
| One place to read | yes | yes | no; the authority and runtime parts have no home |
| Standards kept verbatim | MCP objects nested inside a card extension's `params` | yes | yes |
| Served as-is to A2A clients | yes | no (serve `a2a.agentCard` from it) | yes |

A fits the handoff's wording most literally but makes every tool pretend to be an A2A agent. C keeps the standards
pure but leaves authority without a socket, which DEC-185 rules out. B is the recommendation; the card still exists,
inside it, and is what gets served.

## Found while writing this: MCP 2026-07-28

DEC-177 names MCP spec 2026-07-28. When this page was written, `aec mcp` (Telosmith#95) negotiated 2024-11-05 to
2025-11-25 only; Telosmith#104 (merged 2026-11-22) adds 2026-07-28 beside them. Read on
2026-11-21 from the 2026-07-28 changelog (through a summary): the `initialize` handshake and sessions are removed;
a server MUST implement `server/discover`; list results carry `ttlMs` and `cacheScope`; results carry `resultType`;
`ping` is removed; Roots, Sampling and Logging are deprecated. Effects:
- On this proposal: `mcp.protocolVersions` and `mcp.capabilities` are where a 2026-07-28 server's `server/discover`
  answer goes; `mcp.tools` stays the `tools` array (the Tool object's fields weren't listed as changed). A list
  result's `ttlMs` and `cacheScope` are the server's declared policy, not noise: they are kept per list in
  `mcp.listPolicy` (`{"tools": {"ttlMs": ..., "cacheScope": ...}}`) and a change is drift (Kate, round 9). Not
  verified against the 2026-07-28 schema.
- Separately: `aec mcp` needs 2026-07-28 support before item 6 can claim compatibility with current clients. That's
  a follow-up within item 5, not this decision.

## Not decided here

The authority protocol (DEC-185, DEC-197); budgets, provenance, model routing and recipes (DEC-177 left them to R&D);
signing the manifest (DEC-178); serving it over HTTP; the build and check commands' exact flags.

## Dissent review (AGENTS.md Drift: a proposed new subsystem)

QAT: stress-test (installed skill, 2026-10-15 upload), by hand. Concerns 1 and 3 taken, 2 answered.
1. *Purpose risk:* the manifest becomes a second source of truth for the MCP surface. Taken: rule 3 (generated and
   checked), and only `other` and `runtime` are hand-written.
2. *Evidence of need:* one tool (Prospero) has a manifest today. Counter: DEC-177 requires one for every new tool,
   and item 6's test needs a fixed thing to test against. A schema written now from one example may misfit the second;
   `/1` with a cheap `/2` path is the hedge.
3. *If wrong:* a tool's declared authority is read as a grant. Taken: rule 4 repeats that it grants nothing, and the
   checker keeps `protocol` fixed until Zach adopts one.
4. *Decided by Zach (2026-11-22):* option B; the location; `runtime` in `/1` as network and model use only, no
   dependency list.
