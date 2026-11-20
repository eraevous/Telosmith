"""aec config: the per-repository .aec/config.json (AEC-D-repo-config@2, DEC-256 item 1)."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aec import config  # noqa: E402
from aec.__main__ import main  # noqa: E402


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


class Repo:
    """A temporary git-like repository: ROOT/.git and ROOT/.aec/."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "repo"
        (self.root / ".aec").mkdir(parents=True)
        (self.root / ".git").mkdir()
        return self

    def write(self, doc):
        text = doc if isinstance(doc, str) else json.dumps(doc)
        (self.root / config.CONFIG_PATH).write_text(text, encoding="utf-8")

    def __exit__(self, *exc):
        self._tmp.cleanup()


class Discovery(unittest.TestCase):
    def test_absent_file_means_defaults(self):
        with Repo() as r:
            cfg = config.load(r.root)
            self.assertEqual(cfg.root, r.root)
            self.assertIsNone(cfg.path)
            for key, default in config.DEFAULTS.items():
                self.assertEqual(cfg.get(key), default)
                self.assertEqual(cfg.source(key), "default")

    def test_subdirectory_finds_the_same_root(self):
        with Repo() as r:
            r.write({"records": "records/main.jsonl"})
            sub = r.root / "src" / "pkg"
            sub.mkdir(parents=True)
            cfg = config.load(sub)
            self.assertEqual(cfg.root, r.root)
            # relative paths resolve against the root, not the start directory
            self.assertEqual(cfg.path_of("records"), r.root / "records" / "main.jsonl")

    def test_never_walks_past_the_git_top(self):
        with Repo() as r:
            inner = r.root / "vendored"
            inner.mkdir()
            (inner / ".git").mkdir()
            r.write({"records": "x.jsonl"})
            cfg = config.load(inner)
            self.assertIsNone(cfg.root)
            self.assertEqual(cfg.get("records"), config.DEFAULTS["records"])


class Validation(unittest.TestCase):
    def bad(self, doc, *fragments):
        with Repo() as r:
            r.write(doc)
            with self.assertRaises(config.ConfigError) as caught:
                config.load(r.root)
            message = str(caught.exception)
            self.assertIn(str(r.root / config.CONFIG_PATH), message)
            for fragment in fragments:
                self.assertIn(fragment, message)
            return message

    def test_valid_file(self):
        with Repo() as r:
            r.write({"_doc": "why", "version": 1, "records": "r.jsonl",
                     "init": {"ci_name": "telosmith", "hook_style": "line"}})
            cfg = config.load(r.root)
            self.assertEqual(cfg.get("init.hook_style"), "line")
            self.assertEqual(cfg.source("init.ci_name"), "config")
            self.assertEqual(cfg.source("records"), "config")

    def test_unknown_keys_top_and_nested_all_named(self):
        message = self.bad({"recrods": "x", "init": {"hook_styel": "line"}}, "'recrods'", "'init.hook_styel'")
        self.assertIn("newer Telosmith", message)

    def test_wrong_types_and_values(self):
        self.bad({"version": 2}, "version")
        self.bad({"version": True}, "version")
        self.bad({"init": []}, "init: must be an object")
        self.bad({"init": {"hook_style": "both"}}, "init.hook_style")
        self.bad({"init": {"hook_style": []}}, "init.hook_style")   # unhashable: no TypeError (Codex, #97)
        self.bad({"init": {"hook_style": {}}, "x": 1}, "init.hook_style", "'x'")
        self.bad({"init": {"ci_name": "a b"}}, "init.ci_name")
        self.bad({"init": {"ci_name": "aec.check"}}, "init.ci_name")  # init itself refuses a dot (Codex, #97)
        self.bad({"_doc": 3}, "_doc")

    def test_paths_stay_relative_and_inside(self):
        self.bad({"records": "/etc/r.jsonl"}, "relative")
        self.bad({"records": "../r.jsonl"}, "inside the repository")
        self.bad({"records": "a\\b.jsonl"}, "relative")
        self.bad({"records": ""}, "non-empty")

    def test_malformed_json_root_and_duplicates(self):
        self.bad("{not json", "not valid JSON", "line 1")
        self.bad("[1, 2]", "JSON object")
        self.bad('{"records": "a.jsonl", "records": "b.jsonl"}', "repeated key 'records'")

    def test_every_problem_reported_at_once(self):
        self.bad({"x": 1, "version": 9, "init": {"hook_style": "no"}}, "'x'", "version: this Telosmith",
                 "init.hook_style: 'inline'")


class Precedence(unittest.TestCase):
    def test_flag_then_config_then_default(self):
        with Repo() as r:
            r.write({"init": {"hook_style": "line"}})
            cfg = config.load(r.root)
            self.assertEqual(config.resolve("inline", cfg, "init.hook_style"), "inline")
            self.assertEqual(config.resolve(None, cfg, "init.hook_style"), "line")
            self.assertEqual(config.resolve(None, cfg, "init.ci_name"), "aec")

    def test_init_reads_the_config_and_flags_win(self):
        with Repo() as r:
            r.write({"init": {"ci_name": "gov", "hook_style": "line"}})
            (r.root / "m.py").write_text("x = 1\n")
            before = (r.root / config.CONFIG_PATH).read_bytes()
            code, out, _ = run(["init", str(r.root), "--owner", "o", "--ci-name", "flagged"])
            self.assertEqual(code, 0)
            self.assertIn("flagged", out)              # the flag beat init.ci_name
            self.assertNotIn("gov", out)
            settings = (r.root / ".aec" / "snippets" / "claude-settings.json")
            self.assertTrue(settings.exists())
            self.assertIn("hook project", settings.read_text())  # init.hook_style "line" from the file
            self.assertEqual((r.root / config.CONFIG_PATH).read_bytes(), before)  # never rewritten

    def test_every_value_the_config_accepts_init_accepts(self):
        for name in ("aec", "a-b_c", "X9"):
            for style in ("inline", "line"):
                with self.subTest(name=name, style=style), Repo() as r:
                    r.write({"init": {"ci_name": name, "hook_style": style}})
                    (r.root / "m.py").write_text("x = 1\n")
                    code, _, err = run(["init", str(r.root), "--owner", "o"])
                    self.assertEqual(code, 0, err)

    def test_init_without_config_is_unchanged(self):
        with Repo() as r:
            (r.root / "m.py").write_text("x = 1\n")
            code, out, _ = run(["init", str(r.root), "--owner", "o"])
            self.assertEqual(code, 0)
            self.assertNotIn("hook project", (r.root / ".aec" / "snippets" / "claude-settings.json").read_text())

    def test_invalid_config_stops_init_before_writing(self):
        with Repo() as r:
            r.write({"init": {"hook_style": "both"}})
            code, _, err = run(["init", str(r.root), "--owner", "o"])
            self.assertEqual(code, 2)
            self.assertIn("init.hook_style", err)
            self.assertEqual(sorted(p.name for p in (r.root / ".aec").iterdir()), ["config.json"])


class Cli(unittest.TestCase):
    def test_show_and_check(self):
        with Repo() as r:
            code, out, _ = run(["config", "check", "--repo", str(r.root)])
            self.assertEqual((code, out.strip()), (0, "config: ok (none (defaults))"))
            r.write({"records": "r.jsonl"})
            code, out, _ = run(["config", "show", "--repo", str(r.root), "--json"])
            shown = json.loads(out)
            self.assertEqual(shown["settings"]["records"], {"value": "r.jsonl", "from": "config"})
            self.assertEqual(shown["settings"]["init.ci_name"], {"value": "aec", "from": "default"})
            code, out, _ = run(["config", "show", "--repo", str(r.root)])
            self.assertIn('records = "r.jsonl"  (config)', out)
            r.write({"bogus": 1})
            code, _, err = run(["config", "check", "--repo", str(r.root)])
            self.assertEqual(code, 1)
            self.assertIn("'bogus'", err)

    def test_reading_writes_nothing(self):
        with Repo() as r:
            r.write({"records": "r.jsonl"})
            before = sorted(os.listdir(r.root / ".aec"))
            run(["config", "show", "--repo", str(r.root)])
            self.assertEqual(sorted(os.listdir(r.root / ".aec")), before)


if __name__ == "__main__":
    unittest.main()
