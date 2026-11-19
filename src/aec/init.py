"""`aec init`: scaffold Telosmith (formerly AEC) into an existing repository (feature 002, US1).

Creates only what is absent, never overwrites, and never touches Spec Kit's own files. The purpose
record it writes is a provisional stub: it cannot authorize or block anything until the owner replaces
it. Standard library only.
"""
from __future__ import annotations

import functools
import json
import os
import re
import subprocess
import textwrap
from pathlib import Path

from . import __version__
from . import edges as E

AEC_SOURCE = "git+https://github.com/eraevous/Telosmith.git"
# The first release whose `aec` has `snapshot`, `code-impact --exit-code` and module/reach logic, which the
# generated hook and CI job below call. v0.4.1 (the latest tag when this was written) has none of them.
FIRST_DELIVERY_RELEASE = (0, 5, 0)

README = """# .aec: purpose and justification records (Telosmith, formerly AEC)

- `records.jsonl`: append-only reasoning records (purpose, requirements, claims, evidence, decisions,
  authorities). Never edit a line; append a new version. Vocabulary:
  https://github.com/eraevous/Telosmith/blob/main/docs/reasoning-vocabulary.md
- `edges.jsonl`: the structural snapshot of the code (`aec edges`). Generated, so it is git-ignored
  (`.aec/.gitignore`): regenerate it rather than committing or hand-editing it.
- `snippets/`: a Claude Code hook and a CI job to copy into place. Nothing here is active until you do.

Start by replacing the purpose stub `P0` with a new version stating what this project is for, in your
own words (`"version": 2`, `"epistemic": "provisional"` while you are still discovering it,
`"committed"` once changes to it should need your authorization).

All Telosmith results are structural: they show what changed and what relied on it, not whether the
remaining evidence is good enough. That stays a review question.
"""

# After each edit: refresh the snapshot, fail on record errors, then compare against HEAD and tell the agent
# (stderr, exit 2) when linked code changed or reaches a change. Quiet when nothing linked moved. HEAD's snapshot
# goes to its own git-ignored file so a baseline the user keeps in `.aec/before.jsonl` is never overwritten.
# An installed `aec` too old for this (no `--exit-code`) is reported to the user (exit 1, non-blocking).
# Every aec call goes through the shell function `aec`, which starts Python from `/` and gets the
# project as absolute paths. Python puts the current directory first on the import path, so starting
# it inside the checkout (`cd project; python3 -m aec`) would import an aec.py, runpy.py or any other
# module a branch places there, before the installed Telosmith (Codex security reviews on
# eraevous/crank-mem-eval#7). Starting from `/` keeps the checkout off the path from interpreter
# startup on, on every Python version. Two settings the user may have exported are adjusted first, inside
# the function's subshell only (#77 review): a relative RELAYKIT_RECORDS is anchored to the project (it
# meant the working directory, which was the project; after `cd /` it would mean /), and PYTHONPATH loses
# every entry that resolves inside the checkout (an absolute entry there would still import a branch's
# aec.py). Entries outside the checkout are kept. A relative entry meant the working directory, which was the
# project, so it is resolved against the project and passed on as an absolute path; after `cd /` it would
# mean / (Codex on Fathom#49, Today#7, MtG#46: a sibling checkout `PYTHONPATH=../Telosmith/src` stopped importing).
# Two more entries are dropped (Copilot on #87): an ancestor of the checkout, which would make the checkout
# itself importable under its directory name (a checkout named aec/ would shadow Telosmith), and a resolved
# entry containing the path separator, which a symlink a branch plants could otherwise use to smuggle in a
# second entry that points inside the checkout.
# The filter runs in an isolated interpreter (-I: no PYTHONPATH, no user site) that also starts from /.
HOOK_PATHFILTER = (
    "import os,sys; b=os.path.realpath(sys.argv[1]); p=os.path.join(b,''); "
    "r=lambda a: os.path.join(os.path.realpath(a),''); "
    "print(os.pathsep.join(a for a in (e if os.path.isabs(e) else os.path.realpath(os.path.join(b,e)) "
    "for e in os.environ.get('PYTHONPATH','').split(os.pathsep) if e) "
    "if os.pathsep not in a and not r(a).startswith(p) and not p.startswith(r(a))))"
)
HOOK_AEC = (
    "P=\"$CLAUDE_PROJECT_DIR\"; aec() { ( "
    "r=\"${RELAYKIT_RECORDS#\"${RELAYKIT_RECORDS%%[![:space:]]*}\"}\"; "
    "case \"$r\" in /*|'') ;; *) export RELAYKIT_RECORDS=\"$P/$r\";; esac; "
    "cd / && pp=$(python3 -I -c \"" + HOOK_PATHFILTER + "\" \"$P\") || exit 1; "
    "if [ -n \"$pp\" ]; then export PYTHONPATH=\"$pp\"; else unset PYTHONPATH; fi; "
    "python3 -m aec \"$@\" ); }; "
)
HOOK_COMMAND = (
    "cd \"$CLAUDE_PROJECT_DIR\" || exit 0; "
    + HOOK_AEC +
    "aec code-impact --help 2>/dev/null | grep -q -- --exit-code || "
    "{ echo 'Telosmith hook: the installed aec has no code-impact --exit-code; install Telosmith v0.5.0 or later "
    "(the commit your CI job pins)' >&2; exit 1; }; "
    # A branch controls everything under .aec. A symlink planted at an output would let the hook overwrite any
    # file the user owns; refuse before writing (the same rule as the user-level hook, Codex review on #79).
    # aec >= this release also renames outputs into place, so older copies of this text are covered too.
    "for f in \"$P/.aec\" \"$P/.aec/records.jsonl\" \"$P/.aec/edges.jsonl\" \"$P/.aec/hook-before.jsonl\"; do "
    "if [ -L \"$f\" ]; then echo \"Telosmith hook refused to run: $f is a symlink\" >&2; exit 2; fi; done; "
    "aec edges \"$P\" -o \"$P/.aec/edges.jsonl\" 2>/dev/null || "
    "{ rm -f \"$P/.aec/edges.jsonl\"; echo 'Telosmith hook: could not refresh .aec/edges.jsonl; skipped the records check' >&2; exit 1; }; "
    "aec check \"$P/.aec/records.jsonl\" --edges \"$P/.aec/edges.jsonl\" >/dev/null || "
    "{ aec check \"$P/.aec/records.jsonl\" --edges \"$P/.aec/edges.jsonl\" 1>&2; exit 2; }; "
    "aec snapshot \"$P\" --rev HEAD -o \"$P/.aec/hook-before.jsonl\" 2>/dev/null || exit 0; "
    "out=$(aec code-impact \"$P/.aec/records.jsonl\" \"$P/.aec/hook-before.jsonl\" \"$P/.aec/edges.jsonl\" --exit-code 2>&1) || "
    "{ printf '%s\\n' \"$out\" "
    "'(Telosmith: stale/needs_review lines are status changes; structural pointer lines are candidates for "
    "attention and change no status.)' >&2; exit 2; }"
)

HOOK = {
    "hooks": {
        "PostToolUse": [{
            "matcher": "Edit|Write|MultiEdit",
            "hooks": [{"type": "command", "command": HOOK_COMMAND, "timeout": 30}],
        }]
    }
}

# One-line form (AEC-D-braided-dcc@1, propagation D; opt-in with `aec init --hook-style line`). The hook body
# lives in the installed package (`aec hook project`, src/aec/userhook.py), so a fix to the body ships with a
# Telosmith release and the settings text in each repository stays the same. What stays in the line is only what
# must run before any aec is imported: the launcher above (which aec gets imported) and two diagnostics, one for
# "no aec importable at all" and one for "an aec too old to have the body". Exit codes match HOOK_COMMAND:
# 0 quiet, 1 a step could not run, 2 a report for the agent. Nothing blocks: PostToolUse runs after the edit.
# Not yet the default. Kate's gates for replacing the inline hook (docs/integrations/braided-dcc.md) are not all
# met: the line does not yet check that the local aec is the version CI pins.
HOOK_LINE_COMMAND = (
    "cd \"$CLAUDE_PROJECT_DIR\" || exit 0; "
    + HOOK_AEC +
    "aec --version >/dev/null 2>&1 || "
    "{ echo 'Telosmith hook: no aec is importable here; install Telosmith at the commit your CI job pins "
    "(pip install \"" + AEC_SOURCE + "@<commit>\")' >&2; exit 1; }; "
    "aec hook project --help >/dev/null 2>&1 || "
    "{ echo \"Telosmith hook: the installed $(aec --version 2>&1) has no 'hook project'; install Telosmith "
    "0.6.0 or later (the commit your CI job pins), or go back to the inline hook: aec init --hooks --hook-style inline\" >&2; exit 1; }; "
    "aec hook project \"$P\""
)

HOOK_LINE = {
    "hooks": {
        "PostToolUse": [{
            "matcher": "Edit|Write|MultiEdit",
            "hooks": [{"type": "command", "command": HOOK_LINE_COMMAND, "timeout": 30}],
        }]
    }
}
HOOK_STYLES = {"inline": HOOK, "line": HOOK_LINE}

# Report-only: compares the merge-base with this checkout and writes the report to the job summary, where a
# reviewer sees it on the run page. Never fails the job (a code change is not an error).
CI_IMPACT = """base=$(git merge-base "$AEC_BASE" HEAD 2>/dev/null) || base=""
if [ -z "$base" ]; then
  echo "code-impact skipped: no base revision for this event" | tee -a "$GITHUB_STEP_SUMMARY"; exit 0
fi
python3 -m aec snapshot . --rev "$base" -o .aec/before.jsonl || {
  echo "code-impact skipped: could not snapshot $base" | tee -a "$GITHUB_STEP_SUMMARY"; exit 0; }
report=$(python3 -m aec code-impact .aec/records.jsonl .aec/before.jsonl .aec/edges.jsonl 2>&1) || true
printf '%s\\n' "$report"
{ echo "## Telosmith code-impact (structural, report-only) vs $base"; echo '```'
  printf '%s\\n' "$report"; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
exit 0
"""

def _release(version: str) -> tuple[int, ...] | None:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    return tuple(int(p) for p in m.groups()) if m else None


def _installed_commit() -> str | None:
    """The commit this package was pip-installed from (PEP 610 `direct_url.json`), when that install is the
    code running now; None for a source checkout, an editable install, a wheel from an index, or an install from
    another version-control system (only `vcs_info.vcs == "git"` counts: Copilot on #90, 14c200f)."""
    try:
        from importlib import metadata
        dist = metadata.distribution("telosmith")
        if Path(str(dist.locate_file("aec"))).resolve() != Path(__file__).resolve().parent:
            return None
        data = json.loads(dist.read_text("direct_url.json") or "{}")
        if (data.get("dir_info") or {}).get("editable"):
            return None
        vcs = data.get("vcs_info") or {}
        if vcs.get("vcs") != "git":
            return None
        sha = vcs.get("commit_id", "")
        return sha if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) else None
    except Exception:  # noqa: BLE001 - any metadata problem means "unknown"
        return None


def install_ref(version: str = __version__, commit: str | None = None) -> str:
    """What the generated CI job installs: the commit this aec was installed from when known; else this
    version's tag when it is a release that has the delivery commands; else `main` (with a warning)."""
    if commit:
        return commit
    rel = _release(version)
    if rel is not None and rel >= FIRST_DELIVERY_RELEASE:
        return f"v{version}"
    return "main"


def _checkout_commit(pkg_dir: Path) -> tuple[str, bool] | None:
    """(HEAD, dirty) when pkg_dir is tracked in a git checkout (run with PYTHONPATH=src, or an editable
    install of Telosmith, whose pyproject names it); None otherwise, including a package that only sits
    untracked inside some repo (a venv) or a copy vendored into another project."""
    def git(*args):
        return subprocess.run(["git", "-C", str(pkg_dir), *args], capture_output=True, text=True, timeout=10)
    try:
        if git("ls-files", "--error-unmatch", "__init__.py").returncode:
            return None
        top = git("rev-parse", "--show-toplevel").stdout.strip()
        pyproject = Path(top) / "pyproject.toml" if top else None
        if not (pyproject and pyproject.is_file()
                and re.search(r'^name\s*=\s*"telosmith"', pyproject.read_text(encoding="utf-8"), re.M)):
            return None  # src/aec vendored into some other project: its HEAD is not a Telosmith commit
        head = git("rev-parse", "HEAD")
        sha = head.stdout.strip()
        if head.returncode or not re.fullmatch(r"[0-9a-f]{40}", sha):
            return None
        return sha, git("diff", "--quiet", "HEAD", "--", ".").returncode != 0
    except (OSError, subprocess.SubprocessError):
        return None


def resolve_install_ref(version: str = __version__, commit: str | None = None,
                        pkg_dir: Path | None = None) -> tuple[str, str | None]:
    """The ref the generated CI job installs, and a note to print. A git install's recorded commit comes
    first. A source checkout has no recorded commit, but its HEAD is known, while this version's tag may not
    exist yet (offline, it cannot be checked): pin HEAD. Otherwise `install_ref`'s rule (#51) applies."""
    if not commit:
        found = _checkout_commit(Path(__file__).resolve().parent if pkg_dir is None else pkg_dir)
        if found:
            sha, dirty = found
            note = (f"aec runs from a source checkout, so the CI snippet pins its HEAD commit {sha[:12]} "
                    f"rather than the tag v{version}, which may not exist yet. Push that commit, or replace the "
                    "pin with a release tag you have checked.")
            if dirty:
                note += " The checkout has uncommitted changes in aec/; CI will not run them."
            return sha, note
    return install_ref(version, commit), None


class PinResolutionError(ValueError):
    """`aec init` could not establish the full commit for the Telosmith revision it would pin."""


_FULL_SHA = re.compile(r"[0-9a-f]{40}")


def resolve_commit(rev: str, source: str = AEC_SOURCE, local: Path | None = None,
                   timeout: float = 20) -> str:
    """The full commit object ID for `rev`, or PinResolutionError (AEC-R-init-full-commit-pin@1).

    A full 40-character id is kept as given once git confirms it names a commit (in `local` when given, else
    at `source`). An abbreviated commit is resolved only in `local`, a git
    checkout of Telosmith, where `git rev-parse` refuses an ambiguous prefix and a non-commit object. A
    branch or tag name is resolved with `git ls-remote` against `source`: an annotated tag gives its peeled
    commit, never the tag object; a name that is both a tag and a branch on different commits is ambiguous.
    Nothing is guessed: any other outcome (offline, no git, unknown name) raises with the reason."""
    if not isinstance(rev, str) or not rev or rev.startswith("-") or any(c.isspace() for c in rev):
        raise PinResolutionError(f"cannot pin Telosmith revision {rev!r}: not a commit, branch or tag name")
    url = source[4:] if source.startswith("git+") else source
    if _FULL_SHA.fullmatch(rev):
        # Full length is syntax, not identity (Kate, round 10): ask git that the id names a commit, in the
        # Telosmith checkout it came from when there is one, else at the source.
        kind = _local_object_type(local, rev, timeout) if local is not None else _remote_object_type(url, rev, timeout)
        if kind != "commit":
            where = str(local) if local is not None else url
            raise PinResolutionError(f"cannot pin Telosmith revision {rev[:12]}: " + (
                f"it is a {kind} in {where}, not a commit" if kind else f"no such object could be read from {where}"))
        return rev
    if re.fullmatch(r"[0-9a-f]{4,39}", rev):
        if local is None:
            raise PinResolutionError(f"cannot pin Telosmith revision {rev!r}: an abbreviated commit can only "
                                     "be resolved in a Telosmith checkout; give the full 40-character commit")
        try:
            out = subprocess.run(["git", "-C", str(local), "rev-parse", "--verify", "--quiet", "--end-of-options",
                                  f"{rev}^{{commit}}"], capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as error:
            raise PinResolutionError(f"cannot pin Telosmith revision {rev!r}: git failed ({error})") from None
        sha = out.stdout.strip()
        if out.returncode or not _FULL_SHA.fullmatch(sha):
            raise PinResolutionError(f"cannot pin Telosmith revision {rev!r}: no single commit with that prefix "
                                     f"in {local} (unknown, ambiguous or not a commit)")
        return sha
    try:
        out = subprocess.run(["git", "ls-remote", "--", url, f"refs/tags/{rev}", f"refs/tags/{rev}^{{}}",
                              f"refs/heads/{rev}"], capture_output=True, text=True, timeout=timeout,
                             env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, subprocess.SubprocessError) as error:
        raise PinResolutionError(f"cannot pin Telosmith revision {rev!r}: git ls-remote failed ({error})") from None
    if out.returncode:
        reason = (out.stderr.strip().splitlines() or ["no reason given"])[-1]
        raise PinResolutionError(f"cannot pin Telosmith revision {rev!r}: git ls-remote {url} failed ({reason})")
    refs = {}
    for line in out.stdout.splitlines():
        sha, _, name = line.partition("\t")
        if _FULL_SHA.fullmatch(sha):
            refs[name] = sha
    tag = refs.get(f"refs/tags/{rev}^{{}}") or refs.get(f"refs/tags/{rev}")
    head = refs.get(f"refs/heads/{rev}")
    if tag and head and tag != head:
        raise PinResolutionError(f"cannot pin Telosmith revision {rev!r}: it names both a tag ({tag[:12]}) and a "
                                 f"branch ({head[:12]}); give the full commit")
    if not (tag or head):
        raise PinResolutionError(f"cannot pin Telosmith revision {rev!r}: no tag or branch of that name at {url}")
    sha = tag or head
    # ls-remote gives ids, not object types: a tag can name a tree or a blob (Codex on #91). Fetch that one
    # object, shallow, into a throwaway repository and ask git what it is.
    kind = _remote_object_type(url, sha, timeout)
    if kind != "commit":
        raise PinResolutionError(f"cannot pin Telosmith revision {rev!r}: it names {sha[:12]}, which is "
                                 + (f"a {kind}, not a commit" if kind else "not a commit git could fetch"))
    return sha


def _local_object_type(local: Path, sha: str, timeout: float) -> str | None:
    """The type of object `sha` in the git checkout at `local`, or None if git can't read it."""
    try:
        out = subprocess.run(["git", "-C", str(local), "cat-file", "-t", sha], capture_output=True, text=True,
                             timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stdout.strip() or None) if out.returncode == 0 else None


def _remote_object_type(url: str, sha: str, timeout: float) -> str | None:
    """The type of object `sha` at `url` ("commit", "tree", ...), or None if it can't be fetched."""
    import tempfile
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        with tempfile.TemporaryDirectory(prefix="aec-pin-") as tmp:
            run = functools.partial(subprocess.run, capture_output=True, text=True, timeout=timeout, env=env)
            if run(["git", "init", "-q", "--bare", tmp]).returncode:
                return None
            if run(["git", "-C", tmp, "fetch", "-q", "--depth=1", "--no-tags", "--", url, sha]).returncode:
                return None
            out = run(["git", "-C", tmp, "cat-file", "-t", sha])
            return (out.stdout.strip() or None) if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def __getattr__(name):  # CI is resolved on first use, not at import (resolving it may run git)
    if name == "CI":
        return ci_snippet(resolve_install_ref(__version__, _installed_commit())[0])
    raise AttributeError(name)


def ci_snippet(ref: str, name: str = "aec") -> str:
    first = "v" + ".".join(map(str, FIRST_DELIVERY_RELEASE))
    if ref == "main":
        head = (f"# WARNING: UNPINNED. This aec ({__version__}) was not installed from a known commit, and no release\n"
                f"# >= {first} (the first with `aec snapshot` and `code-impact --exit-code`, which the last step\n"
                f"# needs) was known when it was generated. `@main` runs whatever main holds at job time. Replace\n"
                f"# `main` with a commit SHA you have reviewed, or a release tag >= {first}.")
    elif ref.startswith("v"):
        head = (f"# Pinned to the Telosmith release that generated it ({ref}); change the ref only to a release or\n"
                f"# commit you have reviewed.")
    else:
        head = (f"# Pinned to the Telosmith commit that generated it ({ref[:12]}); change the ref only to a release\n"
                f"# >= {first} or a commit you have reviewed.")
    return f"""# Copy into .github/workflows/{name}.yml.
{head}
name: {name}
on: [push, pull_request]
jobs:
  {name}:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: {{ fetch-depth: 0 }}
      - uses: actions/setup-python@v5
        with: {{ python-version: "3.12" }}
      - run: pip install "{AEC_SOURCE}@{ref}"
      - name: Structural snapshot (regenerated, never trusted from the branch)
        run: python3 -m aec edges . -o .aec/edges.jsonl
      - name: Records check (fails on errors, including dangling code references)
        run: python3 -m aec check .aec/records.jsonl --edges .aec/edges.jsonl
      - name: Code impact against the base (report-only; see the job summary)
        env:
          AEC_BASE: ${{{{ github.event.pull_request.base.sha || github.event.before }}}}
        run: |
{textwrap.indent(CI_IMPACT, " " * 10)}"""


GITIGNORE = """# Generated by `aec edges`; regenerate it instead of committing it (committed copies conflict on
# every pair of pull requests that touch code). Keep a baseline with: cp .aec/edges.jsonl .aec/before.jsonl
# hook-before.jsonl is the Claude Code hook's snapshot of HEAD, rewritten on every edit.
edges.jsonl
before.jsonl
hook-before.jsonl
"""


STUB_PURPOSE = "TODO: the owner states what this project is for (stub from aec init)"


def _records(owner: str, purpose: str | None = None, anchor: dict | None = None) -> str:
    p0 = {"id": "P0", "version": 1, "type": "purpose", "subject": "purpose", "owner": "AU-owner",
          "epistemic": "provisional", "text": purpose or STUB_PURPOSE}
    if anchor:
        p0["anchors"] = [anchor]
    rows = [
        "// Telosmith records. Append-only: add a new version instead of editing a line.",
        {"id": "AU-owner", "version": 1, "type": "authority", "text": f"{owner}: design intent and acceptance",
         "governs": ["purpose", "design", "acceptance", "code"]},
        p0,
    ]
    return "\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows) + "\n"


def init(root: str | Path, owner: str, *, purpose: str | None = None, purpose_anchor: str | None = None,
         hooks: bool | None = None, ci_name: str = "aec", hook_style: str = "inline") -> dict:
    """Scaffold .aec/ without overwriting anything.

    purpose: the text of P0@1 instead of the stub (still provisional: the owner commits it by appending P0@2).
    purpose_anchor: `PATH#LOCATOR` in ROOT that the purpose cites; hashed and checked now (DEC-095).
    hooks: write the Claude Code hook and CI snippets. None (default) writes them only when ROOT has Python
    code, since code-impact has nothing to report in a repository without it.
    ci_name: the CI workflow's name, job id and file name (default `aec`).
    hook_style: `inline` (default) writes the whole hook body into the settings snippet; `line` writes a short
    launcher that calls `aec hook project`, so the body updates with the installed package (opt-in)."""
    root = Path(root)
    aec = root / ".aec"
    created, kept = [], []
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", ci_name or ""):
        raise ValueError(f"--ci-name {ci_name!r}: use letters, digits, - and _ (it names a workflow file and a job)")
    if hook_style not in HOOK_STYLES:
        raise ValueError(f"--hook-style {hook_style!r}: use one of {', '.join(HOOK_STYLES)}")
    if purpose_anchor and not purpose:
        raise ValueError("--purpose-anchor needs --purpose: an anchor cites the text of a stated purpose")
    anchor = None
    if purpose_anchor:
        from .append import make_anchor
        from .sources import SourceContext
        anchor = make_anchor(SourceContext(root), purpose_anchor, "text")  # raises before anything is written
    snapshot = E.snapshot(root)
    if hooks is None:
        hooks = snapshot["header"]["files"] > 0
    ref, note = None, None
    if hooks:
        # The snippet and the next steps name one full commit (AEC-R-init-full-commit-pin@1). A release tag or
        # `main` is resolved now; if that fails, init stops here, before anything is written.
        installed = _installed_commit()
        ref, note = resolve_install_ref(__version__, installed)
        # A checkout's HEAD (the note says so) is checked in that checkout, so an unpushed HEAD still works;
        # anything else is checked at the Telosmith source.
        local = Path(__file__).resolve().parent if note and ref != installed else None
        try:
            ref = resolve_commit(ref, local=local)
        except PinResolutionError as error:
            raise PinResolutionError(f"{error}. Install Telosmith from git at a commit "
                                     f"(pip install \"{AEC_SOURCE}@<commit>\") and run init again, or run it "
                                     "with --no-hooks to skip the hook and CI snippets") from None

    def put(rel: str, make):
        p = aec / rel
        key = f".aec/{rel}"
        if os.path.lexists(p):  # a dangling symlink counts as present: never create its target
            kept.append(key)
            return
        E.write_replacing(p, make())
        created.append(key)

    put("records.jsonl", lambda: _records(owner, purpose, anchor))
    put("edges.jsonl", lambda: E.dumps(snapshot))
    put("README.md", lambda: README)
    # v0.4.1: the snapshot is generated; committing it makes every pair of code-touching PRs conflict.
    put(".gitignore", lambda: GITIGNORE)
    if hooks:
        put("snippets/claude-settings.json", lambda: json.dumps(HOOK_STYLES[hook_style], indent=2) + "\n")
        put(f"snippets/{ci_name}-ci.yml", lambda: ci_snippet(ref, ci_name))

    spec_kit = (root / ".specify").is_dir()
    steps = []
    if purpose:
        steps.append("P0@1 states your purpose (provisional). When it is settled, append P0@2 with "
                     '"epistemic": "committed".')
    else:
        steps.append("Replace the purpose stub P0 in .aec/records.jsonl with your own statement (append version 2).")
    if hooks:
        steps += ["Copy .aec/snippets/claude-settings.json into .claude/settings.json (merge if one exists).",
                  f"Copy .aec/snippets/{ci_name}-ci.yml into .github/workflows/{ci_name}.yml (it pins Telosmith "
                  f"commit {ref}).",
                  ("The hook runs the aec installed in your environment: it needs `code-impact --exit-code` "
                   f"(Telosmith 0.5.0 or later: pip install \"{AEC_SOURCE}@{ref}\")."
                   if hook_style == "inline" else
                   "The one-line hook runs `aec hook project` from the aec installed in your environment "
                   f"(pip install \"{AEC_SOURCE}@{ref}\"); a newer Telosmith updates the hook body without "
                   "editing .claude/settings.json. To go back, run `aec init --hooks --hook-style inline` in an empty "
                   "directory and copy its .aec/snippets/claude-settings.json over.")]
    else:
        steps.append("No hook or CI snippet written: " + ("this repository has no Python code, so code-impact has "
                     "nothing to report. Re-run `aec init --hooks` after adding code." if snapshot["header"]["files"] == 0
                     else "--no-hooks was given."))
    steps.append("Add records with computed anchors: aec append .aec/records.jsonl '<record JSON>' "
                 "--anchor PATH#LOCATOR")
    steps.append("If the repo has Codex++ purpose files: python3 -m aec import-purpose .")
    if spec_kit:
        steps.insert(1, "Spec Kit detected. Register the Telosmith hooks (report-only, removable): "
                        "specify extension add --dev <path-to-Telosmith-checkout>/extension")
    if note and f".aec/snippets/{ci_name}-ci.yml" in created:
        steps.insert(0, "Note: " + note)
    return {"created": created, "kept": kept, "spec_kit": spec_kit, "next_steps": "\n".join(steps)}
