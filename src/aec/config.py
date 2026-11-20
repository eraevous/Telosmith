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
  records            path     the records file (default `.aec/records.jsonl`)
  init.ci_name       name     `aec init --ci-name` (default `aec`)
  init.hook_style    choice   `aec init --hook-style`: `inline` or `line` (default `inline`)

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
}
_SECTIONS = {"init"}
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
        return self.values.get(key, DEFAULTS[key])

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


def _no_duplicates(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ConfigError(f"repeated key {k!r}")
        out[k] = v
    return out


def _check_path(key: str, value, problems: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{key}: must be a non-empty string path")
        return
    p = PurePosixPath(value)
    if "\\" in value or p.is_absolute() or re.match(r"^[A-Za-z]:", value):
        problems.append(f"{key}: must be a relative path with '/' separators, got {value!r}")
    elif ".." in p.parts:
        problems.append(f"{key}: must stay inside the repository root (no '..'), got {value!r}")


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
        _check_path("records", doc["records"], problems)
        values["records"] = doc["records"]
    init = doc.get("init")
    if init is not None:
        if not isinstance(init, dict):
            problems.append("init: must be an object")
        else:
            for key in sorted(set(init) - {"ci_name", "hook_style"}):
                problems.append(f"unknown key 'init.{key}' (known: init.ci_name, init.hook_style)")
            if "ci_name" in init:
                v = init["ci_name"]
                if not isinstance(v, str) or not CI_NAME.fullmatch(v):
                    problems.append(f"init.ci_name: letters, digits, '_' or '-' (what aec init accepts), got {v!r}")
                values["init.ci_name"] = v
            if "hook_style" in init:
                v = init["hook_style"]
                if v not in HOOK_STYLES:
                    problems.append(f"init.hook_style: 'inline' or 'line', got {v!r}")
                values["init.hook_style"] = v
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
        doc = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates)
    except ConfigError as error:
        raise ConfigError(f"{path}: {error}") from None
    except json.JSONDecodeError as error:
        raise ConfigError(f"{path}: not valid JSON (line {error.lineno}, column {error.colno}: {error.msg})") from None
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"{path}: can't read it ({error})") from None
    values, problems = validate(doc)
    if problems:
        raise ConfigError(f"{path}: " + "; ".join(problems))
    return Config(root, path, values)


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
