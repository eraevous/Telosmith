# Agent Skills: every Telosmith-based tool ships its know-how the same way

Author: claude:aec#wake-20261121-13 · Reviewer: none yet (Codex on open; Kate asked for the records) · model=claude-opus-5-5

Status: **experiment** (DEC-200 build gate), DEC-256 item 5, third slice. Handoff HO-AEC-20261119-V8FC.

The point (DEC-256): a tool built with the Dev Kit connects with every other tool built with it. DEC-177 names Agent
Skills (`SKILL.md`) as the know-how socket. This slice lets a Telosmith-based project write a skill folder and check
one against the specification, and ships a working example.

## Use it

```bash
aec skills new my-skill --description "What it does. Use when ..."   # writes skills/my-skill/SKILL.md
aec skills new my-skill --description "..." --dir .claude/skills --license MIT
aec skills check skills/            # a skill folder, or a folder of skill folders; exit 0 only when all are valid
```

`new` never overwrites. A relative `--dir` (the default `skills`) is checked component by component from the working
directory: a symlink anywhere in it, or `..`, is refused, so a link committed in a checkout can't redirect the write.
An absolute `--dir` is your explicit choice: its ancestors aren't checked, but the folder itself and the skill folder
must not be links. Values are written double-quoted, so any text is safe.

## What is checked

Against the Agent Skills specification as read on 2026-11-21 (https://agentskills.io/specification):

| Field | Rule |
| --- | --- |
| `name` | required; 1 to 64 characters; `a-z`, `0-9` and single hyphens, not at either end; equals the folder name |
| `description` | required; non-empty, at most 1024 characters |
| `license` | optional; non-empty string |
| `compatibility` | optional; 1 to 500 characters |
| `metadata` | optional; string keys to string values |
| `allowed-tools` | optional; a string (experimental upstream; its contents are not checked) |

Any other front-matter key is reported. Every problem is reported at once, one line each.

**YAML subset.** Telosmith has no runtime dependencies, so the checker reads the subset `new` writes and most skills
use: one-line `key: value` pairs (plain, single- or double-quoted) and `metadata:` followed by indented pairs (keys
plain or quoted; `new` quotes every key and value). A plain value that YAML reads as null, a boolean, a number or a
date (`null`, `true`, `yes`, `123`, `2026-11-21`) is reported: quote it when text is meant. Block
scalars (`>`, `|`), lists, flow mappings, anchors and tags are reported as outside the subset, never guessed at. A
skill that uses them may still be valid upstream; the upstream validator is `skills-ref validate`.

## Example

`examples/skills/telosmith-records/` is a real skill: how an agent reads and checks a repository's Telosmith records
before changing code. `tests/test_agent_skills.py` checks it stays valid.

## Not covered

Running a skill, checking its `scripts/`, the meaning of `allowed-tools`, and listing skills in the A2A card or over
MCP (item 7, the manifest schema, is where the sockets meet). Records: `AEC-R-agent-skills-impl@1` (implementer).
