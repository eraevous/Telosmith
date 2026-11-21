"""Agent Skills folders for a Telosmith-based project (DEC-256 item 5, slice 3; an experiment under DEC-200).

An Agent Skill is a folder holding a `SKILL.md`: YAML front matter (`name`, `description`, and optional
`license`, `compatibility`, `metadata`, `allowed-tools`) followed by Markdown instructions, with optional
`scripts/`, `references/` and `assets/` beside it. DEC-177 makes it the know-how socket. This module writes
a new skill folder and checks existing ones against the specification, so every Telosmith-based project
ships its know-how the same way.

    aec skills new NAME --description D [--dir DIR] [--license L] [--compatibility C]
                                        write DIR/NAME/SKILL.md (default DIR: skills); never overwrites
    aec skills check PATH...            exit 0 when every skill folder under PATH is valid, else 1

Target: the Agent Skills specification as read on 2026-11-21 (https://agentskills.io/specification).
The checker reads a YAML subset, the one `new` writes and most skills use: `key: value` lines with plain,
single- or double-quoted scalars, and `metadata:` followed by indented `key: value` lines (keys plain or
quoted). A plain value YAML would read as null, a boolean, a number or a date is reported: quote it. Anything else
(block scalars, lists, flow mappings, anchors) is reported as outside the subset, not guessed at.
Not covered: running a skill, checking its scripts, or `allowed-tools` semantics (experimental upstream).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

SPEC_URL = "https://agentskills.io/specification"
SKILL_FILE = "SKILL.md"
FIELDS = ("name", "description", "license", "compatibility", "metadata", "allowed-tools")
REQUIRED = ("name", "description")
NAME_MAX, DESCRIPTION_MAX, COMPATIBILITY_MAX = 64, 1024, 500
_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_KEY_LINE = re.compile(r"([A-Za-z0-9_-]+):(?:[ \t]+(.*))?$")
# Plain scalars a YAML loader (1.1 or 1.2 core schema) reads as something other than a string.
_NOT_A_STRING = re.compile(
    r"~|null|Null|NULL|true|True|TRUE|false|False|FALSE|yes|Yes|YES|no|No|NO|on|On|ON|off|Off|OFF|y|Y|n|N"
    r"|[-+]?(0|[1-9][0-9_]*|0[0-7_]+|0o[0-7_]+|0x[0-9a-fA-F_]+|0b[01_]+)"
    r"|[-+]?(\.[0-9]+|[0-9][0-9_]*(\.[0-9_]*)?)([eE][-+]?[0-9]+)?"
    r"|[-+]?\.(inf|Inf|INF)|\.(nan|NaN|NAN)"
    r"|[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}([Tt ].*)?")


class SkillError(ValueError):
    """A value given to render_skill or new_skill cannot make a valid skill."""


# --- reading -----------------------------------------------------------------------------------------

def _scalar(raw: str, where: str, problems: list) -> str | None:
    """One YAML scalar from the subset: plain, 'single' or "double" quoted. None when outside the subset."""
    raw = raw.strip()
    if raw.startswith('"'):
        try:
            value, end = json.JSONDecoder().raw_decode(raw)  # JSON escapes are valid YAML double-quoted escapes
        except json.JSONDecodeError:
            problems.append(f"{where}: unterminated or malformed double-quoted string")
            return None
        if raw[end:].strip() and not raw[end:].strip().startswith("#"):
            problems.append(f"{where}: text after the closing quote")
            return None
        return value
    if raw.startswith("'"):
        m = re.fullmatch(r"'((?:[^']|'')*)'\s*(#.*)?", raw)
        if not m:
            problems.append(f"{where}: unterminated single-quoted string")
            return None
        return m.group(1).replace("''", "'")
    if raw[:1] in ("|", ">", "[", "{", "&", "*", "!", "@", "`"):
        problems.append(f"{where}: {raw[:1]!r} starts YAML outside the subset this checker reads "
                        "(use a plain or quoted one-line value)")
        return None
    if raw[:1] in (",", "%", "#", "]", "}") or re.match(r"[-?:](\s|$)", raw):
        # YAML can't start a plain scalar with these (`- x` is a list, `? x` a complex key, `#` a comment)
        problems.append(f"{where}: a plain value may not start with {raw[:2].strip()!r} (quote it)")
        return None
    value = re.split(r"\s+#", raw, maxsplit=1)[0].rstrip()
    if ": " in value:
        problems.append(f"{where}: a plain value may not contain ': ' (quote it)")
        return None
    if _NOT_A_STRING.fullmatch(value):
        problems.append(f"{where}: {value!r} is a YAML null, boolean, number or date, not a string "
                        "(quote it if text is meant)")
        return None
    return value


def _mapping_line(text: str, where: str, problems: list):
    """(key, raw value) for an indented `key: value` line; the key may be plain or quoted. None on a problem."""
    if text[:1] in ('"', "'"):
        m = re.match(r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^']|'')*')[ \t]*:(?:[ \t]+(.*))?$", text)
        if not m or m.group(2) is None:
            problems.append(f"{where}: expected 'key: value' inside the mapping")
            return None
        key = _scalar(m.group(1), where, problems)
        return None if key is None else (key, m.group(2))
    m = _KEY_LINE.match(text)
    if not m or m.group(2) is None:
        problems.append(f"{where}: expected 'key: value' inside the mapping")
        return None
    if _NOT_A_STRING.fullmatch(m.group(1)):
        problems.append(f"{where}: key {m.group(1)!r} is a YAML null, boolean, number or date, not a string "
                        "(quote it)")
        return None
    return m.group(1), m.group(2)


def parse_skill_md(text: str) -> tuple[dict, str, list[str]]:
    """(front matter, body, problems) for the text of a SKILL.md. Never raises."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text, ["SKILL.md must start with a '---' line opening the YAML front matter"]
    try:
        close = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}, text, ["the front matter has no closing '---' line"]
    fm: dict = {}
    problems: list[str] = []
    current_map = map_indent = None
    opened: dict = {}
    for n, line in enumerate(lines[1:close], start=2):
        where = f"line {n}"
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1] in (" ", "\t"):
            if current_map is None:
                problems.append(f"{where}: indented line outside a mapping")
                continue
            indent = line[:len(line) - len(line.lstrip(" \t"))]
            if "\t" in indent:
                problems.append(f"{where}: a tab in indentation (YAML allows spaces only)")
                continue
            if map_indent is None:
                map_indent = indent
            elif indent != map_indent:
                problems.append(f"{where}: indented {len(indent)} spaces where the mapping's entries use "
                                f"{len(map_indent)} (nesting is outside the subset)")
                continue
            parsed = _mapping_line(line.strip(), where, problems)
            if parsed is None:
                continue
            key, raw_value = parsed
            if key in current_map:
                problems.append(f"{where}: repeated key {key!r}")
                continue
            value = _scalar(raw_value, where, problems)
            if value is not None:
                current_map[key] = value
            continue
        current_map = map_indent = None
        m = _KEY_LINE.match(line)
        if not m:
            problems.append(f"{where}: expected 'key: value'")
            continue
        key, raw = m.group(1), m.group(2)
        if key in fm:
            problems.append(f"{where}: repeated key {key!r}")
            continue
        if raw is None or raw.strip() == "" or raw.strip().startswith("#"):
            fm[key] = current_map = {}  # a mapping follows (only metadata may be one)
            opened[key] = where
            continue
        value = _scalar(raw, where, problems)
        if value is not None:
            fm[key] = value
    for key, where in opened.items():
        if fm.get(key) == {}:  # `key:` with nothing under it is YAML null, not an empty mapping
            del fm[key]
            problems.append(f"{where}: {key!r} has no value (YAML reads it as null); give a value or drop the key")
    body = "\n".join(lines[close + 1:])
    return fm, body, problems


def validate_frontmatter(fm, dir_name: str | None = None) -> list[str]:
    """Problems that stop `fm` being Agent Skills front matter; empty when none. Never raises."""
    if not isinstance(fm, dict):
        return ["the front matter is not a mapping"]
    problems = [f"missing required field {k!r}" for k in REQUIRED if k not in fm]
    problems += [f"unknown field {k!r} (the specification defines: {', '.join(FIELDS)})"
                 for k in fm if k not in FIELDS]
    for k in ("name", "description", "license", "compatibility", "allowed-tools"):
        if k in fm and not isinstance(fm[k], str):
            problems.append(f"{k!r} must be a string")
    name = fm.get("name")
    if isinstance(name, str):
        if not 1 <= len(name) <= NAME_MAX:
            problems.append(f"'name' must be 1 to {NAME_MAX} characters")
        if not _NAME.fullmatch(name):
            problems.append("'name' must be lowercase a-z, 0-9 and single hyphens, not starting or ending with one")
        if dir_name is not None and name != dir_name:
            problems.append(f"'name' {name!r} must match the folder name {dir_name!r}")
    desc = fm.get("description")
    if isinstance(desc, str) and not (desc.strip() and len(desc) <= DESCRIPTION_MAX):
        problems.append(f"'description' must be non-empty and at most {DESCRIPTION_MAX} characters")
    comp = fm.get("compatibility")
    if isinstance(comp, str) and not (comp.strip() and len(comp) <= COMPATIBILITY_MAX):
        problems.append(f"'compatibility' must be 1 to {COMPATIBILITY_MAX} characters")
    if "license" in fm and isinstance(fm["license"], str) and not fm["license"].strip():
        problems.append("'license' must not be empty")
    if "metadata" in fm:
        md = fm["metadata"]
        if not isinstance(md, dict):
            problems.append("'metadata' must be a mapping of string keys to string values")
        elif not all(isinstance(k, str) and isinstance(v, str) for k, v in md.items()):
            problems.append("'metadata' values must be strings")
    return problems


def check_skill_dir(path) -> list[str]:
    """Problems with one skill folder (its SKILL.md and front matter); empty when valid. Never raises."""
    folder = Path(path)
    skill_md = folder / SKILL_FILE
    if skill_md.is_symlink() or not skill_md.is_file():
        return [f"{SKILL_FILE} is missing (or is not a regular file)"]
    try:
        text = skill_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"cannot read {SKILL_FILE}: {type(exc).__name__}"]
    fm, body, problems = parse_skill_md(text)
    if problems and not fm:
        return problems
    return problems + validate_frontmatter(fm, folder.resolve().name)


def find_skill_dirs(path) -> list[Path]:
    """`path` itself when it holds a SKILL.md, else its immediate subfolders that do."""
    p = Path(path)
    if (p / SKILL_FILE).exists() or (p / SKILL_FILE).is_symlink():
        return [p]
    if not p.is_dir():
        return []
    return sorted(d for d in p.iterdir() if d.is_dir() and not d.is_symlink()
                  and ((d / SKILL_FILE).exists() or (d / SKILL_FILE).is_symlink()))


# --- writing -----------------------------------------------------------------------------------------

def _quoted(v: str) -> str:
    # Escape the Unicode line breaks str.splitlines() splits on, so the value stays on one line.
    out = json.dumps(v, ensure_ascii=False)
    for ch in ("\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"):
        out = out.replace(ch, f"\\u{ord(ch):04x}")
    return out


def render_skill(*, name: str, description: str, body: str = "", license: str | None = None,
                 compatibility: str | None = None, metadata: dict | None = None) -> str:
    """The text of a SKILL.md, or SkillError naming every problem. Values are double-quoted, so any text is safe."""
    fm = {"name": name, "description": description}
    if license is not None:
        fm["license"] = license
    if compatibility is not None:
        fm["compatibility"] = compatibility
    if metadata is not None and metadata != {}:  # an empty mapping is omitted: a bare `metadata:` is YAML null
        fm["metadata"] = dict(metadata) if isinstance(metadata, dict) else metadata
    problems = validate_frontmatter(fm, name if isinstance(name, str) else None)
    if problems:
        raise SkillError("; ".join(problems))
    out = ["---"]
    for k, v in fm.items():
        if k == "metadata":
            out.append("metadata:")
            out += [f"  {_quoted(mk)}: {_quoted(mv)}" for mk, mv in v.items()]
        else:
            out.append(f"{k}: {_quoted(v)}")
    out.append("---")
    return "\n".join(out) + "\n" + (body if body.endswith("\n") or not body else body + "\n")


def _template_body(name: str) -> str:
    return (f"# {name}\n\n"
            "## When to use\n\n"
            "Say when an agent should load this skill, in terms a task description would use.\n\n"
            "## Steps\n\n"
            "1. The first thing to do.\n"
            "2. How to check it worked.\n\n"
            "Keep this file under 500 lines; put longer material in `references/` and code in `scripts/`.\n")


def new_skill(dir, name: str, description: str, **kwargs) -> Path:
    """Write DIR/NAME/SKILL.md from the template and return its path. Never overwrites; SkillError or OSError."""
    text = render_skill(name=name, description=description, body=_template_body(name), **kwargs)
    folder = Path(dir) / name
    target = folder / SKILL_FILE
    base = _check_write_path(Path(dir), name)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"{target} exists; not overwriting")
    folder.mkdir(parents=True, exist_ok=True)
    _check_write_path(Path(dir), name)  # again after mkdir: nothing may have been swapped for a link
    if not folder.resolve().is_relative_to(base):
        raise SkillError(f"{folder} resolves outside {base}; not writing")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return target


def _check_write_path(dir: Path, name: str) -> Path:
    """Refuse a symlink in any written component, and return the directory the write must stay inside.

    A relative DIR (the default `skills`) is checked component by component from the working directory,
    so a symlink committed in a checkout can't redirect the write; the result must stay inside the working
    directory. An absolute DIR is the caller's explicit choice: its ancestors aren't checked (system paths
    such as /tmp may be links), but DIR itself and NAME must not be links.
    """
    if dir.is_absolute():
        base, parts = dir, [name]
        if dir.is_symlink():
            raise SkillError(f"{dir} is a symlink; not writing through it")
    else:
        base, parts = Path.cwd(), [*dir.parts, name]
        if ".." in dir.parts:
            raise SkillError(f"{dir}: '..' is not allowed in a relative --dir (give an absolute path)")
    current = base
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise SkillError(f"{current} is a symlink; not writing through it")
    return base.resolve()


# --- CLI ---------------------------------------------------------------------------------------------

def add_parser(sub) -> None:
    p = sub.add_parser("skills", help="write or check Agent Skills (SKILL.md) folders (DEC-256 item 5)")
    s = p.add_subparsers(dest="skills_cmd", required=True)
    n = s.add_parser("new", help="write DIR/NAME/SKILL.md from a template; never overwrites")
    n.add_argument("name")
    n.add_argument("--description", required=True, help="what the skill does and when to use it")
    n.add_argument("--dir", default="skills", help="parent folder (default: skills)")
    n.add_argument("--license")
    n.add_argument("--compatibility")
    c = s.add_parser("check", help="exit 0 when every skill folder under PATH is valid, else 1")
    c.add_argument("paths", nargs="+", metavar="PATH", help="a skill folder, or a folder of skill folders")


def cli(a, ap) -> int:
    if a.skills_cmd == "new":
        try:
            target = new_skill(a.dir, a.name, a.description, license=a.license, compatibility=a.compatibility)
        except SkillError as exc:  # invalid values, or a symlinked or escaping destination
            print(f"skills new: {exc}", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"skills new: {exc if isinstance(exc, FileExistsError) else type(exc).__name__}",
                  file=sys.stderr)
            return 1
        print(f"skills new: wrote {target}")
        return 0
    bad = 0
    for path in a.paths:
        dirs = find_skill_dirs(path)
        if not dirs:
            print(f"skills check: {path}: no {SKILL_FILE} here or in its subfolders", file=sys.stderr)
            bad += 1
            continue
        for d in dirs:
            problems = check_skill_dir(d)
            for p in problems:
                print(f"skills check: {d}: {p}", file=sys.stderr)
            if problems:
                bad += 1
            else:
                print(f"skills check: {d} is a valid skill")
    return 1 if bad else 0
