# User-level Telosmith hook (DEC-223): design note and draft

Status: **draft, proposed.** Written by the Telosmith lane (claude:aec, scheduled run, 2026-11-12) for
handoff HO-AEC-20261112-NBRW. DEC-223 (Zach, 2026-11-12 08:29 CT) approved moving the hook to user level. The
details below are the lane's proposal; Zach accepts or changes them.

## The answer first: a user-level hook does not stop project hooks

Claude Code **merges** hooks from every settings level. A hook in `~/.claude/settings.json` runs *in
addition to* the hooks in a checkout's `.claude/settings.json`; it can't turn them off or replace them. So
`aec hook install --user` adds a check the branch can't edit. It does **not** stop a branch's own
`.claude/settings.json` from running whatever that branch put there.

Things that *can* stop project hooks, from the documentation (fetched 2026-11-12):

| mechanism | what it does | cost and limits |
|---|---|---|
| `allowManagedHooksOnly: true` in **managed settings**, plus the Telosmith hook in that same managed file | Only managed hooks run. User, project, local and plugin hooks are blocked. | Needs admin rights to write the system file (Linux `/etc/claude-code/managed-settings.json`, macOS `/Library/Application Support/ClaudeCode/managed-settings.json`, Windows `C:\Program Files\ClaudeCode\managed-settings.json`). It blocks **every** other user and project hook too, for example MtG's `drift_check.py` hook, unless that hook is copied into the managed file. The docs state no plan requirement for the file form; **[not verified]**. The server-delivered form needs Claude for Teams or Enterprise. |
| `claude --settings '{"disableAllHooks": true}'` for one run | Turns off all non-managed hooks for that run, whatever the project says. The CLI level sits above project settings. | It turns off the user-level hook too. Combine it with a managed hook if you want the check to keep running. |
| `disableAllHooks: true` in **user** settings | Nothing useful. | A project's `"disableAllHooks": false` overrides it, because project settings take precedence over user settings. |

Two more facts change the threat picture:
- **Hook edits apply live.** The file watcher picks up edits to hooks in settings files without a restart.
  So `git checkout <unreviewed branch>` *inside* a running session switches that session to the branch's hooks.
- **Cloud sessions (the lanes) never read `~/.claude/settings.json`.** They run the repository's hooks, plus
  server-managed hooks (Teams or Enterprise only). The docs describe no way to give an Anthropic-hosted session
  a user-level hook.

Sources (Claude Code docs; quotes collected by a claude-code-guide subagent this run and not re-read by me):
- https://code.claude.com/docs/en/hooks.md: "Hook entries merge across settings levels rather than replacing
  each other". Also on `disableAllHooks`, `allowManagedHooksOnly` ("Your user, project, local, and plugin hooks
  are blocked"), and "Direct edits to hooks in settings files are normally picked up automatically by the file
  watcher".
- https://code.claude.com/docs/en/settings.md: "Settings precedence, highest first: managed settings, command
  line, project local, shared project, user"; "a "disableAllHooks": false in a project's
  .claude/settings.json overrides a true in your user settings"; and on cloud sessions, "User and project
  local settings (~/.claude/settings.json and .claude/settings.local.json): not read."
- https://code.claude.com/docs/en/managed-settings.md: the file paths above.
- https://code.claude.com/docs/en/server-managed-settings.md: "available for Claude for Teams and Claude for
  Enterprise customers"; managed hooks need the user's security approval.
- https://code.claude.com/docs/en/cloud-environments.md: "Claude Code runs hooks from the repository and from
  your organization's server-managed settings."

**Proposal.** On Zach's own machines, the hook that actually closes the gap is the same command placed in
**managed settings** with `allowManagedHooksOnly: true`. The user-level install is the step before that: it
adds the check without disabling anything. Neither reaches the cloud lanes. They stay protected by the
DEC-225 CI hook guard, which only applies to PRs, and by the rule of thumb below.

## The hook (built as a draft: `src/aec/userhook.py`)

`aec hook install --user` writes one PostToolUse entry (`Edit|Write|MultiEdit`, timeout 30):

```sh
P="$CLAUDE_PROJECT_DIR"; [ -n "$P" ] && [ -f "$P/.aec/records.jsonl" ] || exit 0; cd / && exec '/abs/env/bin/python3' -I -c '<bootstrap: verify, then import aec>' <sha256-of-RECORD> "$P" # telosmith-user-hook v1
```

- It runs **the interpreter of the environment `aec` was installed into**, by absolute path. It never calls
  `python3` from `PATH`, and never the checkout's code.
- **`-I`** ignores `PYTHONPATH`, `PYTHON*` variables and user site-packages, and on 3.11+ also leaves the
  current directory off `sys.path`. **`cd /`** covers 3.10. Together they close both Copilot findings on #77 at
  the source: PYTHONPATH entries inside the checkout are never read, and relative paths are resolved
  by `aec hook run` (a relative `RELAYKIT_RECORDS` is anchored to the project).
- It stays quiet (exit 0) in any repository without `.aec/records.jsonl`.
- `aec hook run` keeps the steps and exit codes of #77's final snippet. If the edges refresh fails, it deletes
  the stale edges and exits 1. If a record check fails, it exits 2. If the snapshot fails, it exits 0. If
  code-impact finds something, it exits 2 with the same note. It runs them in-process: one interpreter, no shell
  function, no PYTHONPATH filter.
- **It verifies before it imports.** The bootstrap (`BOOTSTRAP_SRC`) is stdlib-only source passed with `-c`. It
  reads the distribution's metadata, checks the package files, and only then imports `aec`. Verifying from inside
  the package would let a tampered module run at import time and replace the verifier (Codex review on #79).
  If verification fails, the hook exits 2 with `Telosmith hook refused to run: <reason>`, so both the agent and
  the user see why. `aec hook verify` runs the same check but has already imported the package, so it's a
  diagnostic, not the boundary.

Install: `aec hook install --user` or `--settings FILE`. Uninstall: `aec hook uninstall --user`. To print the
JSON without writing anything: `aec hook print`, which is also how to fill a managed-settings file by hand. The
install is idempotent: it finds its own command by the `# telosmith-user-hook v1` marker, replaces only that
command (a sibling hook in the same entry keeps its entry), leaves every other key and hook alone, and writes atomically. It refuses to install for an `aec` that
already fails verification. The tests use a temporary settings file. **No one's real settings were changed.**

## Integrity check: what each layer stops, and what it doesn't

| layer | stops | doesn't stop |
|---|---|---|
| Dedicated environment (pipx or its own venv), `-I`, `cd /`, absolute interpreter | Shadow modules in the checkout (`aec.py`, `runpy.py`, `site.py` …), `PYTHONPATH`, user site-packages. Tested: a planted package plus `PYTHONPATH=<checkout>` never runs. | Anything already inside the environment. `.pth` files in the environment's own site-packages still run at startup, because `-I` doesn't disable them. The base interpreter's stdlib isn't checked. |
| Location check, done before import (the `telosmith` distribution's `aec` package lies inside `sys.prefix`, and that is a venv rather than the base interpreter) | A package installed somewhere else; running from a source checkout or the base interpreter (both refused). | Tampering inside the environment. |
| RECORD check (every file under the `aec` package is listed in pip's RECORD and matches its sha256), then imports with a private empty `pycache_prefix` and no bytecode writes | Edited or added package files, including an editable install, which is refused because its sources aren't in RECORD. Tampered `__pycache__/*.pyc`: those files aren't in RECORD, so the hook never reads them and compiles the verified source instead. Any symlink in the package tree is refused, because import follows a symlinked directory even though the file walk doesn't (both from Codex review on #79). | An attacker who rewrites RECORD too. |
| Pin (sha256 of RECORD, written into the hook command at install time) | A RECORD rewritten after install. Upgrading means re-running `aec hook install`. | An attacker who can also edit the settings file holding the pin. In `~/.claude/settings.json` that is anyone running as the user. In a root-owned managed file it needs admin rights. |
| Release attestation (**proposed, not built**) | A tampered install source: you would check the wheel with `gh attestation verify` before pipx installs it. | Needs a Telosmith release workflow with `actions/attest-build-provenance`, which is a workflow change for Zach. It says nothing about what happens to the files after install. |

The checks are only worth something because the code doing them is started from settings the branch can't
touch. If a checkout started them, a branch could just skip them. And none of this matters if the branch's own
project hook runs alongside: that is the gap in the first section.

## Migration plan

1. **Now.** Project hooks stay. The DEC-225 CI guard covers PRs, and the rule of thumb covers local work.
2. **Per machine (Zach):** `pipx install git+https://github.com/eraevous/Telosmith.git@<release>`, then
   `aec hook install --user`, then `aec hook verify --pin <pin>`. Until step 3, repos with a project-level
   Telosmith hook run the check twice. That's harmless, only noisy.
3. **Retire project copies** one repository at a time. Each gets a Lydian fingerprint PR first (DEC-225), and
   only when no cloud lane depends on that repo's hook. Cloud lanes never get the user hook, so retiring a repo's
   project hook takes the per-edit check away from lanes in that repo. CI's `aec check` remains. The options for
   lanes are below, and the choice is Zach's:
   - (a) keep the project hook in repos that lanes work in. Most repos are like this today, so in practice
     retirement covers few of them.
   - (b) server-managed settings, if the account plan has them (Teams or Enterprise; **not checked**).
   - (c) lanes run `aec check` explicitly before each commit, as a line in the lane rules.
4. **Optional hardening on each machine:** move the hook into managed settings with `allowManagedHooksOnly: true`.
   Any other hook you still want, MtG's for example, has to move there with it.

## Rule of thumb, rewritten

- **The user-level hook doesn't make an unreviewed branch safe.** Project hooks still run beside it.
- Don't open a local agent session with hooks active on a branch nobody has reviewed. If you must, start it with
  `claude --settings '{"disableAllHooks": true}'`. That also turns off the user-level hook, unless it lives in
  managed settings.
- **Don't check out an unreviewed branch inside a running session.** Hook edits apply live.
- This still isn't covered:
  - hooks that run checkout code by design (MtG's `drift_check.py`, Telosmith's own dogfooding hook);
  - Spec Kit extension commands that tell agents to run `python -m aec` from the repository root (C834 step 3);
  - CI workflows, which a PR author controls anyway;
  - `.pth` files and the base interpreter (see the table above);
  - cloud lanes, which see only repository hooks and server-managed ones.

## What this draft doesn't do

- It doesn't change anyone's settings.
- It doesn't remove a project hook.
- It doesn't set `allowManagedHooksOnly`.
- It doesn't add attestation to releases.
- It hasn't been tested on Windows: the hook command is POSIX `sh`.
