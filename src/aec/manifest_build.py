"""`aec manifest build` and `aec manifest check` (DEC-256 item 5, slice 2; docs/integrations/manifest-build.md).

    aec manifest build [--root DIR] --trust-config   start ROOT's configured MCP server, build the manifest, write it
    aec manifest check [--root DIR] --trust-config   build it in memory and compare with the committed file; never writes

Both launch the command in ROOT's own `.aec/config.json` (`manifest.command`), never a manifest's `mcp.command`
(accepted page, rule 7). Launching repository configuration is a trust decision by whoever runs the command: a pull
request can change that config. So neither command starts anything without `--trust-config`; without it they exit 2
before reading further (Kate, `AEC-R-manifest-collection-safety@2`). This is not a sandbox.

Collection (`AEC-R-manifest-rebuild-drift@2`): one fresh server process, MCP revision 2026-07-28 only (the revision
Telosmith pins, `aec.mcp.STATELESS`). `server/discover` first; then, for each capability the server advertises, its
lists: `tools` -> tools/list; `resources` -> resources/list and resources/templates/list; `prompts` -> prompts/list.
An unadvertised list is `[]` with no policy entry. Each list follows `nextCursor` (a non-empty string) to its end; a
repeated cursor, a cursor of another type, more than MAX_PAGES pages, a JSON-RPC error, a result that isn't
`resultType: "complete"`, a timeout (TIMEOUT_S per request), or the process exiting early is a collection failure:
exit 2, nothing written.

List policy (`AEC-R-manifest-cache-policy@2`): each list result's `ttlMs` and `cacheScope` go to
`mcp.listPolicy.<list>`, key by key. A key on every page must have one value on every page; a key on some pages and
not others is an error; a key on no page is left out (no default is supplied).

Bounds: stdout is read as bytes, at most MAX_LINE bytes per line and MAX_STDOUT bytes in all; past either, the
collection fails. stderr is read in chunks and discarded as it arrives, so nothing accumulates (Kate, round 13).

Disclosure: the child gets a minimal environment (PATH and, on Windows, SYSTEMROOT, plus the variable *names* in
`manifest.pass_env`); its working directory is ROOT; its stderr is read and dropped, never shown. Diagnostics name
JSON paths; values appear only through `aec.manifest`'s plain-text rule (`[not shown]` otherwise); exceptions are
reported by type. Before writing, the whole result must pass `aec manifest validate` (which refuses the credential
and host-path shapes it recognises). That catches recognisable shapes only.
"""
from __future__ import annotations

import contextlib
import inspect
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import a2a, config, manifest, mcp, skills

PROTOCOL = mcp.STATELESS[0]
TIMEOUT_S = 10.0
MAX_PAGES = 100
LISTS = (("tools", "tools", "tools/list", "tools"), ("resources", "resources", "resources/list", "resources"),
         ("resources", "resourceTemplates", "resources/templates/list", "resourceTemplates"),
         ("prompts", "prompts", "prompts/list", "prompts"))  # (capability, manifest list, method, result key)
MAX_LINE = 8 * 1024 * 1024     # bytes in one stdout line
MAX_STDOUT = 64 * 1024 * 1024  # bytes of stdout in one session
BASE_ENV = ("PATH", "SYSTEMROOT")
A2A_FROM_ELSEWHERE = ("name", "description", "version", "authority")  # from tool, the server and authority
TOOL_FROM_CONFIG = ("id", "name", "description")


class CollectError(Exception):
    """Collection failed; the message is safe to print (no values from the server or the environment)."""


_TOO_LONG, _TOO_MUCH = "too long", "too much"  # reader sentinels (bytes lines are never str)


def section_problems(sec) -> list[str]:
    """Problems with ROOT's `manifest` config section, beyond the key set config.py checks."""
    if not isinstance(sec, dict):
        return ["manifest: missing from .aec/config.json; build and check need it"]
    p = []
    tool = sec.get("tool")
    if not (isinstance(tool, dict) and set(tool) == set(TOOL_FROM_CONFIG) and all(manifest._str(tool[k])
                                                                                 for k in TOOL_FROM_CONFIG)):
        p.append("manifest.tool: an object with exactly id, name and description (version comes from the server)")
    cmd = sec.get("command")
    if not (isinstance(cmd, list) and cmd and all(manifest._str(c) for c in cmd)):
        p.append("manifest.command: a non-empty argv list of strings")
    env = sec.get("pass_env", [])
    if not (isinstance(env, list) and all(isinstance(n, str) and n and n.replace("_", "").isalnum() for n in env)):
        p.append("manifest.pass_env: a list of environment variable names (names only, never values)")
    for k in ("authority", "runtime"):
        if not isinstance(sec.get(k), dict):
            p.append(f"manifest.{k}: an object")
    if isinstance(sec.get("authority"), dict) and set(sec["authority"]) - set(a2a.AUTHORITY_KEYS):
        # refused, not dropped: a key the manifest has no place for would vanish silently (Kate, round 13)
        p.append(f"manifest.authority: only the keys {', '.join(a2a.AUTHORITY_KEYS)}")
    if not isinstance(sec.get("other", []), list):
        p.append("manifest.other: a list")
    sk = sec.get("skills", [])
    if not (isinstance(sk, list) and all(isinstance(x, str) for x in sk)):
        p.append("manifest.skills: a list of folder paths")
    a = sec.get("a2a")
    if a is not None and not (isinstance(a, dict) and manifest._str(a.get("url"))):
        p.append("manifest.a2a: null, or an object with at least url (the other arguments of aec a2a card)")
    elif isinstance(a, dict) and set(a) & set(A2A_FROM_ELSEWHERE):
        p.append("manifest.a2a: name, description, version and authority come from manifest.tool, the server and "
                 "manifest.authority; don't set them here")
    elif isinstance(a, dict) and set(a) - set(inspect.signature(a2a.build_card).parameters):
        # before collection, like the rest (Kate, AEC-R-manifest-config-provenance@1)
        p.append("manifest.a2a: an argument aec a2a card doesn't take")
    path = sec.get("path", ".aec/manifest.json")
    if not (manifest._str(path) and not manifest._host_path(path) and not manifest._climbs(path)):
        p.append("manifest.path: a relative path inside the repository")
    return p


class _Session:
    """One server process speaking MCP 2026-07-28 over stdio. Reads stdout on a thread so a request can time out."""

    def __init__(self, root: Path, sec: dict):
        env = {k: os.environ[k] for k in (*BASE_ENV, *sec.get("pass_env", [])) if k in os.environ}
        try:
            # its own process group on POSIX, so descendants holding our pipes are killed with it (Codex on #118);
            # bufsize=0, so closing stdin never waits on a flush into a full pipe
            self.proc = subprocess.Popen(sec["command"], cwd=root, env=env, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
                                         start_new_session=os.name == "posix")
        except (OSError, ValueError) as exc:
            raise CollectError(f"could not start manifest.command ({type(exc).__name__})") from None
        self.lines: queue.Queue = queue.Queue()
        self.overrun = None  # set by the reader past a byte cap; checked again before a collection succeeds
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.drainer = threading.Thread(target=self._drain, daemon=True)
        self.drainer.start()
        self.next_id = 0

    def _drain(self):
        """stderr: read and dropped as it arrives, never kept or shown."""
        try:
            while self.proc.stderr.read(65536):
                pass
        except (OSError, ValueError):
            pass

    def _read(self):
        """stdout lines onto the queue, within MAX_LINE and MAX_STDOUT; a sentinel ends reading past either."""
        total = 0
        try:
            while True:
                line = self.proc.stdout.readline(MAX_LINE + 1)
                if not line:
                    break
                total += len(line)
                if len(line) > MAX_LINE or total > MAX_STDOUT:
                    self.overrun = _TOO_LONG if len(line) > MAX_LINE else _TOO_MUCH
                    self.lines.put(self.overrun)
                    while self.proc.stdout.read(65536):  # keep draining, unkept, so the server can't block on a full pipe
                        pass
                    break
                self.lines.put(line)
        except (OSError, ValueError):
            pass
        self.lines.put(None)

    def request(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        params = dict(params or {})
        params["_meta"] = {mcp.META_VERSION: PROTOCOL}
        msg = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params}
        deadline = time.monotonic() + TIMEOUT_S  # one budget for the whole request: the write, notifications too
        data, failed = (json.dumps(msg) + "\n").encode("utf-8"), []

        def write():  # raw (bufsize=0) writes can be short: loop until every byte is sent (Kate, round 16)
            view = memoryview(data)
            try:
                while view:
                    n = self.proc.stdin.write(view)
                    if not n:
                        failed.append(True)
                        return
                    view = view[n:]
            except (OSError, ValueError):
                failed.append(True)
        w = threading.Thread(target=write, daemon=True)  # a server that stops reading can't block us (Codex on #118)
        w.start()
        w.join(max(0.0, deadline - time.monotonic()))
        if w.is_alive():
            raise CollectError(f"{method}: the server didn't read the request within {TIMEOUT_S:g} s")
        if failed:
            raise CollectError(f"{method}: the server closed its input")
        while True:
            left = deadline - time.monotonic()
            try:
                if left <= 0:  # checked before every message, so queued notifications can't outlast the deadline
                    raise queue.Empty
                line = self.lines.get(timeout=left)
            except queue.Empty:
                raise CollectError(f"{method}: no answer within {TIMEOUT_S:g} s") from None
            if line is None:
                raise CollectError(f"{method}: the server exited before answering")
            if line is _TOO_LONG or line is _TOO_MUCH:
                self.raise_overrun(method)
            try:
                reply = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise CollectError(f"{method}: the server wrote a line that isn't JSON") from None
            except RecursionError:  # nesting past the decoder's limit, well under the byte caps (Codex on f455156)
                raise CollectError(f"{method}: the server wrote JSON nested too deeply") from None
            if isinstance(reply, dict) and reply.get("id") == self.next_id:
                break  # anything else (a notification) is skipped
        if "error" in reply:
            code = reply["error"].get("code") if isinstance(reply["error"], dict) else None
            raise CollectError(f"{method}: JSON-RPC error {code if isinstance(code, int) else '[not shown]'}")
        result = reply.get("result")
        if not isinstance(result, dict) or result.get("resultType") != "complete":
            raise CollectError(f"{method}: the result isn't an object with resultType 'complete'")
        return result

    def raise_overrun(self, where: str):
        if self.overrun is _TOO_LONG:
            raise CollectError(f"{where}: the server wrote a line longer than {MAX_LINE} bytes")
        raise CollectError(f"{where}: the server wrote more than {MAX_STDOUT} bytes in this session")

    def finish(self):
        """End a session whose answers all arrived: close stdin, let the server exit (killed after TIMEOUT_S), read
        stdout to its end, then fail if it overran a cap. Session output is everything up to the server's exit, so
        an overrun after the last answer counts, deterministically (Kate, round 14)."""
        self.close()
        self.reader.join(TIMEOUT_S)
        if self.reader.is_alive():  # stdout not accounted for to its end: not a clean result (Kate, round 15)
            raise CollectError(f"session: stdout didn't close within {TIMEOUT_S:g} s of the server exiting")
        if self.overrun is not None:
            self.raise_overrun("session")
        while True:  # lines after the last answer get the same checks as any other (Codex on #118)
            line = self.lines.get_nowait()
            if line is None:
                break
            try:
                json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise CollectError("session: the server wrote a line that isn't JSON after its last answer") from None
            except RecursionError:
                raise CollectError("session: the server wrote JSON nested too deeply after its last answer") from None

    def close(self, failed: bool = False):
        """Close stdin and let the server exit (killed after TIMEOUT_S); after a failure, kill it first, so a write
        still blocked on its stdin ends with a broken pipe."""
        if failed:
            self._kill()
        with contextlib.suppress(OSError):
            self.proc.stdin.close()
        if not failed:
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.proc.wait(timeout=TIMEOUT_S)
        self._kill()

    def _kill(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        if os.name == "posix":  # and anything it started in its group, which may still hold stdout or stderr
            with contextlib.suppress(OSError):
                os.killpg(self.proc.pid, 9)

    def release(self):
        """Close the output pipes whose reader has stopped. A reader still blocked (a descendant outside the group
        holds the pipe) keeps its stream: closing it would wait on the reader's lock (Codex on #118). Both threads
        are daemons, so neither holds the process open."""
        for f, t in ((self.proc.stdout, self.reader), (self.proc.stderr, self.drainer)):
            t.join(0.5)
            if not t.is_alive():
                with contextlib.suppress(OSError, ValueError):
                    f.close()


def _collect_list(s: _Session, method: str, key: str) -> tuple[list, dict]:
    items, policy, seen, cursor = [], {}, set(), None
    pages = []
    for _ in range(MAX_PAGES):
        r = s.request(method, {"cursor": cursor} if cursor is not None else {})
        if not isinstance(r.get(key), list) or not all(isinstance(x, dict) for x in r[key]):
            raise CollectError(f"{method}: result.{key} isn't a list of objects")
        items.extend(r[key])
        page = {k: r[k] for k in manifest.POLICY_KEYS if k in r}
        ttl = page.get("ttlMs", 0)
        if not (type(ttl) is int and ttl >= 0) or ("cacheScope" in page and not manifest._str(page["cacheScope"])):
            # every page is checked: 0, False and 0.0 compare equal, so a merged value can't vouch for the others
            raise CollectError(f"{method}: a page's ttlMs isn't a non-negative integer or its cacheScope isn't a "
                               "non-empty string")
        pages.append(page)
        if "nextCursor" not in r:  # absent ends pagination; a present null is a bad cursor (Codex on f455156)
            break
        nxt = r["nextCursor"]
        if not isinstance(nxt, str) or not nxt:
            raise CollectError(f"{method}: nextCursor isn't a non-empty string")
        if nxt in seen:
            raise CollectError(f"{method}: the server repeated a cursor")
        seen.add(nxt)
        cursor = nxt
    else:
        raise CollectError(f"{method}: more than {MAX_PAGES} pages")
    for k in manifest.POLICY_KEYS:
        present = [p[k] for p in pages if k in p]
        if not present:
            continue
        if len(present) != len(pages):
            raise CollectError(f"{method}: {k} is on some pages and not others")
        if any(v != present[0] for v in present):
            raise CollectError(f"{method}: pages disagree on {k}")
        policy[k] = present[0]
    return items, policy


def collect(root: Path, sec: dict) -> dict:
    """The `sockets.mcp` object from one fresh session with the configured server."""
    s = _Session(root, sec)
    failed = True
    try:
        d = s.request("server/discover")
        versions, caps = d.get("supportedVersions"), d.get("capabilities")
        info = (d.get("_meta") or {}).get(mcp.META_SERVER_INFO) if isinstance(d.get("_meta"), dict) else None
        if not (isinstance(versions, list) and PROTOCOL in versions):
            raise CollectError(f"server/discover: supportedVersions doesn't include {PROTOCOL}")
        if not isinstance(caps, dict):
            raise CollectError("server/discover: capabilities isn't an object")
        if not (isinstance(info, dict) and manifest._str(info.get("name")) and manifest._str(info.get("version"))):
            raise CollectError("server/discover: no serverInfo name and version in _meta")
        out = {"transport": "stdio", "command": list(sec["command"]), "protocolVersions": versions,
               "serverInfo": info, "capabilities": caps, "tools": [], "resources": [], "resourceTemplates": [],
               "prompts": [], "listPolicy": {}}
        for cap, lst, method, key in LISTS:
            if cap in caps:
                out[lst], pol = _collect_list(s, method, key)
                if pol:
                    out["listPolicy"][lst] = pol
        s.finish()  # an overrun after the last answer still fails (Kate, round 14)
        failed = False
        return out
    finally:
        if failed:
            s.close(failed=True)
        s.release()


def _inside(root: Path, path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False


def _skill_entries(root: Path, paths) -> list[dict]:
    out = []
    for rel in paths:
        f = root / rel / skills.SKILL_FILE
        if manifest._host_path(rel) or manifest._climbs(rel) or not _inside(root, f):
            raise CollectError(f"manifest.skills: {manifest._echo(rel)} isn't a folder inside the repository")
        try:
            fm, _, _ = skills.parse_skill_md(f.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            raise CollectError(f"manifest.skills: cannot read {manifest._echo(rel)}/{skills.SKILL_FILE} "
                               f"({type(exc).__name__})") from None
        out.append({"path": rel, "name": fm.get("name"), "description": fm.get("description")})
    return out


def build(root: Path) -> dict:
    """The manifest for ROOT from its own config and a fresh collection. Raises CollectError or ConfigError."""
    return build_with_section(root)[0]


def build_with_section(root: Path) -> tuple[dict, dict]:
    """(manifest, the validated `manifest` config section it was built from). The caller uses that section, not a
    second read of the config, to find the target (Kate, round 13: the file could change during collection)."""
    # The trust is in this repository's config, so it must be this repository's file: a symlinked `.aec` or
    # config.json (or one resolving outside ROOT) is refused before it is parsed (Codex security review on #118).
    aec_dir, cfg_file = root / ".aec", root / config.CONFIG_PATH
    if aec_dir.is_symlink() or cfg_file.is_symlink() or (cfg_file.exists() and not _inside(root, cfg_file)):
        raise config.ConfigError(f"{config.CONFIG_PATH} or .aec is a symlink or resolves outside the repository; "
                                 "refused before reading it")
    cfg = config.own(root)
    sec = cfg.get("manifest")
    p = section_problems(sec)
    if p:
        raise config.ConfigError("; ".join(p))
    sock = collect(root, sec)
    version = sock["serverInfo"]["version"]
    authority = {k: sec["authority"].get(k, []) for k in a2a.AUTHORITY_KEYS}
    card = None
    if sec.get("a2a") is not None:
        args = dict(sec["a2a"])  # section_problems refused name, description, version and authority
        try:
            card = a2a.build_card(name=sec["tool"]["name"], description=sec["tool"]["description"], version=version,
                                  authority=authority, **args)
        except (a2a.CardError, TypeError) as exc:
            raise config.ConfigError(f"manifest.a2a: the card can't be built ({type(exc).__name__})") from None
    return {
        "manifest": manifest.SCHEMA,
        "tool": {**{k: sec["tool"][k] for k in ("id", "name")}, "version": version,
                 "description": sec["tool"]["description"]},
        "sockets": {"mcp": sock, "a2a": {"agentCard": card} if card is not None else None,
                    "skills": _skill_entries(root, sec.get("skills", [])),
                    "authority": {**authority, "protocol": a2a.AUTHORITY_PROTOCOL},
                    "other": list(sec.get("other", []))},
        "runtime": sec["runtime"],
    }, sec


def diff(expected, actual, where="") -> list[tuple[str, str]]:
    """(kind, JSON path) for every difference: added (in the build, not the file), removed (in the file, not the
    build) or changed. Object key order is ignored; array order and length count."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        out = []
        for k in expected:
            path = f"{where}.{manifest._echo(k)}" if where else manifest._echo(k)
            out += diff(expected[k], actual[k], path) if k in actual else [("added", path)]
        out += [("removed", f"{where}.{manifest._echo(k)}" if where else manifest._echo(k))
                for k in actual if k not in expected]
        return out
    if isinstance(expected, list) and isinstance(actual, list):
        out = [x for i in range(min(len(expected), len(actual))) for x in diff(expected[i], actual[i], f"{where}[{i}]")]
        out += [("added", f"{where}[{i}]") for i in range(len(actual), len(expected))]
        out += [("removed", f"{where}[{i}]") for i in range(len(expected), len(actual))]
        return out
    same = expected == actual and type(expected) is type(actual)
    return [] if same else [("changed", where or "(whole file)")]


def _target(root: Path, sec: dict) -> Path:
    return root / sec.get("path", ".aec/manifest.json")


def add_parser(m_sub) -> None:
    for name, help_text in (("build", "start ROOT's configured MCP server and write the manifest"),
                            ("check", "rebuild in memory and report every difference from the committed manifest")):
        p = m_sub.add_parser(name, help=help_text + "; runs manifest.command from ROOT's .aec/config.json, so it "
                             "needs --trust-config")
        p.add_argument("--root", default=".", help="repository root (default: .)")
        p.add_argument("--trust-config", action="store_true",
                       help="you trust ROOT's .aec/config.json enough to run its manifest.command")


def cli(a) -> int:
    name = f"manifest {a.manifest_cmd}"
    if not a.trust_config:
        print(f"{name}: refused: this runs manifest.command from the repository's .aec/config.json; pass "
              "--trust-config only where you trust that file (a pull request can change it)", file=sys.stderr)
        return 2
    root = Path(a.root)
    try:
        expected, sec = build_with_section(root)
    except config.ConfigError as exc:
        # plain-text rule on every quoted value (unknown keys, bad values), not only the credential patterns
        print(f"{name}: config: {manifest._scrub(manifest.redact(str(exc)))}", file=sys.stderr)
        return 2
    except CollectError as exc:
        print(f"{name}: collection failed: {exc}; nothing written", file=sys.stderr)
        return 2
    problems, _ = manifest.validate(expected, root=root)
    if problems:  # exit 1, not 2: collection worked; what it produced (or the config it copied) is what's wrong
        for p in problems:
            print(f"{name}: the built manifest is invalid: {p}; nothing written", file=sys.stderr)
        return 1
    target = _target(root, sec)
    text = json.dumps(expected, indent=2, ensure_ascii=False) + "\n"
    rel = manifest._echo(sec.get("path", ".aec/manifest.json"))
    if not _inside(root, target):  # a committed symlink must not carry the write or the read out of the repository
        print(f"{name}: {rel} resolves outside the repository; refused", file=sys.stderr)
        return 2
    if a.manifest_cmd == "build":
        try:  # before any file exists: a lone surrogate from the server can't be written as UTF-8 (Codex on f455156)
            data = text.encode("utf-8")
        except UnicodeEncodeError:
            print(f"{name}: the built manifest can't be encoded as UTF-8 (a lone surrogate in a server value); "
                  "nothing written", file=sys.stderr)
            return 2
        tmp = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("wb", dir=target.parent, delete=False, suffix=".tmp") as f:
                tmp = f.name
                f.write(data)
            os.replace(tmp, target)
        except OSError as exc:  # by type only: a message would carry host paths (Kate, round 13)
            if tmp is not None:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
            print(f"{name}: cannot write {rel} ({type(exc).__name__}); the old file, if any, is unchanged",
                  file=sys.stderr)
            return 2
        print(f"{name}: wrote {rel}")
        return 0
    try:
        committed = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"{name}: cannot read {rel} ({type(exc).__name__})", file=sys.stderr)
        return 1
    invalid, _ = manifest.validate(committed, root=root)  # the committed file on its own, too (Kate, round 13)
    for p in invalid:
        print(f"{name}: the committed manifest is invalid: {p}", file=sys.stderr)
    found = diff(expected, committed)
    for kind, path in found:
        print(f"{name}: {kind}: {path}", file=sys.stderr)
    if invalid and not found:
        return 1
    if found:
        print(f"{name}: {rel} differs from a fresh build in {len(found)} place(s); run aec manifest build",
              file=sys.stderr)
        return 1
    print(f"{name}: {rel} matches a fresh build")
    return 0
