"""aec config, slice 2: `records` in .aec/config.json is read by the commands whose records path is optional.

AEC-R-repo-config-precedence@2: an explicit path wins and keeps its meaning; then the file; then the default.
A required positional RECORDS (`aec check`, `impact`, `code-impact`, `append`) is unchanged and never becomes
optional. Commands covered: `source show|search`, `import-purpose`, `mcp`, `speckit derive|drift`.
"""
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
from aec.__main__ import build_parser, main  # noqa: E402
from aec.mcp import telosmith_server  # noqa: E402


def rec(rid, text):
    return json.dumps({"id": rid, "version": 1, "type": "requirement", "epistemic": "provisional", "text": text})


def run(argv, cwd=None):
    out, err = io.StringIO(), io.StringIO()
    old = os.getcwd()
    try:
        if cwd:
            os.chdir(cwd)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main(argv)
            except SystemExit as stop:
                code = stop.code
    finally:
        os.chdir(old)
    return code, out.getvalue(), err.getvalue()


class Repo:
    """ROOT/.git, ROOT/.aec/records.jsonl (holds R-DEFAULT) and ROOT/records/main.jsonl (holds R-CONFIG)."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "repo"
        (self.root / ".aec").mkdir(parents=True)
        (self.root / ".git").mkdir()
        (self.root / ".aec" / "records.jsonl").write_text(rec("R-DEFAULT", "default file") + "\n", encoding="utf-8")
        (self.root / "records").mkdir()
        (self.root / "records" / "main.jsonl").write_text(rec("R-CONFIG", "configured file") + "\n", encoding="utf-8")
        self.other = Path(self._tmp.name).resolve() / "other.jsonl"
        self.other.write_text(rec("R-EXPLICIT", "explicit file") + "\n", encoding="utf-8")
        return self

    def configure(self, doc):
        text = doc if isinstance(doc, str) else json.dumps(doc)
        (self.root / config.CONFIG_PATH).write_text(text, encoding="utf-8")

    def __exit__(self, *exc):
        self._tmp.cleanup()


class RecordsPath(unittest.TestCase):
    def test_absent_file_keeps_the_old_default_exactly(self):
        with Repo() as r:
            self.assertEqual(config.records_path(None, r.root), r.root / ".aec" / "records.jsonl")
            self.assertEqual(config.records_path(None, "rel"), Path("rel") / ".aec" / "records.jsonl")

    def test_file_without_records_key_keeps_the_default(self):
        with Repo() as r:
            r.configure({"version": 1, "init": {"ci_name": "x"}})
            self.assertEqual(config.records_path(None, r.root), r.root / ".aec" / "records.jsonl")

    def test_configured_records_resolve_against_root_not_cwd(self):
        with Repo() as r:
            r.configure({"records": "records/main.jsonl"})
            old = os.getcwd()
            try:
                os.chdir(r.root / "records")
                self.assertEqual(config.records_path(None, r.root), r.root / "records" / "main.jsonl")
            finally:
                os.chdir(old)

    def test_explicit_wins_even_when_equal_to_the_default_and_skips_the_config(self):
        with Repo() as r:
            r.configure({"records": "records/main.jsonl"})
            self.assertEqual(config.records_path(".aec/records.jsonl", r.root), Path(".aec/records.jsonl"))
            r.configure("{not json")  # never read when the path is explicit
            self.assertEqual(config.records_path(str(r.other), r.root), r.other)

    def test_invalid_config_is_an_error_when_it_would_be_used(self):
        with Repo() as r:
            r.configure({"records": "../outside.jsonl"})
            with self.assertRaises(config.ConfigError):
                config.records_path(None, r.root)

    def test_only_roots_own_config_counts(self):
        with Repo() as r:
            r.configure({"records": "records/main.jsonl"})
            child = r.root / "child"
            (child / ".aec").mkdir(parents=True)
            self.assertEqual(config.records_path(None, child), child / ".aec" / "records.jsonl")
            bare = r.root / "bare"  # no .aec/ of its own: the parent's file is not read either
            bare.mkdir()
            self.assertEqual(config.records_path(None, bare), bare / ".aec" / "records.jsonl")


class Commands(unittest.TestCase):
    def test_source_show_reads_the_configured_records(self):
        with Repo() as r:
            r.configure({"records": "records/main.jsonl"})
            code, out, err = run(["source", "show", "R-CONFIG@1", "--repo", str(r.root)])
            self.assertEqual(code, 0, err)
            self.assertIn("R-CONFIG@1", out)
            code, _, err = run(["source", "show", "R-DEFAULT@1", "--repo", str(r.root)])
            self.assertNotEqual(code, 0)
            self.assertIn("not found", err)

    def test_source_show_explicit_records_win(self):
        with Repo() as r:
            r.configure({"records": "records/main.jsonl"})
            code, out, err = run(["source", "show", "R-EXPLICIT@1", "--repo", str(r.root), "--records", str(r.other)])
            self.assertEqual(code, 0, err)
            # explicit relative path keeps its meaning: relative to the working directory, not ROOT
            code, out, err = run(["source", "show", "R-DEFAULT@1", "--repo", str(r.root),
                                  "--records", ".aec/records.jsonl"], cwd=r.root)
            self.assertEqual(code, 0, err)

    def test_source_show_without_config_is_unchanged(self):
        with Repo() as r:
            code, out, err = run(["source", "show", "R-DEFAULT@1", "--repo", str(r.root)])
            self.assertEqual(code, 0, err)

    def test_source_reports_an_invalid_config(self):
        with Repo() as r:
            r.configure({"records": "records/main.jsonl", "colour": "red"})
            code, _, err = run(["source", "show", "R-CONFIG@1", "--repo", str(r.root)])
            self.assertEqual(code, 2)
            self.assertIn("config.json", err)
            self.assertIn("colour", err)

    def test_mcp_server_reads_the_configured_records(self):
        with Repo() as r:
            r.configure({"records": "records/main.jsonl"})
            self.assertEqual(_ids(telosmith_server(r.root)), ["R-CONFIG"])
            self.assertEqual(_ids(telosmith_server(r.root, str(r.other))), ["R-EXPLICIT"])
            r.configure({"records": 7})
            with self.assertRaises(config.ConfigError):
                telosmith_server(r.root)
            code, _, err = run(["mcp", "--root", str(r.root)])
            self.assertEqual(code, 1)
            self.assertIn("records: must be a non-empty string path", err)

    def test_import_purpose_appends_to_the_configured_records(self):
        with Repo() as r:
            r.configure({"records": "records/main.jsonl"})
            pdir = r.root / "codex_++" / "purpose_files"
            pdir.mkdir(parents=True)
            (pdir / "demo.purpose.md").write_text("# demo\n\n## Purpose\n\nDo one thing well.\n", encoding="utf-8")
            before_default = (r.root / ".aec" / "records.jsonl").read_text(encoding="utf-8")
            code, out, err = run(["import-purpose", str(r.root)])
            self.assertEqual(code, 0, err)
            self.assertEqual((r.root / ".aec" / "records.jsonl").read_text(encoding="utf-8"), before_default)
            ids = [json.loads(x)["id"] for x in (r.root / "records" / "main.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(ids, ["R-CONFIG", "PF-demo", "PC-demo"])

    def test_required_positional_records_stay_required(self):
        ap = build_parser()
        for cmd in ("check", "impact", "code-impact", "append"):
            with self.subTest(cmd=cmd), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):  # no RECORDS given: still a usage error, config or not
                    ap.parse_args([cmd])


class Speckit(unittest.TestCase):
    SPEC = "# Feature Specification: demo\n\n## Requirements\n\n- **FR-001**: Something (R-CONFIG@1).\n"

    def feature(self, r):
        f = r.root / "specs" / "001-demo"
        f.mkdir(parents=True)
        (f / "spec.md").write_text(self.SPEC, encoding="utf-8")
        return f

    def test_drift_uses_the_configured_records(self):
        with Repo() as r:
            f = self.feature(r)
            _, out, _ = run(["speckit", "drift", str(f)])
            self.assertIn("unresolved-citation", out)  # the default file has no R-CONFIG@1
            r.configure({"records": "records/main.jsonl"})
            _, out, _ = run(["speckit", "drift", str(f)])
            self.assertTrue(out.startswith("0 finding(s)"), out)

    def test_drift_reports_an_invalid_config(self):
        with Repo() as r:
            f = self.feature(r)
            r.configure("[1, 2]")
            code, out, _ = run(["speckit", "drift", str(f)])
            self.assertEqual(code, 2)
            self.assertIn("config.json", out)

    def test_drift_explicit_records_skip_the_config(self):
        with Repo() as r:
            f = self.feature(r)
            r.configure("{broken")
            code, out, _ = run(["speckit", "drift", str(f), "--records", str(r.root / "records" / "main.jsonl")])
            self.assertEqual(code, 0, out)
            self.assertTrue(out.startswith("0 finding(s)"), out)



class KateRecordsRound5(unittest.TestCase):
    """The tests AEC-R-repo-config-records@1 (API Kate, round 5) asks for that the slice-2 tests didn't cover."""

    def parent_with_config(self, r):
        """A parent directory above ROOT with its own .aec/config.json pointing at a file holding R-PARENT."""
        parent = r.root.parent
        (parent / ".aec").mkdir(exist_ok=True)
        (parent / "p.jsonl").write_text(rec("R-PARENT", "parent file") + "\n", encoding="utf-8")
        (parent / ".aec" / "config.json").write_text(json.dumps({"records": "p.jsonl"}), encoding="utf-8")
        return parent

    def test_root_taking_consumers_ignore_a_parent_config_from_any_cwd(self):
        with Repo() as r:
            parent = self.parent_with_config(r)
            for cwd in (parent, r.root / "records"):
                with self.subTest(cwd=str(cwd)):
                    # ROOT has no config: the default file, never the parent's configured one
                    self.assertEqual(run(["source", "show", "R-DEFAULT@1", "--repo", str(r.root)], cwd=cwd)[0], 0)
                    self.assertNotEqual(run(["source", "show", "R-PARENT@1", "--repo", str(r.root)], cwd=cwd)[0], 0)
                    self.assertEqual(_ids(telosmith_server(r.root)), ["R-DEFAULT"])
            r.configure({"records": "records/main.jsonl"})  # conflicting configs: ROOT's own wins, from the parent's cwd
            code, out, err = run(["source", "show", "R-CONFIG@1", "--repo", str(r.root)], cwd=parent)
            self.assertEqual(code, 0, err)
            self.assertEqual(_ids(telosmith_server(r.root)), ["R-CONFIG"])

    def test_source_search_follows_the_same_order(self):
        # search reports source-root hits; the records file only feeds each hit's digest check, so watch which
        # file it loads
        from unittest import mock

        from aec.records import Store
        loaded = []
        real = Store.load.__func__

        def spy(cls, path, *args, **kw):
            loaded.append(Path(path))
            return real(cls, path, *args, **kw)

        with Repo() as r, mock.patch.object(Store, "load", classmethod(spy)):
            argv = ["source", "search", "file", "--root", ".", "--repo", str(r.root)]
            self.assertEqual(run(argv)[0], 0)
            r.configure({"records": "records/main.jsonl"})
            self.assertEqual(run(argv, cwd=r.root.parent)[0], 0)
            self.assertEqual(run(argv + ["--records", str(r.other)])[0], 0)
            self.assertEqual(loaded, [r.root / ".aec" / "records.jsonl", r.root / "records" / "main.jsonl", r.other])
            r.configure("{broken")  # bypassed by an explicit path, an error otherwise
            self.assertEqual(run(argv + ["--records", str(r.other)])[0], 0)
            self.assertNotEqual(run(argv)[0], 0)

    def test_import_purpose_ignores_a_parent_config(self):
        with Repo() as r:
            parent = self.parent_with_config(r)
            pdir = r.root / "codex_++" / "purpose_files"
            pdir.mkdir(parents=True)
            (pdir / "demo.purpose.md").write_text("# demo\n\n## Purpose\n\nDo one thing well.\n", encoding="utf-8")
            before_parent = (parent / "p.jsonl").read_text(encoding="utf-8")
            code, _, err = run(["import-purpose", str(r.root)], cwd=parent)
            self.assertEqual(code, 0, err)
            self.assertEqual((parent / "p.jsonl").read_text(encoding="utf-8"), before_parent)
            self.assertIn("PF-demo", (r.root / ".aec" / "records.jsonl").read_text(encoding="utf-8"))

    def test_positional_records_commands_ignore_even_an_invalid_config(self):
        with Repo() as r:
            r.configure({"records": 7, "colour": "red"})
            code, out, err = run(["check", str(r.root / ".aec" / "records.jsonl")], cwd=r.root)
            self.assertEqual(code, 0, out + err)
            self.assertNotIn("config", out + err)

    def test_editor_hook_checks_the_default_records_whatever_the_config_says(self):
        from unittest import mock

        from aec import userhook
        with Repo() as r:
            r.configure({"records": 7, "colour": "red"})
            calls = []
            with mock.patch.object(userhook, "_produce", return_value=0), \
                    mock.patch.object(userhook, "_call", side_effect=lambda argv: calls.append(argv) or (0, "")):
                self.assertEqual(userhook.body(str(r.root)), 0)
            self.assertEqual(calls[0][:2], ["check", str(r.root / ".aec" / "records.jsonl")])


class SpeckitDiscovery(unittest.TestCase):
    """Kate's round-5 blocker: what stops discovery, what a config without `records` does, which root anchors."""

    def test_derive_follows_explicit_then_config_then_nearest_file(self):
        with Repo() as r:
            f = Speckit().feature(r)
            code, out, _ = run(["speckit", "derive", str(f), "--check"])
            self.assertEqual(code, 0, out)
            r.configure({"records": "records/main.jsonl"})
            self.assertEqual(run(["speckit", "derive", str(f), "--check"])[0], 0)
            r.configure("{broken")
            self.assertEqual(run(["speckit", "derive", str(f), "--check"])[0], 2)
            code, out, _ = run(["speckit", "derive", str(f), "--check", "--records", str(r.other)])
            self.assertEqual(code, 0, out)

    def test_nearest_aec_without_records_falls_back_without_reading_an_outer_config(self):
        with Repo() as r:
            r.configure({"records": "records/main.jsonl"})  # outer config names R-CONFIG's file
            inner = r.root / "pkg"
            (inner / ".aec").mkdir(parents=True)
            (inner / ".aec" / "config.json").write_text(json.dumps({"version": 1}), encoding="utf-8")
            f = inner / "specs" / "001-demo"
            f.mkdir(parents=True)
            (f / "spec.md").write_text(Speckit.SPEC, encoding="utf-8")
            # discovery stops at pkg/.aec; it sets no records, so the nearest records file above the feature is used:
            # ROOT/.aec/records.jsonl (no R-CONFIG@1), not the outer config's records/main.jsonl
            _, out, _ = run(["speckit", "drift", str(f)])
            self.assertIn("unresolved-citation", out)
            (inner / ".aec" / "config.json").write_text(json.dumps({"records": "r.jsonl"}), encoding="utf-8")
            (inner / "r.jsonl").write_text(rec("R-CONFIG", "inner file") + "\n", encoding="utf-8")
            _, out, _ = run(["speckit", "drift", str(f)], cwd=r.root.parent)  # resolved against pkg/, not cwd
            self.assertTrue(out.startswith("0 finding(s)"), out)

    def test_an_outer_config_is_not_read_across_the_git_top(self):
        with Repo() as r:
            r.configure({"records": "records/main.jsonl"})
            sub = r.root / "vendored"
            (sub / ".git").mkdir(parents=True)
            (sub / ".aec").mkdir()
            (sub / ".aec" / "records.jsonl").write_text(rec("R-SUB", "sub") + "\n", encoding="utf-8")
            self.assertIsNone(config.discovered_records(sub))
            nested = r.root / "plain" / "deep"
            nested.mkdir(parents=True)
            (r.root / "plain" / ".git").mkdir()  # a git top with no .aec/ between it and the feature
            self.assertIsNone(config.discovered_records(nested))

def _ids(srv):
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "records_list", "arguments": {}}}
    res = srv.handle(req)["result"]
    return [i["ref"].split("@")[0] for i in res["structuredContent"]["items"]]


if __name__ == "__main__":
    unittest.main()
