# Per-repository config: `.aec/config.json`

Author: claude:aec#wake-20261120-19 · Reviewer: API Kate (records `AEC-R-repo-config-*@2`, independent); Codex · model=claude-opus-5-5

Decided by Zach on Telosmith#94 (`AEC-D-repo-config@2`). Handoff HO-AEC-20261119-V8FC, DEC-256 item 1.
First slice (#97): the loader, the schema, precedence, and `aec init`. Second slice: the commands whose records
path is optional read `records`.

## What it does

One file per repository holds the settings that instantiating repositories otherwise copy by hand. A repository
without it behaves exactly as before: every setting has a default equal to today's behaviour.

```json
{
  "_doc": "Telosmith settings for this repository. Flags on the command line win over these.",
  "version": 1,
  "records": ".aec/records.jsonl",
  "init": {"ci_name": "aec", "hook_style": "line"}
}
```

| Key | Type | Default | Read by |
|---|---|---|---|
| `_doc` | string | none | nobody (JSON has no comments) |
| `version` | `1` | `1` | the loader: any other value is an error |
| `records` | relative path | `.aec/records.jsonl` | `aec source show\|search`, `aec import-purpose`, `aec mcp`, `aec speckit derive\|drift` (see below) |
| `init.ci_name` | name (`A-Z a-z 0-9 _ -`, as `aec init` accepts) | `aec` | `aec init --ci-name`, `aec snippets show ci` |
| `init.hook_style` | `inline` or `line` | `inline` | `aec init --hook-style`, `aec snippets show hook` |
| `init.snippet_files` | `true` or `false` | `true` | `aec init`: whether it writes `.aec/snippets/` ([snippets.md](snippets.md)) |
| `agents.owner` | one-line text | `the repository owner` | `aec agents` (who accepts design intent) |
| `agents.glossary` | relative path or `https://` URL | none | `aec agents` (the DEC-255 glossary pointer) |
| `agents.read_first` | list of relative paths | `[]` | `aec agents` (read after the purpose records, in order) |
| `agents.ledgers` | list of relative paths | `[]` | `aec agents` (append-only files besides `records`) |
| `agents.hard_rules` | list of one-line texts | `[]` | `aec agents` (added after the shared hard rules) |

The `agents.*` texts end up in Markdown, so each is one printable line of at most 300 characters, with no backtick and
no `<!--` or `-->`; a list has no repeated entries. See `docs/integrations/agents-md.md`.

## Rules

- **Discovery.** From the start directory, walk up to the nearest directory holding `.aec/`, never past the top of the
  git work tree. That directory is the root. `aec init ROOT` reads only `ROOT/.aec/config.json`, never a parent's.
- **Relative paths** resolve against the root, never the directory the command ran in. They use `/`, are not absolute
  and contain no `..`.
- **Validation** covers the whole file before any command uses it: malformed JSON, a non-object top level, repeated
  keys, unknown keys (top-level or nested), wrong types or values. Once the file parses, every problem is reported
  at once, with the file's path. Malformed JSON stops at its first parse error (line and column): nothing past it can
  be checked. An unknown key may mean the file was written for a newer Telosmith; the message says so.
- **The records path** is read only by commands whose records path is optional:
  - `aec source show|search --repo ROOT`, `aec import-purpose ROOT` and `aec mcp --root ROOT`: an explicit `--records`
    first (relative to the working directory, as before; the config is then not read at all), then `records` in
    ROOT's own `.aec/config.json` (resolved against ROOT; a parent's file is never read), then `ROOT/.aec/records.jsonl`.
  - `aec speckit derive|drift`, which already search upward from the feature: an explicit `--records`, then `records`
    from the config found by discovery, then the nearest `.aec/records.jsonl` above the feature, as before. In detail:
    - Discovery is the rule above, started from the spec's directory: it stops at the nearest directory holding
      `.aec/` and never passes the git top. It doesn't look further for a config that sets `records`.
    - If that directory has no `config.json`, or its config sets no `records`, the command falls back at once to the
      nearest `.aec/records.jsonl` above the feature (the search it always made; it is not bounded by the git top).
      An outer repository's config is never read.
    - A configured `records` resolves against the directory discovery stopped at, never the working directory.
  - The two rules differ on purpose: an explicit ROOT names the repository, so only its own file counts; a feature
    path names it implicitly, so discovery finds it. The order (explicit, config, default) is the same for both.
  - An invalid config is an error for these commands only when they would use it (no explicit `--records`).
  - A configured `records` path may not pass through a symlink anywhere below the root, and must resolve inside the
    root; otherwise it is refused as an invalid config. The checkout controls both the file and the tree, so a
    committed link could otherwise send a read or an append outside the repository. An explicit `--records` is not
    checked (it is the user's own choice, as before).
  - `aec check RECORDS`, `impact`, `code-impact` and `append` take RECORDS as a required argument; that is unchanged
    and the config never makes it optional (`AEC-R-repo-config-precedence@2`).
- **Precedence:** an explicit flag, then the file, then the default. Reading never rewrites the file.
- **Lists** (none yet): a list value replaces the default whole; nothing merges.

## Commands

- `aec config show [--repo DIR] [--json]`: each setting, its value, and whether it came from the file or the default.
- `aec config check [--repo DIR]`: exit 0 when the file is valid or absent, else 1 with every problem.

## Not yet

Which checks run, hook strictness, and the records path in the
editor hook (`aec hook`, which still reads `.aec/records.jsonl` and ignores `records`). Each arrives with the code that
reads it; until then the new keys are unknown keys.
