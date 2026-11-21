# Telosmith as the base for every Python tool (DEC-256): plan and the config-file decision

Author: claude:aec#wake-20261119-23 · Reviewer: none yet (Kate asked for the item-1 records; Codex on open) · model=claude-opus-5-5

Status: **decided: `.aec/config.json`** (`AEC-D-repo-config@2`, accepted). Zach, on Telosmith#94, 2026-11-20T14:49Z:
"Decided as aec/config.json". Read as `.aec/config.json`, the JSON option below (the leading dot is the `.aec/` folder
every repository has). The rest of this page is the proposal as written; where it says TOML, the decision replaces it.
Handoff: HO-AEC-20261119-V8FC (relay-kit-private), authorized by DEC-256 (Zach, 2026-11-19 15:21 and 15:33 CT).

## What this is for

The outcome Zach asked for: **a tool built with the Dev Kit connects with every other tool built with it.** For Python,
that means starting from Telosmith (or instantiating it), so the connections (MCP, A2A, Agent Skills, the authority
socket) come with the project. "Compatible" will mean one thing: a test in Lydian where two separately built
Telosmith-based tools discover and call each other, passing in CI (item 6).

Getting there has two parts. Part A removes what instantiating repositories copy by hand today (hook text, snippets,
AGENTS.md governance prose), behind one per-repository config. Part B adds the sockets and the test that proves them.

## Decided: `.aec/config.json`

What changes from the proposal below: the file is JSON, read with the standard-library `json` module on every
supported Python (3.10 included), so there is no 3.10 error path and the Python floor question no longer bears on
this work. JSON has no comments; the item-1 PR will propose a `_doc` key for prose (as in `tools/aec_upstream.json`).
Unchanged: the file lives in `.aec/`, a missing file means today's defaults, unknown keys are errors.

## The call as it was put to Zach: where the per-repository config lives

**Recommendation: `.aec/config.toml`.** Not `[tool.telosmith]` in `pyproject.toml`.

Evidence (GitHub tree listing, 2026-11-19T23:20Z, the 15 repositories this lane can read):

| Has `.aec/` | Has `pyproject.toml` | Repositories |
|---|---|---|
| yes | yes | Telosmith, relay-kit, fathom, data-guide, mtg, anamnesis, cognitive-scaffolding |
| yes | **no** | relay-kit-private, qat-kits, kairos, kairos-cockpit, today, prospero |

Six of the thirteen `.aec/` repositories have no `pyproject.toml`; several are records or coordination repositories,
not Python packages. `[tool.telosmith]` would make them grow a packaging file just to hold Telosmith settings, or need
a second location anyway. `.aec/` already holds everything else Telosmith owns (records, `sources.json`).

What it costs:
- **Python 3.10 has no TOML reader in the standard library** (`tomllib` is 3.11+), and Telosmith has no runtime
  dependencies. 3.10 is the package floor and is still in CI's matrix. Proposed handling: without a config file, every
  command uses today's defaults on every Python; with one, 3.11+ reads it and 3.10 stops with a message naming the file
  and the fix (use Python 3.11+). No hand-written TOML parser.
- A separate, later call (not made here): Python 3.10 reached end of life in October 2026. Raising the floor to 3.11
  would remove the 3.10 message entirely. It changes who can install Telosmith, so it is Zach's, and it can wait.
- Two Telosmith files under `.aec/` that both configure things (`sources.json` and `config.toml`). The config does not
  absorb `sources.json` in this work; that is a possible later consolidation, listed under "not decided".

Considered and not recommended:
- `[tool.telosmith]` in `pyproject.toml`: the Python norm, and one file fewer for packages; fails the six repositories
  above.
- `.aec/config.json`: readable on 3.10 with the standard library, and consistent with `sources.json`; but no comments,
  and the handoff named the two TOML options. If Zach prefers it, the plan below is unchanged except the file name.

## What the config covers (item 1)

From the handoff: the records path and source roots; which checks run; hook strictness; the governance options that
`aec agents` and `aec init` render (items 3 and 4). Every key has a default equal to today's behaviour, so a repository
without the file behaves exactly as it does now. Unknown keys are an error (a typo shouldn't silently do nothing).
The exact keys come with the item-1 PR and the semantic maintainer's records, not with this note.

## Order of work (one PR each, from main, no stacking)

1. **Config** (`.aec/config.json` loader, defaults, `aec config show`). Decided; Kate's records first.
2. **`aec hook`** as a command: already built as `aec hook project` in Telosmith#92 (ready, waiting on Zach). Reading
   strictness from the config waits for #92's merge (no stacking).
3. **`aec agents`**: renders the shared governance part of AGENTS.md between markers, with a glossary pointer (DEC-255);
   the repository's own sections are never touched.
4. **`aec init` renders snippets from the config** instead of committing `.aec/snippets/`; follow-up PRs remove the
   committed copies, one repository at a time.
5. **Sockets**: MCP server skeleton (building on relay-kit's `tools/mcp_server.py`), A2A Agent Card, an Agent Skills
   folder, and the authority socket (DEC-185) as a declared field. Item 5 does not depend on the config and can start in
   parallel with items 3 and 4 (see the dissent review).
6. **Compatibility test in Lydian**: two separately built tools discover and call each other through MCP and an A2A task.
7. **Manifest schema proposal** (Agent Card plus MCP listings), the part DEC-177 left with R&D: a proposed decision.
   Proposed in [manifest.md](manifest.md) (`AEC-D-manifest-schema@1`, waiting on Zach).

## Not decided here

- The Python floor (above). The file's exact keys (item-1 PR). Whether `sources.json` folds into the config.
- Anything in HO-LYD-20261119-ZA3J (the CI move to Lydian) and the Dev Kit's name.

## Dissent review (AGENTS.md Drift: a new subsystem and a module's responsibility change)

1. **Which purpose or assumption might this violate?** `AEC-P0` and the constitution keep Telosmith standard-library
   only and Python 3.10+. A TOML config strains that (3.10 can't read it). Separately, the handoff's own warning: Zach
   rejected "declares and checks contracts" as the point; the point is the connection. Part A first risks spending the
   effort on machinery (AGENTS.md Drift trigger) before the outcome Zach named.
2. **Evidence:** the survey above; `tomllib` is 3.11+; CI tests 3.10. Part A is four items of consolidation; Part B's
   compatibility test is the only thing that shows the outcome.
3. **Counter-evidence:** a missing config file keeps every Python working, so the 3.10 strain falls only on
   repositories that opt in; the hook re-roll cost is measured (21 of about 258 commits, 12 to 17 November), so Part A
   pays for itself; and the MCP skeleton doesn't need the config, so the two parts needn't be sequential.
4. **If the concern is right:** Part B arrives late and the README still can't show the outcome. Mitigation taken:
   item 5 is marked parallel, not last.
5. **Test, escalate, decide:** Zach decides the file location (this PR) and, later, the floor. The item-1 PR carries a
   test that a 3.10 run with a config file fails with the named message and without one matches today's output.

QAT: stress-test (installed skill, 2026-10-15 upload) on the plan: concerns taken: Part B sequencing (item 5 made
parallel), the JSON alternative stated rather than dropped, the 3.10 floor split out as its own later call; concern
noted and not acted on: two config files under `.aec/` (deferred, listed as not decided).
