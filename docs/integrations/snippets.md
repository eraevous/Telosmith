# Hook and CI snippets, rendered on demand (DEC-256 item 3)

`aec init` writes two snippets for a repository to copy into place: the Claude Code hook settings and a CI job. Until
now they landed under `.aec/snippets/`, and repositories committed them. Committed copies go stale: the survey behind
DEC-256 found 11 repositories carrying them in 4 to 6 variants.

`aec snippets` renders the same text from what the repository already states, so nothing needs committing:

```bash
aec snippets show hook                 # settings JSON for .claude/settings.json (init.hook_style)
aec snippets show ci                   # workflow for .github/workflows/<init.ci_name>.yml
aec snippets show ci --ref <full SHA>  # pin a commit explicitly
aec snippets check                     # are the committed copies under .aec/snippets/ still current?
```

## Where each value comes from

| Snippet | Value | Source, in order |
|---|---|---|
| hook | style | `--hook-style`, else `init.hook_style` in ROOT's own `.aec/config.json`, else `inline` |
| ci | job and file name | `--ci-name`, else `init.ci_name`, else `aec` |
| ci | Telosmith commit | `--ref` (a full 40-character SHA), else `commit` in `tools/aec_upstream.json` (the one pin source, AEC-D-pin-check-scope@1) |

Only ROOT's own config counts, as for `aec init`; a parent repository's config is never read. Nothing is fetched:
with no `--ref` and no pin file, `show ci` exits 1 and says what to supply. A symlinked `tools/` directory is not
read through. An invalid config fails with the config's own message.

`show` prints exactly what `aec init` writes for the same settings and commit (a test pins this for both hook styles).

## `check`

For each file under `.aec/snippets/`:

- `claude-settings.json` is compared with `show hook` as JSON (layout doesn't matter);
- `<name>-ci.yml` is compared with `show ci` as text; a name other than `init.ci_name` is reported, and with no
  commit to compare against the file is reported as unchecked, never passed;
- symlinks and non-regular files are reported, not read; other files are listed and ignored.

Exit 0 when there are no copies or all are current, else 1. It writes nothing. Use it in a follow-up PR to show the
copies were current before deleting them, or in CI while copies remain.

## `init.snippet_files`

`aec init` still writes `.aec/snippets/` by default, so its behaviour is unchanged. Set
`{"init": {"snippet_files": false}}` in `.aec/config.json` and `init` writes no copies; its next steps name the
`aec snippets show` commands instead, with the style, name and commit init resolved written out as flags, so a flag
given to `init` but not in the config still applies (Codex P2 on #102). Whether the default should flip is left to Zach (see the PR).

## Not here

- Removing committed copies from the instantiating repositories: follow-up PRs, one repository at a time.
- Rendering `.claude/settings.json` or the workflow file in place: `show` prints; merging into an existing settings
  file stays a person's (or agent's) edit.
