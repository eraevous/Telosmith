"""The user-level hook body (`aec hook run`) and the `aec hook` command line, called in-process.

tests/test_user_hook.py runs the installed hook end to end in a throwaway venv, so coverage of `run()` and
`cli()` happens in a subprocess. These tests call them directly, with the package-integrity check stubbed
(`verify` is tested on its own there): each exit code `run()` documents, the relative-RELAYKIT_RECORDS
rewrite, the stale-edges cleanup, and each `aec hook` subcommand's output and refusal.
"""
import argparse
import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from aec import userhook as U

DANGLING = json.dumps({"id": "X", "version": 1, "type": "requirement", "subject": "s", "text": "t",
                       "relations": [{"rel": "serves", "to": "Y@1"}]}) + "\n"


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid"))


class _Project(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = pathlib.Path(self.tmp.name).resolve() / "proj"
        (self.p / ".aec").mkdir(parents=True)
        (self.p / ".aec" / "records.jsonl").write_text("")
        (self.p / "m.py").write_text("def f():\n    return 1\n")
        patcher = mock.patch.object(U, "verify", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, project=None):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = U.run(str(self.p) if project is None else project, None)
        return rc, err.getvalue()

    def leftovers(self):
        return sorted(n.name for n in (self.p / ".aec").glob(".hook-*"))


class RunRefusalTests(_Project):
    def test_failed_verification_is_refused_before_anything_runs(self):
        with mock.patch.object(U, "verify", side_effect=U.Refused("tampered")), \
             mock.patch.object(U, "_call") as call:
            rc, err = self.run_hook()
        self.assertEqual(rc, U.REFUSED)
        self.assertIn("refused to run: tampered", err)
        call.assert_not_called()

    def test_relative_project_path_exits_1(self):
        rc, err = self.run_hook(project="proj")
        self.assertEqual(rc, 1)
        self.assertIn("must be absolute", err)

    def test_missing_aec_directory_is_refused(self):
        shutil.rmtree(self.p / ".aec")
        rc, err = self.run_hook()
        self.assertEqual(rc, U.REFUSED)
        self.assertIn("is not a directory inside the project", err)

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symlinks")
    def test_symlinked_records_file_is_refused(self):
        real = pathlib.Path(self.tmp.name) / "elsewhere.jsonl"
        real.write_text("")
        rec = self.p / ".aec" / "records.jsonl"
        rec.unlink()
        rec.symlink_to(real)
        with mock.patch.object(U, "_call") as call:
            rc, err = self.run_hook()
        self.assertEqual(rc, U.REFUSED)
        self.assertIn("records.jsonl is a symlink", err)
        call.assert_not_called()


class RunStepTests(_Project):
    def test_relative_relaykit_records_is_rewritten_against_the_project(self):
        with mock.patch.dict(os.environ, {"RELAYKIT_RECORDS": "records"}), \
             mock.patch.object(U, "_produce", return_value=1):
            self.run_hook()
            self.assertEqual(os.environ["RELAYKIT_RECORDS"], str(self.p / "records"))

    def test_absolute_relaykit_records_is_left_alone(self):
        absolute = str(pathlib.Path(self.tmp.name) / "shared")
        with mock.patch.dict(os.environ, {"RELAYKIT_RECORDS": absolute}), \
             mock.patch.object(U, "_produce", return_value=1):
            self.run_hook()
            self.assertEqual(os.environ["RELAYKIT_RECORDS"], absolute)

    def test_failed_edges_refresh_removes_the_stale_file_and_skips_the_check(self):
        stale = self.p / ".aec" / "edges.jsonl"
        stale.write_text("old\n")
        with mock.patch.object(U, "_produce", return_value=1), mock.patch.object(U, "_call") as call:
            rc, err = self.run_hook()
        self.assertEqual(rc, 1)
        self.assertIn("could not refresh .aec/edges.jsonl", err)
        self.assertFalse(stale.exists())
        call.assert_not_called()

    def test_records_check_error_exits_2_with_its_report(self):
        (self.p / ".aec" / "records.jsonl").write_text(DANGLING)
        rc, err = self.run_hook()
        self.assertEqual(rc, 2)
        self.assertIn("X@1: serves -> Y@1 does not resolve", err)
        self.assertEqual(self.leftovers(), [])

    def test_outside_git_the_impact_step_is_skipped_and_the_hook_passes(self):
        rc, err = self.run_hook()
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue((self.p / ".aec" / "edges.jsonl").is_file())
        self.assertFalse((self.p / ".aec" / "hook-before.jsonl").exists())
        self.assertEqual(self.leftovers(), [])

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_clean_committed_project_runs_every_step_and_passes(self):
        _git("init", "-q", cwd=self.p)
        _git("add", "-A", cwd=self.p)
        _git("commit", "-qm", "init", cwd=self.p)
        rc, err = self.run_hook()
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue((self.p / ".aec" / "edges.jsonl").is_file())
        self.assertTrue((self.p / ".aec" / "hook-before.jsonl").is_file())
        self.assertEqual(self.leftovers(), [])

    def test_affected_conclusions_exit_2_with_the_status_note(self):
        def fake_call(argv):
            return (1, "stale: CL-1@1\n") if argv[0] == "code-impact" else (0, "")
        with mock.patch.object(U, "_produce", return_value=0), mock.patch.object(U, "_call", side_effect=fake_call):
            rc, err = self.run_hook()
        self.assertEqual(rc, 2)
        self.assertTrue(err.startswith("stale: CL-1@1\n(Telosmith: stale/needs_review lines are status changes"))


class CallAndProduceTests(unittest.TestCase):
    def test_call_reports_an_exception_instead_of_raising(self):
        with mock.patch("aec.__main__.main", side_effect=RuntimeError("boom")):
            self.assertEqual(U._call(["check"]), (1, "RuntimeError: boom\n"))

    def test_call_maps_system_exit(self):
        with mock.patch("aec.__main__.main", side_effect=SystemExit(3)):
            self.assertEqual(U._call(["x"])[0], 3)
        with mock.patch("aec.__main__.main", side_effect=SystemExit("usage")):
            self.assertEqual(U._call(["x"])[0], 1)

    def test_produce_leaves_dest_untouched_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            dest = pathlib.Path(d) / "out.jsonl"
            dest.write_text("kept\n")
            with mock.patch.object(U, "_call", return_value=(1, "")):
                self.assertEqual(U._produce(["edges", d], pathlib.Path(d), str(dest)), 1)
            self.assertEqual(dest.read_text(), "kept\n")
            self.assertEqual(sorted(p.name for p in pathlib.Path(d).iterdir()), ["out.jsonl"])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = pathlib.Path(self.tmp.name) / "settings.json"
        ap = argparse.ArgumentParser()
        U.add_parser(ap.add_subparsers(dest="cmd"))
        self.ap = ap

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = U.cli(self.ap.parse_args(["hook", *argv]), self.ap)
        return rc, out.getvalue(), err.getvalue()

    def test_install_writes_the_hook_and_says_what_it_does_not_do(self):
        with mock.patch.object(U, "verify", return_value=[]), mock.patch.object(U, "record_pin", return_value="ab" * 32):
            rc, out, _ = self.cli("install", "--settings", str(self.settings))
            again = self.cli("install", "--settings", str(self.settings))[1]
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith(f"installed: {self.settings}\n"))
        self.assertIn("does not disable a checkout's own hooks", out)
        self.assertTrue(again.startswith(f"unchanged: {self.settings}\n"))
        cmd = json.loads(self.settings.read_text())["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
        self.assertIn(U.MARKER, cmd)
        self.assertIn("ab" * 32, cmd)

    def test_install_refuses_an_aec_that_fails_verification(self):
        with mock.patch.object(U, "verify", side_effect=U.Refused("not in a venv")):
            rc, out, err = self.cli("install", "--settings", str(self.settings))
        self.assertEqual((rc, out), (1, ""))
        self.assertIn("refused: not in a venv", err)
        self.assertFalse(self.settings.exists())

    def test_print_writes_nothing(self):
        with mock.patch.object(U, "verify", return_value=[]), mock.patch.object(U, "record_pin", return_value="cd" * 32):
            rc, out, _ = self.cli("print", "--settings", str(self.settings))
        self.assertEqual(rc, 0)
        entry = json.loads(out)["hooks"]["PostToolUse"][0]
        self.assertEqual(entry["matcher"], U.MATCHER)
        self.assertFalse(self.settings.exists())

    def test_uninstall_reports_absent_and_removed(self):
        self.assertEqual(self.cli("uninstall", "--settings", str(self.settings))[:2],
                         (0, f"absent: {self.settings}\n"))
        U.install(self.settings, "/usr/bin/python3", "0" * 64)
        self.assertEqual(self.cli("uninstall", "--settings", str(self.settings))[:2],
                         (0, f"removed: {self.settings}\n"))
        self.assertEqual(json.loads(self.settings.read_text()), {})

    def test_verify_prints_each_check_and_the_pin(self):
        with mock.patch.object(U, "verify", return_value=["a", "b"]) as v, \
             mock.patch.object(U, "record_pin", return_value="ef" * 32):
            rc, out, _ = self.cli("verify", "--pin", "ef" * 32)
        v.assert_called_once_with("ef" * 32)
        self.assertEqual((rc, out), (0, f"ok: a\nok: b\npin: {'ef' * 32}\n"))

    def test_verify_refusal_exits_1(self):
        with mock.patch.object(U, "verify", side_effect=U.Refused("pin mismatch")):
            rc, out, err = self.cli("verify")
        self.assertEqual((rc, out, err), (1, "", "refused: pin mismatch\n"))

    def test_run_dispatches_to_the_hook_body(self):
        with mock.patch.object(U, "run", return_value=7) as r:
            self.assertEqual(self.cli("run", "/abs/project", "--pin", "p")[0], 7)
        r.assert_called_once_with("/abs/project", "p")


if __name__ == "__main__":
    unittest.main()
