# Per-repository config: `.aec/config.json`

Author: claude:aec#wake-20261120-19 · Reviewer: API Kate (records `AEC-R-repo-config-*@2`, independent); Codex · model=claude-opus-5-5

Decided by Zach on Telosmith#94 (`AEC-D-repo-config@2`). Handoff HO-AEC-20261119-V8FC, DEC-256 item 1.
This is the first slice: the loader, the schema, precedence, and one consumer (`aec init`).

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
| `records` | relative path | `.aec/records.jsonl` | `aec config show` now; the record commands in a later slice |
| `init.ci_name` | name (`A-Z a-z 0-9 _ -`, as `aec init` accepts) | `aec` | `aec init --ci-name` |
| `init.hook_style` | `inline` or `line` | `inline` | `aec init --hook-style` |

## Rules

- **Discovery.** From the start directory, walk up to the nearest directory holding `.aec/`, never past the top of the
  git work tree. That directory is the root. `aec init ROOT` reads only `ROOT/.aec/config.json`, never a parent's.
- **Relative paths** resolve against the root, never the directory the command ran in. They use `/`, are not absolute
  and contain no `..`.
- **Validation** covers the whole file before any command uses it: malformed JSON, a non-object top level, repeated
  keys, unknown keys (top-level or nested), wrong types or values. Once the file parses, every problem is reported
  at once, with the file's path. Malformed JSON stops at its first parse error (line and column): nothing past it can
  be checked. An unknown key may mean the file was written for a newer Telosmith; the message says so.
- **The records path is not yet used by the record commands.** `aec check RECORDS` and the others still take their
  path as before. When they read the config (a later slice), an explicit `RECORDS` argument will still win.
- **Precedence:** an explicit flag, then the file, then the default. Reading never rewrites the file.
- **Lists** (none yet): a list value replaces the default whole; nothing merges.

## Commands

- `aec config show [--repo DIR] [--json]`: each setting, its value, and whether it came from the file or the default.
- `aec config check [--repo DIR]`: exit 0 when the file is valid or absent, else 1 with every problem.

## Not yet

Which checks run, hook strictness, the governance options `aec agents` renders (item 4), and the records path in the
record commands. Each arrives with the code that reads it; until then those keys are unknown keys.
