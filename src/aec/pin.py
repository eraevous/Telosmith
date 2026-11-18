"""`aec pin-check`: does the aec running here equal the Telosmith version this repository's CI pins?

The gate Kate set on Telosmith#88 and wrote as `AEC-R-hook-line-pin-gate@1`: no repository's hook is replaced
by the one-line form until the launcher refuses to run when the local aec and the CI pin differ, or when their
equality cannot be established. This module is that check, on its own, so the line hook (Telosmith#89) can call
it once both are merged, and a person or CI job can run it today.

It reads the static pins repositories already have (comments ignored; a dynamic or unpinned install fails); it does not define a new pin-file format (out of scope in the
record):
  - each `.github/workflows/*.yml|*.yaml` line installing `git+https://github.com/eraevous/Telosmith.git@<ref>`
    (what `aec init` writes);
  - `tools/aec_upstream.json` `commit` (MtG's pin, which its aec-upstream bot moves).

Every pin found must be a full 40-character commit SHA and all must name the same commit
(Kate's AEC-R-pin-check-consensus@1): an abbreviated SHA, a tag or a branch such as `main` fails, because
offline none of them establishes which commit CI installs.

The local version is the commit this aec was pip-installed from (PEP 610 direct_url.json) or, for a clean
source checkout of Telosmith, its HEAD (AEC-R-pin-check-local-identity@1). A checkout is clean only when no
tracked file is modified (staged or not), no non-ignored untracked file exists (AEC-R-pin-check-source-clean@1),
and no ignored file inside the package can run in place of the pinned source: an importable suffix, or a
bytecode cache for this interpreter (AEC-R-pin-check-source-clean@2; Codex security P2). In practice a source
checkout qualifies only when run with bytecode writing off (python -B) and no caches present.
Anything else (an index wheel, a dirty checkout, a copy vendored elsewhere) is indeterminate, and indeterminate
fails.

Trust limit (Codex security P2 on #90, ec563ad): the check runs inside the aec it checks. Code that can write the
checkout before aec starts (an ignored package directory such as `aec/records/` shadowing `records.py`, which
`python -m aec` imports at startup) runs before this module does and can forge its answer. Tampering with the
installation is outside Kate's AEC-R-pin-check-local-identity@1 ("verifying installed file contents ... or package
provenance authenticity"); a defence has to verify from outside the checkout, before importing it (the line
launcher, propagation D step 3), not from in here. The pass condition is exact equality of the two 40-character commits. Standard library only; offline.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# The whole revision, up to whitespace, a quote or pip's `#egg=` fragment. Capturing only a SHA-shaped prefix would
# let `@<sha>+hotfix` (a valid branch name) pass as the SHA (Codex P2 on #90, 5b8ef40).
PIN_RE = re.compile(r"github\.com/eraevous/Telosmith(?:\.git)?@([^\s\"'#]+)")
UPSTREAM_FILE = Path("tools") / "aec_upstream.json"
SHA_RE = re.compile(r"[0-9a-f]{40}")


class PinError(Exception):
    """Equality could not be established; the message says why."""


# A YAML or shell comment starts at a `#` that begins the line or follows whitespace; pip's `#egg=` follows no space.
COMMENT_RE = re.compile(r"(^|\s)#.*$")
TELOSMITH_GIT_RE = re.compile(r"eraevous/Telosmith\.git|git\+\S*eraevous/Telosmith", re.IGNORECASE)
PIP_INSTALL_RE = re.compile(r"\bpip3?\s+install\b|\bpython3?\s+-m\s+pip\s+install\b")
# A workflow's or step's `name:` / `description:` is display text GitHub never executes, so a Telosmith URL there
# is not an install (Codex P2 on #90, ec563ad: a step named "Replaces ...@<old-sha>" made the pins disagree).
DISPLAY_KEY_RE = re.compile(r"^\s*(?:-\s+)?(?:name|description)\s*:")


def _workflow_pins(text: str, where: str) -> list[str]:
    """Pins from the executable part of one workflow file (Codex security P2 on #90, 11af34e).

    Comments and display text (`name:`, `description:` lines) are dropped first, so a pinned SHA in a comment cannot stand in for what CI installs. Then any
    remaining line that names Telosmith's git URL without a static `@<rev>` (an unpinned URL, or one kept in a
    variable), or a pip install whose target is built from a variable (`$`), cannot be read offline and fails:
    pin-check accepts only static, textual pins and refuses the rest rather than guessing."""
    pins: list[str] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = COMMENT_RE.sub("", raw)
        if DISPLAY_KEY_RE.match(line):
            continue
        found = PIN_RE.findall(line)
        pins.extend(found)
        rest = PIN_RE.sub("", line)
        if TELOSMITH_GIT_RE.search(rest):
            raise PinError(f"{where}:{n} names Telosmith's git URL without a static @<commit>; pin-check reads "
                           f"only static pins, so it cannot tell what CI installs")
        if PIP_INSTALL_RE.search(line) and "$" in line and ("@" in line or "git+" in line):
            raise PinError(f"{where}:{n} installs from a variable ({line.strip()[:80]}); pin-check reads only "
                           f"static pins, so it cannot tell what CI installs; write the full pinned URL")
    return pins


def find_pins(root) -> list[tuple[str, str]]:
    """(relative path, ref) for every Telosmith pin under root. Raises PinError on an unreadable pin file, or on a
    workflow install the check cannot read statically (see _workflow_pins)."""
    root = Path(root)
    pins: list[tuple[str, str]] = []
    wf = root / ".github" / "workflows"
    if wf.is_dir():
        for path in sorted(list(wf.glob("*.yml")) + list(wf.glob("*.yaml"))):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise PinError(f"cannot read {path.relative_to(root)}: {exc}") from exc
            rel = str(path.relative_to(root))
            pins.extend((rel, ref) for ref in _workflow_pins(text, rel))
    up = root / UPSTREAM_FILE
    if up.exists():
        try:
            commit = json.loads(up.read_text(encoding="utf-8")).get("commit")
        except (OSError, UnicodeDecodeError, ValueError, AttributeError) as exc:
            raise PinError(f"cannot read {UPSTREAM_FILE}: {exc}") from exc
        if not isinstance(commit, str) or not commit:
            raise PinError(f"{UPSTREAM_FILE} has no commit")
        pins.append((str(UPSTREAM_FILE), commit))
    return pins


def local_version() -> dict | None:
    """{"commit": sha, "how": text} for the aec running now; None when its commit cannot be established."""
    return local_identity()[0]


def local_identity() -> tuple[dict | None, str]:
    """(version, reason): the version as local_version gives it, and when it is None, why
    (AEC-R-pin-check-source-clean@2: a refusal names the offending path or condition)."""
    from .init import _checkout_commit, _installed_commit
    pkg = Path(__file__).resolve().parent
    sha = _installed_commit()
    if sha:
        return {"commit": sha, "how": "pip install from git"}, ""
    found = _checkout_commit(pkg)
    if not found:
        return None, "not a git install and not a Telosmith source checkout"
    if found[1]:
        return None, "the source checkout is dirty"
    why = _dirty(pkg)
    if why:
        return None, f"the source checkout does not qualify: {why}"
    return {"commit": found[0], "how": "clean source checkout"}, ""


def _dirty(pkg: Path) -> str | None:
    """A reason when the checkout holding pkg does not qualify as clean, else None (AEC-R-pin-check-source-clean@2,
    Kate). It is unclean with a staged or unstaged change to a tracked file, or a non-ignored untracked file,
    anywhere in the checkout, or when git cannot say. An untracked module can shadow a committed one (an untracked
    `aec/records/__init__.py` beats `records.py`; Codex P2 on #90). Ignored files count only when they can supply
    executable content to this interpreter from inside the package (see _ignored_importables). Nothing is deleted
    or changed."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", str(pkg), "status", "--porcelain=v1", "-z", "--untracked-files=all",
                              "--ignore-submodules=none", ":/"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"git status failed: {exc}"
    if out.returncode:
        return "git status failed"
    changed = [e[3:] for e in out.stdout.split("\0") if e.strip()]
    if changed:
        return "modified or untracked: " + ", ".join(changed[:5]) + (" ..." if len(changed) > 5 else "")
    found = _ignored_importables(pkg)
    if found:
        return ("ignored files that could run in place of the pinned source: " + ", ".join(found[:5])
                + (" ..." if len(found) > 5 else "") + "; remove them and run with PYTHONDONTWRITEBYTECODE=1 "
                "(python -B) so this run writes none")
    return None


def _ignored_importables(pkg: Path) -> list[str]:
    """Ignored files under pkg that can supply executable content to the running interpreter (Kate's
    AEC-R-pin-check-source-clean@2; Codex security P2 on #90, 11af34e):
      - any file whose suffix the interpreter imports (an ignored `records.so`, a sourceless `records.pyc`);
      - bytecode caches under `__pycache__` for this interpreter's cache tag. Requiring the source to exist does
        not make a cache match it: a timestamp-validated cache with the same mtime and size, or an unchecked-hash
        cache (PEP 552), loads instead of the source. Caches for another interpreter's tag cannot be loaded by
        this one and do not count.
    When sys.pycache_prefix is set, caches live outside the checkout where this check cannot see them, so the
    result is a sentinel entry (unsupported). So does a git failure. Nothing is deleted or changed."""
    import importlib.machinery
    import subprocess
    import sys
    if getattr(sys, "pycache_prefix", None):
        return [f"<sys.pycache_prefix is set ({sys.pycache_prefix}); caches there cannot be checked>"]
    suffixes = tuple(importlib.machinery.all_suffixes())
    tag = sys.implementation.cache_tag
    try:
        out = subprocess.run(["git", "-C", str(pkg), "status", "--porcelain=v1", "-z", "--ignored=traditional",
                              "--untracked-files=all", "--", "."],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ["<git status failed>"]
    if out.returncode:
        return ["<git status failed>"]
    found = []
    for entry in out.stdout.split("\0"):
        if not entry.startswith("!! "):
            continue
        path = entry[3:]
        if "__pycache__" in Path(path).parts:
            name = Path(path).name
            if tag and name.endswith(".pyc") and f".{tag}." in name:
                found.append(path)
            continue
        if path.endswith(suffixes):
            found.append(path)
    return found


_UNSET = object()


def check(root, local=_UNSET) -> str:
    """Return a one-line success message, or raise PinError when the local aec and the pin are not shown equal."""
    pins = find_pins(root)
    if not pins:
        raise PinError(f"no Telosmith pin found under {root} (looked in .github/workflows/*.yml and {UPSTREAM_FILE})")
    for where, ref in pins:
        if not SHA_RE.fullmatch(ref):
            kind = ("an abbreviated commit" if re.fullmatch(r"[0-9a-f]{4,39}", ref)
                    else "a tag or branch, not a commit")
            raise PinError(f"{where} pins {ref!r}, {kind}: offline, only a full 40-character commit SHA establishes "
                           f"what CI installs; pin the full commit")
    refs = sorted({ref for _, ref in pins})
    if len(refs) > 1:
        raise PinError("pins disagree: " + "; ".join(f"{p} pins {r[:12]}" for p, r in pins))
    ref = refs[0]
    why = "not a git install and not a clean Telosmith checkout"
    if local is _UNSET:
        local, why = local_identity()
    if not local:
        raise PinError(f"the local aec's version is indeterminate ({why}); install the pinned one: pip install \"git+https://github.com/eraevous/Telosmith.git@{ref}\"")
    commit = local["commit"]
    if commit == ref:
        return f"local aec {commit[:12]} ({local['how']}) matches the CI pin {ref[:12]}"
    raise PinError(f"local aec is {commit[:12]} ({local['how']}) but CI pins {ref[:12]} ({pins[0][0]})")


def add_parser(sub) -> None:
    p = sub.add_parser("pin-check", help="exit 0 only when the local aec equals the Telosmith version CI pins "
                                         "(AEC-R-hook-line-pin-gate@1); 1 with a reason otherwise")
    p.add_argument("root", nargs="?", default=".", help="repository root (default: .)")


def cli(a, ap) -> int:
    import sys
    try:
        print(check(a.root))
    except PinError as exc:
        print(f"Telosmith pin check: {exc}", file=sys.stderr)
        return 1
    return 0
