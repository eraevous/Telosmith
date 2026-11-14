"""Tests for the `aec edges` command line (snapshots are JSON Lines: a header row, then one row per edge), which no other test runs.

`aec edges` extracts a structural snapshot of a Python tree (to stdout or a file,
optionally with a legacy calls CSV) or diffs two stored snapshots. These tests pin
its exit codes, where its output goes, and how it reports bad input. They change
no behavior.
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from aec import edges as E  # noqa: E402
from aec.__main__ import main  # noqa: E402


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


class EdgesCli(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.tree = self.tmp / "tree"
        (self.tree / "pkg").mkdir(parents=True)
        (self.tree / "pkg" / "__init__.py").write_text("")
        (self.tree / "pkg" / "a.py").write_text(
            "def target():\n    return 1\n\n\ndef caller():\n    return target()\n")

    def snapshot_to(self, name):
        path = self.tmp / name
        code, _, _ = run("edges", str(self.tree), "-o", str(path))
        self.assertEqual(code, 0)
        return path

    def test_stdout_is_a_loadable_snapshot(self):
        code, out, err = run("edges", str(self.tree))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        snap = E.loads(out)
        self.assertEqual(E.dumps(snap), out)
        self.assertTrue(any(e["kind"] == "calls" and e["dst"].endswith("target") for e in snap["edges"]))

    def test_output_file_matches_stdout_and_reports_counts(self):
        _, stdout_text, _ = run("edges", str(self.tree))
        path = self.tmp / "nested" / "dir" / "edges.json"
        code, out, err = run("edges", str(self.tree), "-o", str(path))
        self.assertEqual(code, 0)
        self.assertEqual(out, "", "with -o the snapshot goes to the file, not stdout")
        self.assertEqual(path.read_text(encoding="utf-8"), stdout_text)
        snap = E.load(path)
        self.assertIn(f"aec edges: {len(snap['edges'])} edges from {snap['header']['files']} files", err)
        self.assertIn(f"-> {path}", err)

    def test_legacy_csv_lists_only_call_edges(self):
        csv_path = self.tmp / "calls.csv"
        code, out, _ = run("edges", str(self.tree), "--legacy-csv", str(csv_path))
        self.assertEqual(code, 0)
        snap = E.loads(out)
        self.assertEqual(csv_path.read_text(encoding="utf-8"), E.legacy_csv(snap))
        lines = csv_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "Source,Call")
        calls = [e for e in snap["edges"] if e["kind"] == "calls"]
        self.assertEqual(len(lines) - 1, len(calls))
        self.assertGreater(len(snap["edges"]), len(calls), "decoy: non-call edges exist and are left out")

    def test_missing_root_exits_2_with_message(self):
        missing = self.tmp / "nope"
        code, out, err = run("edges", str(missing))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn(f"aec edges: {missing} is not a directory", err)

    def test_file_as_root_exits_2(self):
        code, _, err = run("edges", str(self.tree / "pkg" / "a.py"))
        self.assertEqual(code, 2)
        self.assertIn("is not a directory", err)

    def test_source_changed_during_extraction_exits_2_without_output(self):
        path = self.tmp / "edges.json"
        with mock.patch.object(E, "snapshot", side_effect=E.SourceChanged("pkg/a.py changed during extraction")):
            code, out, err = run("edges", str(self.tree), "-o", str(path))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("aec edges: pkg/a.py changed during extraction", err)
        self.assertFalse(path.exists(), "a mixed-version snapshot is never written")

    def test_diff_identical_snapshots_reports_no_change(self):
        a = self.snapshot_to("a.json")
        code, out, _ = run("edges", "--diff", str(a), str(a))
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), ["# aec edges --diff (structural)", "no structural change"])

    def test_diff_reports_added_edge_and_definition(self):
        old = self.snapshot_to("old.json")
        (self.tree / "pkg" / "a.py").write_text(
            (self.tree / "pkg" / "a.py").read_text() + "\n\ndef added():\n    return target()\n")
        new = self.snapshot_to("new.json")
        code, out, _ = run("edges", "--diff", str(old), str(new))
        self.assertEqual(code, 0)
        self.assertTrue(any(line.startswith("+ calls:") and "added" in line for line in out.splitlines()))
        self.assertIn("defs_added:", out)
        code, out, _ = run("edges", "--diff", str(old), str(new), "--json")
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertTrue(report["added"])
        self.assertEqual(report["removed"], [])

    def test_diff_unreadable_snapshot_is_a_usage_error(self):
        a = self.snapshot_to("a.json")
        code, out, err = run("edges", "--diff", str(a), str(self.tmp / "missing.json"))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("error:", err)

    def test_diff_malformed_snapshot_is_a_usage_error(self):
        a = self.snapshot_to("a.json")
        bad = self.tmp / "bad.json"
        bad.write_text("{not json")
        code, _, err = run("edges", "--diff", str(a), str(bad))
        self.assertEqual(code, 2)
        self.assertIn("error:", err)


if __name__ == "__main__":
    unittest.main()
