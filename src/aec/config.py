"""Per-repository configuration: `.aec/config.json` (AEC-D-repo-config@2, DEC-256 item 1).

A repository without the file behaves exactly as before: every setting has a default equal to today's behaviour.
With the file, the whole document is validated before any command uses it; unknown keys are errors, because a
setting that silently does nothing is worse than a refusal. Explicit command-line flags win over the file, and the
file wins over the defaults (`resolve`). Reading the file never writes anything. Standard library only.

Discovery: from the start directory, walk up to the nearest directory that holds an `.aec/` folder, never past the
top of the git work tree (the first directory with a `.git` entry). That directory is the repository root; the file
is `<root>/.aec/config.json`, and every relative path in it is resolved against the root, never against the
directory the command ran in.

Schema version 1 (every key optional):

  _doc               string   free prose, ignored (JSON has no comments)
  version            1        the schema version; any other value is an error
  records            path     the records file (default `.aec/records.jsonl`), for the commands whose
                              records path is optional (`records_path`, `discovered_records`)
  init.ci_name       name     `aec init --ci-name` (default `aec`)
  init.hook_style    choice   `aec init --hook-style`: `inline` or `line` (default `inline`)
  init.snippet_files bool     `aec init` writes `.aec/snippets/` (default true); false: it doesn't, and its next
                              steps point to `aec snippets show hook|ci` instead (DEC-256 item 3)
  agents.owner       text     who accepts design intent, in the shared AGENTS.md block (default
                              `the repository owner`)
  agents.glossary    path|URL the glossary the shared block points to (DEC-255; default: none named)
  agents.read_first  paths    files to read first, in order, after the purpose records (default: none)
  agents.ledgers     paths    append-only files besides the records file (default: none)
  agents.hard_rules  texts    this repository's extra hard rules, one line each (default: none)

The `agents.*` texts are rendered into Markdown by `aec agents` (src/aec/agents.py), so each is one line, at most
300 characters, and holds no backtick or HTML comment marker (`<!--`, `-->`).

Paths are relative, use `/`, and stay inside the root. A list value, when a later version adds one, replaces the
default whole; nothing is merged. Further keys (which checks run, hook strictness, governance options) arrive with
the items that consume them; until then they are unknown keys.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .init import CI_NAME, HOOK_STYLES

CONFIG_PATH = ".aec/config.json"
SCHEMA_VERSION = 1

DEFAULTS: dict[str, object] = {
    "records": ".aec/records.jsonl",
    "init.ci_name": "aec",
    "init.hook_style": "inline",
    "init.snippet_files": True,
    "agents.owner": "the repository owner",
    "agents.glossary": None,
    "agents.read_first": [],
    "agents.ledgers": [],
    "agents.hard_rules": [],
}
_SECTIONS = {"init", "agents"}
_AGENT_KEYS = ("owner", "glossary", "read_first", "ledgers", "hard_rules")
_TEXT_MAX = 300
_TOP = {"_doc", "version", "records"} | _SECTIONS


class ConfigError(ValueError):
    """The config file exists but can't be used. The message names the file and every problem."""


@dataclass
class Config:
    root: Path | None                  # the repository root found by discovery (None: no `.aec/` above start)
    path: Path | None                  # the config file read (None: no file, defaults only)
    values: dict[str, object] = field(default_factory=dict)  # settings set in the file, dotted keys

    def get(self, key: str) -> object:
        if key not in DEFAULTS:
            raise KeyError(key)
        value = self.values.get(key, DEFAULTS[key])
        return list(value) if isinstance(value, list) else value  # a caller never mutates a default

    def source(self, key: str) -> str:
        return "config" if key in self.values else "default"

    def path_of(self, key: str) -> Path:
        """A path setting resolved against the repository root (or the start directory when there is none)."""
        base = self.root if self.root is not None else Path.cwd()
        return base / str(self.get(key))


def find_root(start: str | Path = ".") -> Path | None:
    here = Path(start).resolve()
    if here.is_file():
        here = here.parent
    for d in (here, *here.parents):
        if (d / ".aec").is_dir():
            return d
        if (d / ".git").exists():
            return None
    return None


def _collect_duplicates(found: list[str]):
    """An object_pairs_hook that records repeated keys (keeping the last value) so validation still runs."""
    def hook(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                found.append(f"repeated key {k!r}")
            out[k] = v
        return out
    return hook


def _check_path(key: str, value, problems: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{key}: must be a non-empty string path")
        return
    p = PurePosixPath(value)
    if "\\" in value or p.is_absolute() or re.match(r"^[A-Za-z]:", value):
        problems.append(f"{key}: must be a relative path with '/' separators, got {value!r}")
    elif ".." in p.parts:
        problems.append(f"{key}: must stay inside the repository root (no '..'), got {value!r}")


def _check_text(key: str, value, problems: list[str]) -> bool:
    """A one-line text that `aec agents` renders into Markdown (no backtick, no HTML comment marker)."""
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{key}: must be a non-empty string")
        return False
    if len(value) > _TEXT_MAX or any(c in value for c in "\r\n\x85\u2028\u2029") or not value.isprintable():
        problems.append(f"{key}: must be one printable line of at most {_TEXT_MAX} characters")
        return False
    if "`" in value or "<!--" in value or "-->" in value:
        problems.append(f"{key}: may not contain a backtick or an HTML comment marker, got {value!r}")
        return False
    return True


def _check_list(key: str, value, item, problems: list[str]) -> None:
    if not isinstance(value, list):
        problems.append(f"{key}: must be a list")
        return
    seen = set()
    for i, v in enumerate(value):
        item(f"{key}[{i}]", v, problems)
        if isinstance(v, str):
            if v in seen:
                problems.append(f"{key}[{i}]: repeated value {v!r}")
            seen.add(v)


def _check_agent_path(key: str, value, problems: list[str]) -> None:
    if _check_text(key, value, problems):
        _check_path(key, value, problems)


def _check_agents(agents, values: dict[str, object], problems: list[str]) -> None:
    if not isinstance(agents, dict):
        problems.append("agents: must be an object")
        return
    for key in sorted(set(agents) - set(_AGENT_KEYS)):
        problems.append(f"unknown key 'agents.{key}' (known: {', '.join('agents.' + k for k in _AGENT_KEYS)})")
    if "owner" in agents:
        _check_text("agents.owner", agents["owner"], problems)
    if "glossary" in agents:
        v = agents["glossary"]
        if _check_text("agents.glossary", v, problems) and not v.startswith("https://"):
            if "://" in v:
                problems.append(f"agents.glossary: a URL must start with https://, got {v!r}")
            else:
                _check_path("agents.glossary", v, problems)
    if "read_first" in agents:
        _check_list("agents.read_first", agents["read_first"], _check_agent_path, problems)
    if "ledgers" in agents:
        _check_list("agents.ledgers", agents["ledgers"], _check_agent_path, problems)
    if "hard_rules" in agents:
        _check_list("agents.hard_rules", agents["hard_rules"], _check_text, problems)
    for key in _AGENT_KEYS:
        if key in agents:
            values[f"agents.{key}"] = agents[key]


def validate(doc) -> tuple[dict[str, object], list[str]]:
    """Return (settings by dotted key, problems). Never raises."""
    if not isinstance(doc, dict):
        return {}, [f"the top level must be a JSON object, got {type(doc).__name__}"]
    problems: list[str] = []
    values: dict[str, object] = {}
    for key in sorted(set(doc) - _TOP):
        problems.append(f"unknown key {key!r} (known: {', '.join(sorted(_TOP))}); a newer Telosmith may define it")
    if "_doc" in doc and not isinstance(doc["_doc"], str):
        problems.append("_doc: must be a string")
    if "version" in doc and (type(doc["version"]) is not int or doc["version"] != SCHEMA_VERSION):
        problems.append(f"version: this Telosmith reads schema version {SCHEMA_VERSION}, got {doc['version']!r}")
    if "records" in doc:
        # `aec agents` renders the records path into Markdown, so it gets the same text rules as the agents.* texts
        # (Codex on #101: a path holding a newline and an end marker would forge the block's end).
        before = len(problems)
        _check_path("records", doc["records"], problems)
        if len(problems) == before:
            _check_text("records", doc["records"], problems)
        values["records"] = doc["records"]
    if "init" in doc:
        init = doc["init"]
        if not isinstance(init, dict):
            problems.append("init: must be an object")
        else:
            for key in sorted(set(init) - {"ci_name", "hook_style", "snippet_files"}):
                problems.append(f"unknown key 'init.{key}' (known: init.ci_name, init.hook_style, "
                                "init.snippet_files)")
            if "ci_name" in init:
                v = init["ci_name"]
                if not isinstance(v, str) or not CI_NAME.fullmatch(v):
                    problems.append(f"init.ci_name: letters, digits, '_' or '-' (what aec init accepts), got {v!r}")
                values["init.ci_name"] = v
            if "hook_style" in init:
                v = init["hook_style"]
                if not isinstance(v, str) or v not in HOOK_STYLES:
                    problems.append(f"init.hook_style: 'inline' or 'line', got {v!r}")
                values["init.hook_style"] = v
            if "snippet_files" in init:
                v = init["snippet_files"]
                if type(v) is not bool:
                    problems.append(f"init.snippet_files: true or false, got {v!r}")
                values["init.snippet_files"] = v
    if "agents" in doc:
        _check_agents(doc["agents"], values, problems)
    return (values if not problems else {}), problems


def load(start: str | Path = ".") -> Config:
    """Find and read the repository's config. Raises ConfigError (naming the file) when it exists but is invalid."""
    root = find_root(start)
    if root is None:
        return Config(None, None)
    path = root / CONFIG_PATH
    if not path.exists():
        return Config(root, None)
    try:
        duplicates: list[str] = []
        doc = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_collect_duplicates(duplicates))
    except json.JSONDecodeError as error:
        raise ConfigError(f"{path}: not valid JSON (line {error.lineno}, column {error.colno}: {error.msg})") from None
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"{path}: can't read it ({error})") from None
    values, problems = validate(doc)
    problems = duplicates + problems
    if problems:
        raise ConfigError(f"{path}: " + "; ".join(problems))
    return Config(root, path, values)


def own(root: str | Path) -> Config:
    """ROOT's own config, never a parent's: for `aec init` and the commands that take a ROOT or --repo."""
    root = Path(root)
    return load(root) if (root / ".aec").is_dir() else Config(None, None)


def configured_records(cfg: Config) -> Path:
    """`records` from CFG, resolved against its root, refusing symlinks (Codex security review on #98).

    The checkout controls the config and every path under the root. A committed symlink anywhere along the
    configured path (`records -> ../.bash_profile`) would make a reading command leave the repository and an appending
    one (`aec import-purpose`) write outside it, so no component below the root may be a symlink, and the resolved
    path must stay inside the resolved root. Raises ConfigError naming the file."""
    root = cfg.root if cfg.root is not None else Path.cwd()
    rel = PurePosixPath(str(cfg.get("records")))
    here = root
    for part in rel.parts:
        here = here / part
        if here.is_symlink():
            raise ConfigError(f"{cfg.path}: records: {rel} passes through a symlink ({here}); refused, "
                              "a records path must stay inside the repository")
    real_root = root.resolve()
    if not here.resolve().is_relative_to(real_root):
        raise ConfigError(f"{cfg.path}: records: {rel} resolves outside the repository root {real_root}; refused")
    return here


def records_path(explicit, root: str | Path) -> Path:
    """The records file for a command whose path is optional (AEC-R-repo-config-precedence@2).

    An explicit path wins and keeps its existing meaning (relative to the working directory); then `records` in
    ROOT's own config, resolved against ROOT; then the unchanged default `ROOT/.aec/records.jsonl`. With an explicit
    path the config isn't read at all. Raises ConfigError when ROOT's config exists and is invalid."""
    if explicit:
        return Path(explicit)
    cfg = own(root)
    if "records" in cfg.values:
        return configured_records(cfg)
    return Path(root) / ".aec" / "records.jsonl"


def discovered_records(start: str | Path) -> Path | None:
    """`records` from the config found by discovery from START, or None when no config sets it (the caller keeps
    its own default). For commands that already search upward (the speckit ones). Raises ConfigError."""
    cfg = load(start)
    return configured_records(cfg) if "records" in cfg.values else None


def resolve(cli_value, config: Config, key: str):
    """Explicit flag first, then the config file, then the default. `None` means the flag wasn't given."""
    return cli_value if cli_value is not None else config.get(key)


def add_parser(sub) -> None:
    p = sub.add_parser("config", help="show or check this repository's .aec/config.json (DEC-256 item 1)")
    c_sub = p.add_subparsers(dest="config_cmd", required=True)
    s = c_sub.add_parser("show", help="print every setting, its value and where it came from (config or default)")
    s.add_argument("--repo", default=".", help="start directory for discovery (default: .)")
    s.add_argument("--json", action="store_true")
    k = c_sub.add_parser("check", help="exit 0 when the config is valid or absent, else 1 with every problem")
    k.add_argument("--repo", default=".", help="start directory for discovery (default: .)")


def cli(a, ap) -> int:
    import sys
    try:
        cfg = load(a.repo)
    except ConfigError as error:
        print(f"config: {error}", file=sys.stderr)
        return 1
    where = str(cfg.path) if cfg.path else "none (defaults)"
    if a.config_cmd == "check":
        print(f"config: ok ({where})")
        return 0
    rows = {k: {"value": cfg.get(k), "from": cfg.source(k)} for k in DEFAULTS}
    if a.json:
        print(json.dumps({"root": str(cfg.root) if cfg.root else None, "file": str(cfg.path) if cfg.path else None,
                          "settings": rows}, indent=1, sort_keys=True))
    else:
        print(f"root: {cfg.root if cfg.root else 'none (no .aec/ found)'}\nfile: {where}")
        for k, row in rows.items():
            print(f"  {k} = {json.dumps(row['value'])}  ({row['from']})")
    return 0
