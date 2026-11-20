"""A2A Agent Card for a Telosmith-based project (DEC-256 item 5, slice 2; an experiment under DEC-200).

An Agent Card is the JSON document an A2A client fetches to learn what an agent is, where to reach
it and which skills it offers. This module builds one from plain values and checks a card against
the fields A2A 1.0 requires, so every Telosmith-based project describes itself the same way.

    aec a2a card --name N --description D --version V --url URL [--binding JSONRPC]
                 [--skill ID=NAME|DESCRIPTION|tag1,tag2 ...] [--provider ORG=URL] [-o FILE]
    aec a2a check FILE        exit 0 when the card has every required field, else 1 with the problems

Target: A2A protocol version 1.0, where the endpoint and protocol version live per entry in
`supportedInterfaces` (the 0.3 top-level `url`, `preferredTransport` and `protocolVersion` are gone).
Not covered: serving the card over HTTP, signing it (`signatures`), security schemes, the extended
card, and any A2A task handling. The card describes; it grants nothing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

PROTOCOL_VERSION = "1.0"
WELL_KNOWN_PATH = ".well-known/agent-card.json"
BINDINGS = ("JSONRPC", "GRPC", "HTTP+JSON")  # A2A names these; the field is open, so others are allowed
CARD_REQUIRED = ("name", "description", "supportedInterfaces", "version", "capabilities",
                 "defaultInputModes", "defaultOutputModes", "skills")
INTERFACE_REQUIRED = ("url", "protocolBinding", "protocolVersion")
SKILL_REQUIRED = ("id", "name", "description", "tags")
PROVIDER_REQUIRED = ("organization", "url")


class CardError(ValueError):
    """A value given to build_card cannot make a valid card."""


def skill(id: str, name: str, description: str, tags, examples=None) -> dict:
    """One AgentSkill. `tags` is a non-empty list of keywords."""
    out = {"id": id, "name": name, "description": description, "tags": list(tags)}
    if examples:
        out["examples"] = list(examples)
    return out


def build_card(*, name: str, description: str, version: str, url: str, binding: str = "JSONRPC",
               skills=(), provider: dict | None = None, streaming: bool = False,
               push_notifications: bool = False, input_modes=("text/plain",),
               output_modes=("application/json",), documentation_url: str | None = None) -> dict:
    """Return an A2A 1.0 Agent Card as a dict, or raise CardError naming every problem."""
    card = {
        "name": name,
        "description": description,
        "supportedInterfaces": [{"url": url, "protocolBinding": binding, "protocolVersion": PROTOCOL_VERSION}],
        "version": version,
        "capabilities": {"streaming": bool(streaming), "pushNotifications": bool(push_notifications)},
        "defaultInputModes": list(input_modes),
        "defaultOutputModes": list(output_modes),
        "skills": [dict(s) for s in skills],
    }
    if provider is not None:
        card["provider"] = dict(provider)
    if documentation_url:
        card["documentationUrl"] = documentation_url
    problems = validate_card(card)
    if problems:
        raise CardError("; ".join(problems))
    return card


def _nonempty_str(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _http_url(v) -> bool:
    if not _nonempty_str(v):
        return False
    try:
        p = urlparse(v)
    except ValueError:  # e.g. "https://[": a malformed URL is a problem to report, not a crash
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


def _grpc_address(v) -> bool:
    """gRPC interfaces use `host:port` (A2A AgentInterface); a URL is also accepted."""
    if not _nonempty_str(v):
        return False
    if "://" in v:
        try:
            return bool(urlparse(v).netloc)
        except ValueError:
            return False
    host, sep, port = v.rpartition(":")
    return (bool(sep) and host != "" and not any(c.isspace() or c == "/" for c in host)
            and port.isdigit() and 0 < int(port) < 65536)


def _interface_url_problem(f: dict, where: str) -> str | None:
    """HTTP-based (or missing) bindings need an absolute http(s) URL; GRPC host:port; other (open) bindings a non-empty string."""
    binding, url = f.get("protocolBinding"), f["url"]
    if binding == "GRPC":
        return None if _grpc_address(url) else f"{where}.url must be host:port (or a URL) for GRPC"
    if _nonempty_str(binding) and binding not in BINDINGS:
        return None if _nonempty_str(url) else f"{where}.url must be a non-empty string"
    # JSONRPC, HTTP+JSON, or a missing binding (already reported): the strict check
    return None if _http_url(url) else f"{where}.url must be an absolute http(s) URL"


def _str_list(v, *, nonempty: bool) -> bool:
    return isinstance(v, list) and all(_nonempty_str(x) for x in v) and (bool(v) or not nonempty)


def validate_card(card) -> list[str]:
    """Problems that stop `card` being an A2A 1.0 Agent Card; empty when none. Never raises."""
    if not isinstance(card, dict):
        return ["the card is not a JSON object"]
    problems = [f"missing required field {k!r}" for k in CARD_REQUIRED if k not in card]
    for k in ("name", "description", "version"):
        if k in card and not _nonempty_str(card[k]):
            problems.append(f"{k!r} must be a non-empty string")
    for k in ("defaultInputModes", "defaultOutputModes"):
        if k in card and not _str_list(card[k], nonempty=True):
            problems.append(f"{k!r} must be a non-empty list of media types")
    if "capabilities" in card:
        caps = card["capabilities"]
        if not isinstance(caps, dict):
            problems.append("'capabilities' must be an object")
        else:
            for k in ("streaming", "pushNotifications", "extendedAgentCard"):
                if k in caps and not isinstance(caps[k], bool):
                    problems.append(f"'capabilities.{k}' must be true or false")
    if "supportedInterfaces" in card:
        ifaces = card["supportedInterfaces"]
        if not isinstance(ifaces, list) or not ifaces:
            problems.append("'supportedInterfaces' must be a non-empty list")
        else:
            for i, f in enumerate(ifaces):
                where = f"supportedInterfaces[{i}]"
                if not isinstance(f, dict):
                    problems.append(f"{where} must be an object")
                    continue
                problems += [f"{where} is missing {k!r}" for k in INTERFACE_REQUIRED if k not in f]
                if "url" in f:
                    problem = _interface_url_problem(f, where)
                    if problem:
                        problems.append(problem)
                for k in ("protocolBinding", "protocolVersion"):
                    if k in f and not _nonempty_str(f[k]):
                        problems.append(f"{where}.{k} must be a non-empty string")
    if "skills" in card:
        skills = card["skills"]
        if not isinstance(skills, list):
            problems.append("'skills' must be a list")
        else:
            seen = set()
            for i, s in enumerate(skills):
                where = f"skills[{i}]"
                if not isinstance(s, dict):
                    problems.append(f"{where} must be an object")
                    continue
                problems += [f"{where} is missing {k!r}" for k in SKILL_REQUIRED if k not in s]
                for k in ("id", "name", "description"):
                    if k in s and not _nonempty_str(s[k]):
                        problems.append(f"{where}.{k} must be a non-empty string")
                if "tags" in s and not _str_list(s["tags"], nonempty=True):
                    problems.append(f"{where}.tags must be a non-empty list of strings")
                if _nonempty_str(s.get("id")):
                    if s["id"] in seen:
                        problems.append(f"{where}.id {s['id']!r} repeats an earlier skill id")
                    seen.add(s["id"])
    if "provider" in card:
        prov = card["provider"]
        if not isinstance(prov, dict):
            problems.append("'provider' must be an object")
        else:
            problems += [f"provider is missing {k!r}" for k in PROVIDER_REQUIRED if k not in prov]
            if "organization" in prov and not _nonempty_str(prov["organization"]):
                problems.append("provider.organization must be a non-empty string")
            if "url" in prov and not _http_url(prov["url"]):
                problems.append("provider.url must be an absolute http(s) URL")
    if "documentationUrl" in card and not _http_url(card["documentationUrl"]):
        problems.append("'documentationUrl' must be an absolute http(s) URL")
    return problems


def _parse_skill(text: str) -> dict:
    """ID=NAME|DESCRIPTION|tag1,tag2"""
    sid, sep, rest = text.partition("=")
    parts = rest.split("|")
    if not sep or len(parts) != 3:
        raise CardError(f"--skill {text!r}: expected ID=NAME|DESCRIPTION|tag1,tag2")
    tags = [t.strip() for t in parts[2].split(",") if t.strip()]
    return skill(sid.strip(), parts[0].strip(), parts[1].strip(), tags)


def _parse_provider(text: str) -> dict:
    org, sep, url = text.partition("=")
    if not sep:
        raise CardError(f"--provider {text!r}: expected ORGANIZATION=URL")
    return {"organization": org.strip(), "url": url.strip()}


def add_parser(sub) -> None:
    p = sub.add_parser("a2a", help="build or check an A2A 1.0 Agent Card for this project (DEC-256 item 5)")
    a2a_sub = p.add_subparsers(dest="a2a_cmd", required=True)
    c = a2a_sub.add_parser("card", help="print (or write) an Agent Card built from the flags")
    c.add_argument("--name", required=True)
    c.add_argument("--description", required=True)
    c.add_argument("--version", required=True, help="the project's version, not the protocol's")
    c.add_argument("--url", required=True, help="where the agent's A2A endpoint is served")
    c.add_argument("--binding", default="JSONRPC", help="protocolBinding: " + ", ".join(BINDINGS) + " (default JSONRPC)")
    c.add_argument("--skill", action="append", default=[], metavar="ID=NAME|DESCRIPTION|TAGS")
    c.add_argument("--provider", metavar="ORGANIZATION=URL")
    c.add_argument("--documentation-url")
    c.add_argument("--streaming", action="store_true")
    c.add_argument("-o", "--out", help=f"write here (conventionally {WELL_KNOWN_PATH}); never overwrites")
    k = a2a_sub.add_parser("check", help="exit 0 when FILE is an A2A 1.0 Agent Card, else 1 with the problems")
    k.add_argument("file")


def cli(a, ap) -> int:
    if a.a2a_cmd == "check":
        try:
            card = json.loads(Path(a.file).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            print(f"a2a check: cannot read {a.file}: {type(exc).__name__}", file=sys.stderr)
            return 1
        problems = validate_card(card)
        for p in problems:
            print(f"a2a check: {p}", file=sys.stderr)
        if not problems:
            print(f"a2a check: {a.file} is an A2A {PROTOCOL_VERSION} Agent Card "
                  f"({len(card['skills'])} skill(s))")
        return 1 if problems else 0
    try:
        card = build_card(name=a.name, description=a.description, version=a.version, url=a.url,
                          binding=a.binding, skills=[_parse_skill(s) for s in a.skill],
                          provider=_parse_provider(a.provider) if a.provider else None,
                          documentation_url=a.documentation_url, streaming=a.streaming)
    except CardError as exc:
        print(f"a2a card: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(card, indent=2) + "\n"
    if not a.out:
        sys.stdout.write(text)
        return 0
    out = Path(a.out)
    if out.exists() or out.is_symlink():
        print(f"a2a card: {out} exists; not overwriting", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x", encoding="utf-8") as fh:
        fh.write(text)
    print(f"a2a card: wrote {out}")
    return 0
