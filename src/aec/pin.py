"""`aec pin-check`: does the aec running here equal the Telosmith version this repository's CI pins?

The gate Kate set on Telosmith#88 and wrote as `AEC-R-hook-line-pin-gate@1`: no repository's hook is replaced
by the one-line form until the launcher refuses to run when the local aec and the CI pin differ, or when their
equality cannot be established. This module is that check, on its own, so the line hook (Telosmith#89) can call
it once both are merged, and a person or CI job can run it today.

It reads the pins repositories already have; it does not define a new pin-file format (out of scope in the
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
and no ignored file inside the package has an importable suffix outside `__pycache__` (Kate, round 5).
Anything else (an index wheel, a dirty checkout, a copy vendored elsewhere) is indeterminate, and indeterminate
fails. The pass condition is exact equality of the two 40-character commits. Standard library only; offline.
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


def find_pins(root) -> list[tuple[str, str]]:
    """(relative path, ref) for every Telosmith pin under root. Raises PinError on an unreadable pin file."""
    root = Path(root)
    pins: list[tuple[str, str]] = []
    wf = root / ".github" / "workflows"
    if wf.is_dir():
        for path in sorted(list(wf.glob("*.yml")) + list(wf.glob("*.yaml"))):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise PinError(f"cannot read {path.relative_to(root)}: {exc}") from exc
            for ref in PIN_RE.findall(text):
                pins.append((str(path.relative_to(root)), ref.strip("\"'")))
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
    from .init import _checkout_commit, _installed_commit
    pkg = Path(__file__).resolve().parent
    sha = _installed_commit()
    if sha:
        return {"commit": sha, "how": "pip install from git"}
    found = _checkout_commit(pkg)
    if found and not found[1] and not _dirty(pkg):
        return {"commit": found[0], "how": "clean source checkout"}
    return None


def _dirty(pkg: Path) -> bool:
    """True when the checkout holding pkg has a staged or unstaged change to a tracked file, or a non-ignored
    untracked file, anywhere in the checkout, or when git cannot say (AEC-R-pin-check-source-clean@1, Kate).
    An untracked module can shadow a committed one (an untracked `aec/records/__init__.py` beats `records.py`;
    Codex P2 on #90). Ignored files count only when they are importable from inside the package (Kate, round 5
    on #90): a suffix the running interpreter imports (source, bytecode or native extension), outside
    `__pycache__`. Other ignored artefacts do not count. Nothing is deleted or changed."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", str(pkg), "status", "--porcelain=v1", "-z", "--untracked-files=all",
                              "--ignore-submodules=none", ":/"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return True
    if out.returncode or out.stdout.strip("\0"):
        return True
    return bool(_ignored_importables(pkg))


def _ignored_importables(pkg: Path) -> list[str]:
    """Ignored files under pkg that the interpreter could import ahead of, or beside, committed code: an ignored
    `records.so` or a sourceless `records.pyc` beside a deleted `records.py` both import. Files under `__pycache__`
    are left out: CPython loads a cached `.pyc` only for a source file that exists, and checks it against that
    source, so a cache cannot supply a module the checkout lacks (open question to Kate, round 6). Raises nothing:
    when git cannot list ignored files, the result is a sentinel entry, so the checkout counts as dirty."""
    import importlib.machinery
    import subprocess
    suffixes = tuple(importlib.machinery.all_suffixes())
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
    if local is _UNSET:
        local = local_version()
    if not local:
        raise PinError(f"the local aec's version is indeterminate (not a git install and not a clean Telosmith "
                       f"checkout); install the pinned one: pip install \"git+https://github.com/eraevous/Telosmith.git@{ref}\"")
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
