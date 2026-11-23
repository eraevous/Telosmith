"""`aec pin-check`: does the aec running here equal the Telosmith commit this repository pins?

The gate Kate set on Telosmith#88 and wrote as `AEC-R-hook-line-pin-gate@1`: no repository's hook is replaced
by the one-line form until the launcher refuses to run when the local aec and the pin differ, or when their
equality cannot be established. This module is that check as a command; the line launcher itself makes the same
decision before importing aec (`HOOK_LINE_GATE` in init.py, Kate's AEC-R-hook-launcher-preimport@1), because code in
the aec it checks must not run first.

Owner decision `AEC-D-pin-check-scope@1` (Zach, 2026-11-18, on #90) narrows it to what can be established
without guessing:

- **One pin source.** The pin is `commit` in `tools/aec_upstream.json` (the format MtG already uses and its
  aec-upstream bot moves). Workflow files are not read: six review rounds on #90 showed that a line reader over
  YAML and shell can always be steered (comments, quoted `#`, `name:` inside `run:` blocks, variables, unused
  `env:` values). A symlink at the pin path, a missing file, unreadable JSON, or a `commit` that is not a full
  40-character SHA fails.
- **Installed aec only.** The local version is the commit this aec was pip-installed from (PEP 610
  `direct_url.json`). A source checkout or editable install is indeterminate and fails: code in a writable
  checkout runs before this module and can forge its answer (Codex security P2 on #90, ec563ad).

The pass condition is exact equality of the two 40-character commits. Tampering with an installed environment is
out of scope (Kate's AEC-R-pin-check-local-identity@1). That CI installs the commit the file names is a separate
CI-side check, not this one. Standard library only; offline.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

UPSTREAM_FILE = Path("tools") / "aec_upstream.json"
SHA_RE = re.compile(r"[0-9a-f]{40}")


class PinError(Exception):
    """Equality could not be established; the message says why."""


def read_pin(root) -> str:
    """The pinned commit from root/tools/aec_upstream.json. Raises PinError when it is missing, a symlink
    (dangling or not), unreadable, or not a full 40-character commit SHA."""
    path = Path(root) / UPSTREAM_FILE
    if path.is_symlink():
        raise PinError(f"{UPSTREAM_FILE.as_posix()} is a symlink; the pin must be a regular file in the repository")
    if not path.exists():
        raise PinError(f"no Telosmith pin: {UPSTREAM_FILE.as_posix()} not found under {root} (the only pin source; "
                       f"add it with {{\"commit\": \"<40-character Telosmith commit>\"}})")
    if not path.is_file():
        raise PinError(f"{UPSTREAM_FILE.as_posix()} is not a regular file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise PinError(f"cannot read {UPSTREAM_FILE.as_posix()}: {exc}") from exc
    commit = data.get("commit") if isinstance(data, dict) else None
    if not isinstance(commit, str) or not commit:
        raise PinError(f"{UPSTREAM_FILE.as_posix()} has no commit")
    if not SHA_RE.fullmatch(commit):
        kind = ("an abbreviated commit" if re.fullmatch(r"[0-9a-f]{4,39}", commit)
                else "a tag or branch, not a commit")
        raise PinError(f"{UPSTREAM_FILE.as_posix()} pins {commit!r}, {kind}: only a full 40-character commit SHA "
                       f"establishes what is installed; pin the full commit")
    return commit


def local_identity() -> tuple[dict | None, str]:
    """({"commit": sha, "how": text}, "") for a pip install from git; (None, reason) otherwise."""
    from .init import _installed_commit
    sha = _installed_commit()
    if sha:
        return {"commit": sha, "how": "pip install from git"}, ""
    return None, ("not a pip install from git with a recorded commit (a source checkout or editable install "
                  "does not qualify: AEC-D-pin-check-scope@1)")


def local_version() -> dict | None:
    return local_identity()[0]


_UNSET = object()


def check(root, local=_UNSET) -> str:
    """Return a one-line success message, or raise PinError when the local aec and the pin are not shown equal."""
    ref = read_pin(root)
    why = "not a pip install from git with a recorded commit"
    if local is _UNSET:
        local, why = local_identity()
    if not local:
        raise PinError(f"the local aec's version is indeterminate ({why}); install the pinned one: "
                       f"pip install \"git+https://github.com/eraevous/Telosmith.git@{ref}\"")
    commit = local["commit"]
    if commit == ref:
        return f"local aec {commit[:12]} ({local['how']}) matches the pin {ref[:12]} ({UPSTREAM_FILE.as_posix()})"
    raise PinError(f"local aec is {commit[:12]} ({local['how']}) but {UPSTREAM_FILE.as_posix()} pins {ref[:12]}")


def add_parser(sub) -> None:
    p = sub.add_parser("pin-check", help="exit 0 only when the installed aec equals the commit in "
                                         "tools/aec_upstream.json (AEC-D-pin-check-scope@1); 1 with a reason otherwise")
    p.add_argument("root", nargs="?", default=".", help="repository root (default: .)")


def cli(a, ap) -> int:
    import sys
    try:
        print(check(a.root))
    except PinError as exc:
        print(f"Telosmith pin check: {exc}", file=sys.stderr)
        return 1
    return 0
