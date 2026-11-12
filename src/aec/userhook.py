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

import contextlib
import io
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path

MARKER = "# telosmith-user-hook v1"
MATCHER = "Edit|Write|MultiEdit"
DIST = "telosmith"
REFUSED = 2  # PostToolUse exit 2: stderr goes to the agent and the user sees it; the edit already happened


# The integrity check is plain source, not a function of this package, because the hook must run it BEFORE
# importing anything from the package it checks: a tampered module would otherwise run at import time and could
# replace the verifier (Codex review on #79). The hook passes this source to `python -I -c`; it imports only the
# standard library and reads the distribution's metadata, never `aec`. This module execs the same source so
# `aec hook verify` and the tests use the identical code.
VERIFY_SRC = r"""
import base64, csv, hashlib, os, sys
from importlib import metadata


class Refused(Exception):
    pass


def _digest(path):
    h = hashlib.sha256(open(path, 'rb').read()).digest()
    return 'sha256=' + base64.urlsafe_b64encode(h).rstrip(b'=').decode()


def _dist():
    try:
        return metadata.distribution('telosmith')
    except metadata.PackageNotFoundError:
        raise Refused('no installed telosmith distribution in %s (a source checkout cannot be verified)' % sys.prefix)


def record_text(dist=None):
    text = (dist or _dist()).read_text('RECORD')
    if not text:
        raise Refused('the installed telosmith has no RECORD file, so its files cannot be checked')
    return text


def record_pin(dist=None):
    return hashlib.sha256(record_text(dist).encode()).hexdigest()


def verify(pin=None):
    if os.path.realpath(sys.prefix) == os.path.realpath(sys.base_prefix):
        raise Refused('aec is not in a dedicated environment (sys.prefix %s is the base interpreter); '
                      'install it with pipx or into its own venv' % sys.prefix)
    prefix = os.path.join(os.path.realpath(sys.prefix), '')
    dist = _dist()
    pkg = os.path.realpath(str(dist.locate_file('aec')))
    if not pkg.startswith(prefix):
        raise Refused('the aec package %s is outside its environment %s' % (pkg, prefix))
    checked = ['aec package inside ' + prefix]
    # Read RECORD directly: Distribution.files silently drops entries whose file no longer exists, which would
    # hide a deleted package file from the missing-file check below.
    listed = {}
    for row in csv.reader(record_text(dist).splitlines()):
        if len(row) >= 2 and row[1]:
            listed[os.path.realpath(str(dist.locate_file(row[0])))] = row[1]
    found = 0
    seen = set()
    for root, dirs, files in os.walk(pkg):
        # os.walk does not descend into a symlinked directory, but import does (a package beats a same-named
        # module), so any symlink in the tree is refused outright (Codex review on #79).
        for name in dirs + files:
            if os.path.islink(os.path.join(root, name)):
                raise Refused('%s is a symlink; the installed package must contain only regular files'
                              % os.path.join(root, name))
        dirs[:] = sorted(d for d in dirs if d != '__pycache__')
        for name in sorted(files):
            path = os.path.realpath(os.path.join(root, name))
            want = listed.get(path)
            if want is None:
                raise Refused('%s is not in the installed RECORD (an editable install, or a file added after install)' % path)
            if _digest(path) != want:
                raise Refused('%s does not match its RECORD hash (changed after install)' % path)
            found += 1
            seen.add(path)
    if not found:
        raise Refused('no files under ' + pkg)
    # Every hashed RECORD file inside the package must still exist: a deleted aec/__init__.py would let an
    # aec.py elsewhere on sys.path load instead (Codex security review on #79).
    missing = sorted(p for p in listed if p.startswith(os.path.join(pkg, '')) and p not in seen)
    if missing:
        raise Refused('%s is listed in RECORD but missing (removed after install)' % missing[0])
    # And the top-level import must resolve to this package's __init__.py, not a module that shadows it on sys.path.
    # find_spec locates the top-level module without running it.
    import importlib.util
    spec = importlib.util.find_spec('aec')
    want_init = os.path.join(pkg, '__init__.py')
    if spec is None or not spec.origin or os.path.realpath(spec.origin) != want_init:
        raise Refused('the aec import would load %s, not the verified %s'
                      % (spec.origin if spec else 'nothing', want_init))
    checked.append('%d package files match RECORD; the aec import resolves to it' % found)
    if pin is not None:
        if record_pin(dist) != pin:
            raise Refused('RECORD changed since the hook was installed (after upgrading aec, reinstall the hook: '
                          '`aec hook install --user`)')
        checked.append('RECORD matches the digest pinned at install')
    return checked
"""

# What the hook runs: verify with VERIFY_SRC, and only then import aec. argv: <pin> <project>.
BOOTSTRAP_SRC = VERIFY_SRC + r"""
try:
    verify(sys.argv[1])
except Refused as exc:
    sys.stderr.write('Telosmith hook refused to run: %s\n' % exc)
    sys.exit(2)
# Run the verified source, never cached bytecode: a .pyc in the package's __pycache__ is not in RECORD, and
# Python would load it whenever its header matches the unchanged source (Codex review on #79). With a private,
# empty pycache_prefix nothing is read from __pycache__, and nothing is written.
import atexit, tempfile
sys.dont_write_bytecode = True
sys.pycache_prefix = tempfile.mkdtemp(prefix='telosmith-nocache-')
atexit.register(os.rmdir, sys.pycache_prefix)
from aec.__main__ import main
sys.exit(main(['hook', 'run', '--pin', sys.argv[1], sys.argv[2]]))
"""

_ns: dict = {"__name__": "aec._verify"}
exec(compile(VERIFY_SRC, "<aec verify>", "exec"), _ns)  # noqa: S102 - our own constant, see above
Refused = _ns["Refused"]
verify = _ns["verify"]
record_pin = _ns["record_pin"]


# --- the hook ------------------------------------------------------------------------------------------------

def hook_command(python: str, pin: str) -> str:
    """Absolute interpreter, isolated mode, started from /. Quiet in repos without Telosmith records."""
    return (
        'P="$CLAUDE_PROJECT_DIR"; [ -n "$P" ] && [ -f "$P/.aec/records.jsonl" ] || exit 0; '
        f'cd / && exec {shlex.quote(python)} -I -c {shlex.quote(BOOTSTRAP_SRC)} {shlex.quote(pin)} "$P" {MARKER}'
    )


def hook_entry(python: str, pin: str) -> dict:
    return {"matcher": MATCHER, "hooks": [{"type": "command", "command": hook_command(python, pin), "timeout": 30}]}


def _mine(hook) -> bool:
    return isinstance(hook, dict) and MARKER in str(hook.get("command", ""))


def _without_ours(post: list) -> list:
    """PostToolUse entries with our command removed. A sibling hook in the same entry keeps its entry and matcher
    (Codex review on #79); an entry left with no hooks only because ours went is dropped."""
    out = []
    for entry in post:
        hooks = entry.get("hooks") if isinstance(entry, dict) else None
        if not isinstance(hooks, list) or not any(_mine(h) for h in hooks):
            out.append(entry)
            continue
        rest = [h for h in hooks if not _mine(h)]
        if rest:
            out.append({**entry, "hooks": rest})
    return out


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


def _produce(argv: list[str], directory: Path, dest: str) -> int:
    """Run an aec command whose output goes to `-o`, writing a new private file in `directory` and renaming it
    onto `dest` only on success. Never opens `dest`, so a symlink planted there is replaced, not followed."""
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".hook-", suffix=".tmp")
    os.close(fd)
    try:
        rc = _call(argv + ["-o", tmp])[0]
        if rc == 0:
            os.replace(tmp, dest)
        return rc
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.remove(tmp)


def run(project: str, pin: str | None) -> int:
    """The hook body. Same steps and exit codes as the project-level snippet from `aec init` (Telosmith #77).
    The installed hook reaches this only through BOOTSTRAP_SRC, which has already verified the package before
    importing it; the check repeated here is a convenience for direct calls, not the trust boundary."""
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
    aec_dir = p / ".aec"
    rec, edges, before = (str(aec_dir / n) for n in ("records.jsonl", "edges.jsonl", "hook-before.jsonl"))
    # The checkout controls everything under .aec, including symlinks; writing through one would let a branch
    # overwrite any file the user owns (Codex security review on #79). Refuse a symlinked .aec or records file,
    # and write each output to a fresh file inside .aec, then rename it over the destination: a rename replaces
    # a symlink there instead of following it.
    for path in (aec_dir, Path(rec)):
        if path.is_symlink():
            print(f"Telosmith hook refused to run: {path} is a symlink", file=sys.stderr)
            return REFUSED
    if not aec_dir.is_dir() or os.path.realpath(aec_dir) != os.path.join(os.path.realpath(p), ".aec"):
        print(f"Telosmith hook refused to run: {aec_dir} is not a directory inside the project", file=sys.stderr)
        return REFUSED
    if _produce(["edges", str(p)], aec_dir, edges) != 0:
        with contextlib.suppress(OSError):
            os.remove(edges)  # removes a symlink itself, never its target
        print("Telosmith hook: could not refresh .aec/edges.jsonl; skipped the records check", file=sys.stderr)
        return 1
    rc, out = _call(["check", rec, "--edges", edges])
    if rc != 0:
        sys.stderr.write(out)
        return 2
    if _produce(["snapshot", str(p), "--rev", "HEAD"], aec_dir, before) != 0:
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
    kept = _without_ours(post)
    new = kept + [hook_entry(python, pin)]
    if new == post:
        return "unchanged"
    hooks["PostToolUse"] = new
    _write(path, data)
    return "updated" if kept != post else "installed"


def uninstall(path: Path) -> str:
    data = _load(path)
    post = data.get("hooks", {}).get("PostToolUse")
    if not post:
        return "absent"
    kept = _without_ours(post)
    if kept == post:
        return "absent"
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
