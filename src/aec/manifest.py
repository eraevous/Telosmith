"""`aec manifest validate`: check a tool manifest against telosmith.manifest/1.0 (DEC-256 item 7 follow-up).

    aec manifest validate FILE [--root DIR]    exit 0 when FILE is a valid /1.0 manifest, else 1 with the problems

The schema is `docs/integrations/manifest.md` (`AEC-D-manifest-schema@3`, accepted by Zach on Telosmith#103). This
module checks a manifest's shape and its internal agreements; it never launches anything, the manifest's own
`mcp.command` least of all (MAN-06). `aec manifest build|check`, which start the repository's configured server and
compare a fresh build field by field, come in a later slice.

What is checked:
- the objects Telosmith owns (the envelope, `tool`, `sockets`, the `mcp` and `a2a` wrappers, `skills` and `other`
  entries, `authority`, `runtime`, `listPolicy`) have exactly their keys; unknown keys are errors there only. MCP
  and A2A objects embedded in them may carry fields Telosmith doesn't know (rule 8);
- every socket key is present in its one empty form: `mcp`, `a2a` null; `skills`, `other` []; `authority` an object;
- `manifest` names major 1 and a minor this checker knows; a newer minor is refused naming both versions;
- the card passes `aec a2a check`; when there is a card it carries the authority extension exactly once and its params
  equal `sockets.authority` as JSON; `protocol` is the undecided placeholder;
- `tool.version` equals `mcp.serverInfo.version` and the card's `version`;
- `runtime.network` and `runtime.model_calls` are never, optional, required or unknown;
- no string anywhere looks like a credential, an environment assignment or a host path (in `command`, skill paths
  and `other` locations). Diagnostics name where, never the value. A schema check can't prove a server's text holds
  no secret; this catches the shapes it can recognise.
- with `--root`, each skill folder exists under it, passes `aec skills check`, and its name and description match.

Notes (not errors): `other` sockets are listed as transitional, `unknown` runtime answers are listed, and declared
grants are listed as declarations (the protocol is undecided, so nothing is granted).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

from . import a2a, skills

FAMILY = "telosmith.manifest"
MAJOR, MINOR = 1, 0
SCHEMA = f"{FAMILY}/{MAJOR}.{MINOR}"
TOP_KEYS = ("manifest", "tool", "sockets", "runtime")
TOOL_KEYS = ("id", "name", "version", "description")
SOCKET_KEYS = ("mcp", "a2a", "skills", "authority", "other")
MCP_KEYS = ("transport", "command", "protocolVersions", "serverInfo", "capabilities",
            "tools", "resources", "resourceTemplates", "prompts", "listPolicy")
MCP_LISTS = ("tools", "resources", "resourceTemplates", "prompts")
POLICY_KEYS = ("ttlMs", "cacheScope")
SKILL_KEYS = ("path", "name", "description")
OTHER_KEYS = ("id", "kind", "direction", "location", "planned")
AUTHORITY_KEYS = (*a2a.AUTHORITY_KEYS, "protocol")
RUNTIME_KEYS = ("network", "model_calls")
RUNTIME_VALUES = ("never", "optional", "required", "unknown")
_VERSION = re.compile(r"telosmith\.manifest/(\d+)\.(\d+)")
_SECRETS = (
    ("a credential-shaped token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
                                             r"|xox[abposr]-[A-Za-z0-9-]{6,}|sk-[A-Za-z0-9_-]{20,}"
                                             r"|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,})")),
    ("a URL with credentials", re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@", re.I)),
    ("an environment assignment", re.compile(r"(?:^|\s)[A-Z][A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD|PASS|AUTH)"
                                             r"[A-Z0-9_]*=\S")),
)


def _str(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _keys(obj, keys, where, problems, *, required=True) -> bool:
    """`obj` is an object with exactly `keys` (all present when `required`); False when it isn't an object."""
    if not isinstance(obj, dict):
        problems.append(f"{where} must be an object")
        return False
    extra = sorted(k for k in obj if k not in keys)
    if extra:
        problems.append(f"{where} has unknown key(s) {extra} (allowed: {list(keys)})")
    if required:
        for k in keys:
            if k not in obj:
                problems.append(f"{where}.{k} is missing")
    return True


def _host_path(v: str) -> bool:
    return bool(PurePosixPath(v).anchor or PureWindowsPath(v).anchor or v.startswith("~"))


def _climbs(v: str) -> bool:
    return ".." in PurePosixPath(v).parts or ".." in PureWindowsPath(v).parts


def _scan(v, where, problems) -> None:
    """Every string anywhere under `v`: report credential-shaped values by location, never by value."""
    if isinstance(v, str):
        for what, rx in _SECRETS:
            if rx.search(v):
                problems.append(f"{where} holds {what}; a manifest carries no secrets or environment values")
                return
    elif isinstance(v, dict):
        for k, x in v.items():
            _scan(x, f"{where}.{k}", problems)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            _scan(x, f"{where}[{i}]", problems)


def _check_version(v, problems) -> None:
    m = _VERSION.fullmatch(v) if isinstance(v, str) else None
    if not m:
        problems.append(f"manifest must be '{FAMILY}/<major>.<minor>' (this checker reads {SCHEMA}), got {v!r}"[:200])
    elif int(m.group(1)) != MAJOR:
        problems.append(f"manifest is {v}; this checker reads major {MAJOR} only ({SCHEMA})")
    elif int(m.group(2)) > MINOR:
        problems.append(f"manifest is {v}, newer than this checker's {SCHEMA}; update Telosmith to read it")


def _check_mcp(mcp, tool_version, problems) -> None:
    w = "sockets.mcp"
    if not _keys(mcp, MCP_KEYS, w, problems):
        return
    if mcp.get("transport") != "stdio":
        problems.append(f"{w}.transport must be 'stdio' in /1.0")
    cmd = mcp.get("command")
    if not (isinstance(cmd, list) and cmd and all(_str(c) for c in cmd)):
        problems.append(f"{w}.command must be a non-empty argv list of non-empty strings")
    else:
        for i, c in enumerate(cmd):
            if _host_path(c):
                problems.append(f"{w}.command[{i}] is a host path; name the program, not where it is installed")
    pv = mcp.get("protocolVersions")
    if not (isinstance(pv, list) and pv and all(_str(x) for x in pv)):
        problems.append(f"{w}.protocolVersions must be a non-empty list of strings")
    si = mcp.get("serverInfo")
    if not (isinstance(si, dict) and _str(si.get("name")) and _str(si.get("version"))):
        problems.append(f"{w}.serverInfo must be an object with a name and a version")
    elif tool_version is not None and si["version"] != tool_version:
        problems.append(f"{w}.serverInfo.version must equal tool.version")
    if not isinstance(mcp.get("capabilities"), dict):
        problems.append(f"{w}.capabilities must be an object")
    for lst in MCP_LISTS:
        items = mcp.get(lst)
        if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
            problems.append(f"{w}.{lst} must be a list of objects")
    for i, t in enumerate(mcp.get("tools") if isinstance(mcp.get("tools"), list) else []):
        if isinstance(t, dict) and not (_str(t.get("name")) and isinstance(t.get("inputSchema"), dict)):
            problems.append(f"{w}.tools[{i}] needs a name and an inputSchema object (MCP Tool)")
    pol = mcp.get("listPolicy")
    if _keys(pol, MCP_LISTS, f"{w}.listPolicy", problems, required=False):
        for lst, p in pol.items():
            pw = f"{w}.listPolicy.{lst}"
            if not _keys(p, POLICY_KEYS, pw, problems, required=False):
                continue
            ttl = p.get("ttlMs")
            if "ttlMs" in p and not (isinstance(ttl, int) and not isinstance(ttl, bool) and ttl >= 0):
                problems.append(f"{pw}.ttlMs must be a non-negative integer")
            if "cacheScope" in p and not _str(p.get("cacheScope")):
                problems.append(f"{pw}.cacheScope must be a non-empty string")


def _check_a2a(sock, authority, tool_version, problems) -> None:
    w = "sockets.a2a"
    if not _keys(sock, ("agentCard",), w, problems):
        return
    card = sock.get("agentCard")
    card_problems = a2a.validate_card(card)
    problems.extend(f"{w}.agentCard: {p}" for p in card_problems)
    if not isinstance(card, dict):
        return
    if tool_version is not None and card.get("version") != tool_version:
        problems.append(f"{w}.agentCard.version must equal tool.version")
    exts = (card.get("capabilities") or {}).get("extensions") if isinstance(card.get("capabilities"), dict) else None
    found = [e for e in exts if isinstance(e, dict) and e.get("uri") == a2a.AUTHORITY_EXTENSION_URI] \
        if isinstance(exts, list) else []
    if len(found) != 1:
        problems.append(f"{w}.agentCard must carry the authority extension ({a2a.AUTHORITY_EXTENSION_URI}) "
                        f"exactly once, found {len(found)}")
    elif isinstance(authority, dict) and found[0].get("params") != authority:
        problems.append(f"{w}.agentCard's authority extension params must equal sockets.authority (as JSON)")


def _check_authority(auth, problems, notes) -> None:
    w = "sockets.authority"
    if not _keys(auth, AUTHORITY_KEYS, w, problems):
        return
    for k in a2a.AUTHORITY_KEYS:
        v = auth.get(k)
        if k in auth and not (isinstance(v, list) and all(_str(x) for x in v)):
            problems.append(f"{w}.{k} must be a list of non-empty strings ([] for none)")
    if "protocol" in auth and auth.get("protocol") != a2a.AUTHORITY_PROTOCOL:
        problems.append(f"{w}.protocol must be {a2a.AUTHORITY_PROTOCOL!r} until a protocol is adopted")
    if isinstance(auth.get("grants"), list) and auth["grants"]:
        notes.append(f"{w}.grants declares {len(auth['grants'])} grant(s); the protocol is undecided, "
                     "so nothing is granted")


def _check_skills(items, root, problems) -> None:
    if not isinstance(items, list):
        problems.append("sockets.skills must be a list ([] for none)")
        return
    for i, s in enumerate(items):
        w = f"sockets.skills[{i}]"
        if not _keys(s, SKILL_KEYS, w, problems):
            continue
        if not all(_str(s.get(k)) for k in SKILL_KEYS):
            problems.append(f"{w} needs non-empty path, name and description")
            continue
        if _host_path(s["path"]) or _climbs(s["path"]):
            problems.append(f"{w}.path must be relative to the repository and stay inside it")
            continue
        if root is None:
            continue
        folder = Path(root) / s["path"]
        found = skills.check_skill_dir(folder)
        if found:
            problems.extend(f"{w} ({s['path']}): {p}" for p in found)
            continue
        fm, _, _ = skills.parse_skill_md((folder / skills.SKILL_FILE).read_text(encoding="utf-8"))
        for k in ("name", "description"):
            if fm.get(k) != s[k]:
                problems.append(f"{w}.{k} must equal the {k} in {s['path']}/{skills.SKILL_FILE}")


def _check_other(items, problems, notes) -> None:
    if not isinstance(items, list):
        problems.append("sockets.other must be a list ([] for none)")
        return
    for i, o in enumerate(items):
        w = f"sockets.other[{i}]"
        if not _keys(o, OTHER_KEYS, w, problems):
            continue
        if not all(isinstance(o.get(k), str) for k in OTHER_KEYS) or not all(_str(o.get(k)) for k in
                                                                            ("id", "kind", "location")):
            problems.append(f"{w}: id, kind and location are non-empty strings; direction and planned are strings")
            continue
        if o["direction"] not in ("in", "out"):
            problems.append(f"{w}.direction must be 'in' or 'out'")
        if _host_path(o["location"]):
            problems.append(f"{w}.location is a host path; give it relative to the repository")
        notes.append(f"{w} '{o['id']}' is transitional ({o['kind']}, {o['direction']}); planned: "
                     f"{o['planned'] or 'not named'}")


def validate(m, *, root=None) -> tuple[list[str], list[str]]:
    """(problems, notes) for manifest `m`; no problems means valid. Reads skill folders only when `root` is given.
    Never raises on bad input and never runs anything."""
    problems, notes = [], []
    if not _keys(m, TOP_KEYS, "manifest file", problems):
        return problems, notes
    _check_version(m.get("manifest"), problems)
    tool, tool_version = m.get("tool"), None
    if _keys(tool, TOOL_KEYS, "tool", problems):
        bad = [k for k in TOOL_KEYS if k in tool and not _str(tool[k])]
        if bad:
            problems.append(f"tool.{', tool.'.join(bad)} must be non-empty strings")
        tool_version = tool.get("version") if _str(tool.get("version")) else None
    sockets = m.get("sockets")
    if _keys(sockets, SOCKET_KEYS, "sockets", problems):
        auth = sockets.get("authority")
        if "mcp" in sockets and sockets["mcp"] is not None:
            _check_mcp(sockets["mcp"], tool_version, problems)
        if "a2a" in sockets and sockets["a2a"] is not None:
            _check_a2a(sockets["a2a"], auth, tool_version, problems)
        if "skills" in sockets:
            _check_skills(sockets["skills"], root, problems)
        if "authority" in sockets:
            _check_authority(auth, problems, notes)
        if "other" in sockets:
            _check_other(sockets["other"], problems, notes)
    rt = m.get("runtime")
    if _keys(rt, RUNTIME_KEYS, "runtime", problems):
        for k in RUNTIME_KEYS:
            if k in rt and rt[k] not in RUNTIME_VALUES:
                problems.append(f"runtime.{k} must be one of {list(RUNTIME_VALUES)}")
            elif rt.get(k) == "unknown":
                notes.append(f"runtime.{k} is unknown (an honest answer; not established)")
    _scan(m, "manifest", problems)
    return [p.replace("manifest.", "", 1) if p.startswith("manifest.") else p for p in problems], notes


def add_parser(sub) -> None:
    p = sub.add_parser("manifest", help=f"check a tool manifest ({SCHEMA}; DEC-256 item 7)")
    m_sub = p.add_subparsers(dest="manifest_cmd", required=True)
    v = m_sub.add_parser("validate", help="exit 0 when FILE is a valid manifest, else 1 with the problems; "
                                          "never runs anything")
    v.add_argument("file")
    v.add_argument("--root", help="repository root, to check the skill folders the manifest names")


def cli(a, ap) -> int:
    try:
        m = json.loads(Path(a.file).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"manifest validate: cannot read {a.file}: {type(exc).__name__}", file=sys.stderr)
        return 1
    problems, notes = validate(m, root=Path(a.root) if a.root else None)
    for p in problems:
        print(f"manifest validate: {p}", file=sys.stderr)
    for n in notes:
        print(f"manifest validate: note: {n}")
    if problems:
        return 1
    print(f"manifest validate: {a.file} is a valid {m['manifest']} manifest"
          + ("" if a.root else " (skill folders not checked; pass --root)"))
    return 0
