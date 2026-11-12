"""`aec hook`: a Claude Code hook installed in the user's settings, run by an installed, verified `aec`.

DRAFT for DEC-223 (proposed; see docs/integrations/user-level-hook.md). Read the limits there first:
Claude Code merges hooks from every settings level, so a user-level hook ADDS this check; it does not stop a
checkout's own `.claude/settings.json` hooks from running. Only managed settings (`allowManagedHooksOnly`) or a
per-run `claude --settings '{"disableAllHooks": true}'` do that.

What this module gives on top of the project-level snippet from `aec init`:
- the hook command is written once, outside every checkout, with absolute paths baked in, so a branch cannot
  edit it;
- it runs the Python of the environment `aec` was installed into, with `-I` (ignores PYTHONPATH, user
  site-packages and the current directory) and from `/`, so nothing in the checkout is importable;
- before doing anything it checks that `aec` was imported from inside that environment and that the installed
  files still match pip's RECORD, and that RECORD still matches the digest pinned at install time. On any
  mismatch it refuses and says why.

Subcommands: `print`, `install`, `uninstall`, `verify`, `run` (what the hook calls). Standard library only.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import os
import shlex
import sys
from pathlib import Path

MARKER = "# telosmith-user-hook v1"
MATCHER = "Edit|Write|MultiEdit"
DIST = "telosmith"
REFUSED = 2  # PostToolUse exit 2: stderr goes to the agent and the user sees it; the edit already happened


class Refused(Exception):
    """An integrity check failed; the message says which and why."""


# --- integrity -----------------------------------------------------------------------------------------------

def _digest(path: Path) -> str:
    """sha256 in pip RECORD's format: urlsafe base64, no padding."""
    h = hashlib.sha256(path.read_bytes()).digest()
    return "sha256=" + base64.urlsafe_b64encode(h).rstrip(b"=").decode()


def _distribution():
    from importlib import metadata
    try:
        return metadata.distribution(DIST)
    except metadata.PackageNotFoundError as exc:
        raise Refused(f"no installed '{DIST}' distribution in {sys.prefix} (a source checkout can't be verified)") from exc


def record_text(dist=None) -> str:
    dist = dist or _distribution()
    text = dist.read_text("RECORD")
    if not text:
        raise Refused("the installed telosmith has no RECORD file, so its files can't be checked")
    return text


def record_pin(dist=None) -> str:
    """The digest pinned at install time: sha256 of the RECORD file itself."""
    return hashlib.sha256(record_text(dist).encode()).hexdigest()


def verify(pin: str | None = None) -> list[str]:
    """Check the running `aec`. Returns what was checked; raises Refused on the first failure."""
    import aec
    checked = []
    prefix = Path(sys.prefix).resolve()
    if Path(sys.prefix) == Path(sys.base_prefix):
        raise Refused(f"aec is not running from a dedicated environment (sys.prefix {sys.prefix} is the base "
                      "interpreter); install it with pipx or into its own venv")
    pkg = Path(aec.__file__).resolve().parent
    if prefix not in pkg.parents:
        raise Refused(f"aec was imported from {pkg}, outside its environment {prefix}")
    checked.append(f"aec imported from inside {prefix}")
    dist = _distribution()
    if Path(str(dist.locate_file("aec"))).resolve() != pkg:
        raise Refused(f"the telosmith distribution's files are not the aec package that is running ({pkg})")
    listed = {}
    for f in dist.files or ():
        p = Path(str(dist.locate_file(f))).resolve()
        if f.hash is not None:
            listed[p] = f"{f.hash.mode}={f.hash.value}"
    sources = [p for p in pkg.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    if not sources:
        raise Refused(f"no files under {pkg}")
    for p in sources:
        want = listed.get(p.resolve())
        if want is None:
            raise Refused(f"{p} is not in the installed RECORD (an editable install, or a file added after install)")
        if _digest(p) != want:
            raise Refused(f"{p} does not match its RECORD hash (changed after install)")
    checked.append(f"{len(sources)} package files match RECORD")
    if pin is not None:
        if record_pin(dist) != pin:
            raise Refused("RECORD changed since the hook was installed (reinstall the hook after upgrading aec: "
                          "`aec hook install --user`)")
        checked.append("RECORD matches the digest pinned at install")
    return checked


# --- the hook ------------------------------------------------------------------------------------------------

def hook_command(python: str, pin: str) -> str:
    """Absolute interpreter, isolated mode, started from /. Quiet in repos without Telosmith records."""
    return (
        'P="$CLAUDE_PROJECT_DIR"; [ -n "$P" ] && [ -f "$P/.aec/records.jsonl" ] || exit 0; '
        f'cd / && exec {shlex.quote(python)} -I -m aec hook run --pin {shlex.quote(pin)} "$P" {MARKER}'
    )


def hook_entry(python: str, pin: str) -> dict:
    return {"matcher": MATCHER, "hooks": [{"type": "command", "command": hook_command(python, pin), "timeout": 30}]}


def _ours(entry) -> bool:
    return isinstance(entry, dict) and any(
        isinstance(h, dict) and MARKER in str(h.get("command", "")) for h in entry.get("hooks", []) or [])


def _call(argv: list[str]) -> tuple[int, str]:
    from .__main__ import main
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(argv)
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:  # noqa: BLE001 - any failure of a step is reported, not raised into the hook
        buf.write(f"{type(exc).__name__}: {exc}\n")
        rc = 1
    return rc or 0, buf.getvalue()


def run(project: str, pin: str | None) -> int:
    """The hook body. Same steps and exit codes as the project-level snippet from `aec init` (Telosmith #77)."""
    try:
        verify(pin)
    except Refused as exc:
        print(f"Telosmith hook refused to run: {exc}", file=sys.stderr)
        return REFUSED
    p = Path(project)
    if not p.is_absolute():
        print("Telosmith hook: project path must be absolute", file=sys.stderr)
        return 1
    rr = os.environ.get("RELAYKIT_RECORDS", "").strip()
    if rr and not os.path.isabs(rr):
        os.environ["RELAYKIT_RECORDS"] = str(p / rr)  # it meant the project; the hook runs from /
    rec, edges, before = (str(p / ".aec" / n) for n in ("records.jsonl", "edges.jsonl", "hook-before.jsonl"))
    if _call(["edges", str(p), "-o", edges])[0] != 0:
        with contextlib.suppress(OSError):
            os.remove(edges)
        print("Telosmith hook: could not refresh .aec/edges.jsonl; skipped the records check", file=sys.stderr)
        return 1
    rc, out = _call(["check", rec, "--edges", edges])
    if rc != 0:
        sys.stderr.write(out)
        return 2
    if _call(["snapshot", str(p), "--rev", "HEAD", "-o", before])[0] != 0:
        return 0
    rc, out = _call(["code-impact", rec, before, edges, "--exit-code"])
    if rc != 0:
        sys.stderr.write(out.rstrip("\n") + "\n(Telosmith: stale/needs_review lines are status changes; structural "
                         "pointer lines are candidates for attention and change no status.)\n")
        return 2
    return 0


# --- settings file -------------------------------------------------------------------------------------------

def default_settings() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text() or "{}")
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".telosmith-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def install(path: Path, python: str, pin: str) -> str:
    """Add the hook, replacing an older copy of ours; leaves every other key and hook alone. Idempotent."""
    data = _load(path)
    hooks = data.setdefault("hooks", {})
    post = hooks.setdefault("PostToolUse", [])
    entry = hook_entry(python, pin)
    kept = [e for e in post if not _ours(e)]
    if kept + [entry] == post:
        return "unchanged"
    hooks["PostToolUse"] = kept + [entry]
    _write(path, data)
    return "updated" if len(kept) != len(post) else "installed"


def uninstall(path: Path) -> str:
    data = _load(path)
    post = data.get("hooks", {}).get("PostToolUse")
    if not post or not any(_ours(e) for e in post):
        return "absent"
    kept = [e for e in post if not _ours(e)]
    if kept:
        data["hooks"]["PostToolUse"] = kept
    else:
        del data["hooks"]["PostToolUse"]
        if not data["hooks"]:
            del data["hooks"]
    _write(path, data)
    return "removed"


# --- CLI -----------------------------------------------------------------------------------------------------

def add_parser(sub) -> None:
    h = sub.add_parser("hook", help="install a user-level Claude Code hook that runs this verified aec (draft, DEC-223)")
    hs = h.add_subparsers(dest="hook_cmd", required=True)
    for name, text in (("install", "add the hook to your Claude settings (idempotent)"),
                       ("uninstall", "remove the hook from your Claude settings"),
                       ("print", "print the settings JSON without writing anything")):
        s = hs.add_parser(name, help=text)
        s.add_argument("--user", action="store_true", help="target ~/.claude/settings.json (the default)")
        s.add_argument("--settings", help="target this settings file instead (e.g. a managed-settings.json you place)")
    v = hs.add_parser("verify", help="check this aec's environment and files; exit 1 with the reason if not intact")
    v.add_argument("--pin", help="also require RECORD to match this digest")
    r = hs.add_parser("run", help="the hook body (called by the installed hook)")
    r.add_argument("project")
    r.add_argument("--pin")


def cli(a, ap) -> int:
    if a.hook_cmd == "run":
        return run(a.project, a.pin)
    if a.hook_cmd == "verify":
        try:
            for line in verify(a.pin):
                print("ok:", line)
            print("pin:", record_pin())
            return 0
        except Refused as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 1
    target = Path(a.settings).expanduser() if a.settings else default_settings()
    if a.hook_cmd == "uninstall":
        print(f"{uninstall(target)}: {target}")
        return 0
    try:
        verify()  # never pin or install a hook for an aec that already fails the check
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    python, pin = os.path.abspath(sys.executable), record_pin()
    if a.hook_cmd == "print":
        print(json.dumps({"hooks": {"PostToolUse": [hook_entry(python, pin)]}}, indent=2))
        return 0
    print(f"{install(target, python, pin)}: {target}")
    print("note: Claude Code merges hooks across settings levels; this adds a check and does not disable a "
          "checkout's own hooks (docs/integrations/user-level-hook.md)")
    return 0
