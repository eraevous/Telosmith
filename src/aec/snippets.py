"""`aec snippets`: render the hook and CI snippets from the repository's config (DEC-256 item 3).

`aec init` used to be the only way to get the Claude Code hook and the CI job, and it wrote them as files under
`.aec/snippets/`, which repositories then committed. Committed copies go stale: the survey behind DEC-256 found 11
repositories carrying them in 4 to 6 variants. This module renders the same text on demand from what the repository
already states, so nothing needs committing:

  hook  `init.hook_style` in ROOT's own `.aec/config.json` (default `inline`): the settings JSON `aec init` writes.
  ci    `init.ci_name` (default `aec`) and a full commit: `--ref`, else the repository's pin
        (`tools/aec_upstream.json`, the one pin source, AEC-D-pin-check-scope@1). Never the network: with neither,
        `show ci` fails and says what to supply.

`check` compares each committed copy under `.aec/snippets/` with a fresh render and exits 1 when one differs, so a
follow-up PR can show its copies were current before removing them, and CI can catch drift while copies remain.
Only ROOT's own config counts (`config.own`), as for `aec init`. Reads only; writes nothing. Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from .init import CI_NAME, HOOK_STYLES, ci_snippet

SNIPPETS_DIR = Path(".aec") / "snippets"
HOOK_FILE = "claude-settings.json"
_SHA = re.compile(r"[0-9a-f]{40}")


class SnippetError(ValueError):
    """A snippet can't be rendered or checked; the message says what to supply."""


def settings(root: str | Path, ref: str | None = None, hook_style: str | None = None, ci_name: str | None = None):
    """(hook_style, ci_name, ref or None): explicit values first, then ROOT's own config and pin, as `aec init`
    resolves them (an explicit flag wins over the config). Raises SnippetError."""
    from .config import ConfigError, own
    root = Path(root)
    try:
        cfg = own(root)
    except ConfigError as error:
        raise SnippetError(str(error)) from None
    style = hook_style if hook_style is not None else cfg.get("init.hook_style")
    name = ci_name if ci_name is not None else cfg.get("init.ci_name")
    if style not in HOOK_STYLES:
        raise SnippetError(f"--hook-style {style!r}: one of {', '.join(HOOK_STYLES)}")
    if not isinstance(name, str) or not CI_NAME.fullmatch(name):
        raise SnippetError(f"--ci-name {name!r}: letters, digits, '_' or '-' (what aec init accepts)")
    if ref is not None:
        if not _SHA.fullmatch(ref):
            raise SnippetError(f"--ref {ref!r}: a full 40-character commit SHA (what aec init pins)")
        return style, name, ref
    from .pin import UPSTREAM_FILE, PinError, read_pin
    if os.path.islink(root / UPSTREAM_FILE.parent):
        return style, name, None   # a symlinked tools/ is never read through
    try:
        return style, name, read_pin(root)
    except PinError:
        return style, name, None


def render(root: str | Path, which: str, ref: str | None = None, hook_style: str | None = None,
           ci_name: str | None = None) -> str:
    """The text `aec init` would write for WHICH (`hook` or `ci`) in ROOT, from explicit values or ROOT's config."""
    style, name, ref = settings(root, ref, hook_style, ci_name)
    if which == "hook":
        return json.dumps(HOOK_STYLES[style], indent=2) + "\n"
    if which == "ci":
        if ref is None:
            raise SnippetError("no commit to pin: pass --ref <full commit SHA>, or commit tools/aec_upstream.json "
                               "with one (aec init --hook-style line writes it)")
        return ci_snippet(ref, name)
    raise SnippetError(f"unknown snippet {which!r}: hook or ci")


def check(root: str | Path, ref: str | None = None, hook_style: str | None = None,
          ci_name: str | None = None) -> tuple[list[str], list[str]]:
    """(ok lines, problem lines) for each committed copy under ROOT/.aec/snippets/. No copies: ([], [])."""
    root = Path(root)
    folder = root / SNIPPETS_DIR
    if os.path.islink(root / ".aec") or os.path.islink(folder):
        return [], [f"{SNIPPETS_DIR.as_posix()}: a symlink; not read"]
    if not folder.is_dir():
        return [], []
    style, name, ref = settings(root, ref, hook_style, ci_name)
    ok, bad = [], []
    for path in sorted(folder.iterdir()):
        rel = (SNIPPETS_DIR / path.name).as_posix()
        if path.name == HOOK_FILE:
            which = "hook"
        elif path.name.endswith("-ci.yml") and CI_NAME.fullmatch(path.name[:-len("-ci.yml")]):
            which = "ci"
            if path.name != f"{name}-ci.yml":
                bad.append(f"{rel}: the CI name is {name!r} (init.ci_name or --ci-name), so aec init would write "
                           f"{name}-ci.yml, not this file")
                continue
        else:
            ok.append(f"{rel}: not a Telosmith snippet; not checked")
            continue
        if path.is_symlink() or not path.is_file():
            bad.append(f"{rel}: not a regular file; not read")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            bad.append(f"{rel}: can't read it ({error})")
            continue
        if which == "ci" and ref is None:
            bad.append(f"{rel}: can't check it, no commit to compare with (pass --ref or commit "
                       "tools/aec_upstream.json)")
            continue
        fresh = render(root, which, ref, style, name)
        same = (_json(text) == _json(fresh)) if which == "hook" else text == fresh
        if same:
            ok.append(f"{rel}: current (matches `aec snippets show {which}`)")
        else:
            why = f"hook style {style!r}" if which == "hook" else f"CI name {name!r}, commit {ref[:12]}"
            bad.append(f"{rel}: stale, differs from `aec snippets show {which}` ({why})")
    return ok, bad


def _json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text   # not JSON: compared as text, so it can only match an identical text


def add_parser(sub) -> None:
    p = sub.add_parser("snippets", help="render the hook and CI snippets from .aec/config.json, or check committed "
                                        "copies (DEC-256 item 3)")
    s = p.add_subparsers(dest="snippets_cmd", required=True)
    show = s.add_parser("show", help="print the snippet aec init would write: hook (settings JSON) or ci (workflow)")
    show.add_argument("which", choices=("hook", "ci"))
    for q in (show, s.add_parser("check", help="exit 1 when a committed copy under .aec/snippets/ differs from a "
                                               "fresh render")):
        q.add_argument("--repo", default=".", help="the repository root; only its own .aec/config.json counts")
        q.add_argument("--ref", help="full commit SHA for the CI job (default: commit in tools/aec_upstream.json)")
        q.add_argument("--hook-style", choices=tuple(HOOK_STYLES), default=None,
                       help="as aec init --hook-style; wins over init.hook_style in the config")
        q.add_argument("--ci-name", default=None, help="as aec init --ci-name; wins over init.ci_name in the config")


def cli(a, ap) -> int:
    try:
        if a.snippets_cmd == "show":
            print(render(a.repo, a.which, a.ref, a.hook_style, a.ci_name), end="")
            return 0
        ok, bad = check(a.repo, a.ref, a.hook_style, a.ci_name)
    except SnippetError as error:
        print(f"snippets: {error}", file=sys.stderr)
        return 1
    for line in ok + bad:
        print(line)
    if not ok and not bad:
        print(f"no committed snippets under {SNIPPETS_DIR.as_posix()}: nothing to check "
              "(aec snippets show renders them on demand)")
    return 1 if bad else 0
