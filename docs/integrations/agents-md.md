# The shared part of AGENTS.md: `aec agents`

Author: claude:aec#wake-20261121-17 · Reviewer: none yet (Codex on open; Kate asked for the records) · model=claude-opus-5-5

DEC-256 item 4. Seven Telosmith-based repositories restated the same governance ideas in their AGENTS.md (what to read
first, who decides what, which files are append-only, the hard rules, run and drift), each in different words.
`aec agents` writes that part once, from `.aec/config.json`, so every repository says the same thing in the same terms,
and keeps only its own sections by hand.

## Commands

- `aec agents show [--repo ROOT]`: print the block.
- `aec agents write [--repo ROOT] [--file AGENTS.md] [--append]`: put the block between the two marker lines in the
  file. Everything outside the markers stays byte for byte. A file without markers, or a missing file, is refused
  unless `--append`, which adds the block at the end (or creates the file). A second run with nothing changed doesn't
  rewrite the file.
- `aec agents check [--repo ROOT] [--file AGENTS.md]`: exit 0 only when the file holds the block exactly as it renders
  now; 1 when it's missing or stale. Meant for CI.

To adopt it, put these two lines where the shared part belongs, delete the hand-written text it replaces, and run
`aec agents write`:

```
<!-- telosmith:agents:begin -->
<!-- telosmith:agents:end -->
```

The begin line may be short; `write` replaces it with the full one, which says the block is generated.

## What it renders

A `## Shared governance (Telosmith)` section with: read first (the purpose records in `records`, then
`agents.read_first` in order; the purpose wins over a spec or plan until the owner decides otherwise); authority
(domain truth is cited, design intent is `agents.owner`'s, operational rules decide how, not what); records and
ledgers (`records`, then `agents.ledgers`, all append-only, plus the reasoning vocabulary link); hard rules (four
shared ones, then `agents.hard_rules`); run and drift (the five drift triggers and the dissent review); terms (the
`agents.glossary` pointer DEC-255 asks for, or a line saying none is configured).

The keys and their checks are in `docs/integrations/repo-config.md`. Only ROOT's own config is read (as `aec init`
does), never a parent's.

## Rules

- **Markers:** exactly one begin line (starting `<!-- telosmith:agents:begin`) followed by exactly one end line, each on
  a line of its own. Anything else (two blocks, a lone marker, end before begin) is refused and nothing is written.
  Marker text inside a sentence isn't a marker.
- **Safety:** `--file` is relative and stays inside ROOT (no `..`). The file and every folder on the way to it must not
  be symlinks. The new text goes to a temporary file in the same folder and is renamed over the old one, keeping its
  permissions.
- **Config texts** are one printable line each, at most 300 characters, with no backtick and no HTML comment marker,
  so a value can't break the Markdown or forge an end marker.
- **Deterministic:** the same config gives the same block, on every machine.

## Not yet

- Removing the hand-written copies from the seven repositories: follow-up PRs there, one repository at a time.
- Heading levels and wording per repository: the block is the same everywhere by design; a repository that needs
  more says it in its own sections.
- Line endings: a file with CRLF line endings reads as stale under `check`; `write` puts the block in with LF.
