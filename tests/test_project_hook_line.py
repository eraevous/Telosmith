"""The one-line project hook (`aec init --hook-style line`) behaves like the inline hook it would replace.

AEC-D-braided-dcc@1, propagation D: the hook body moves into the package (`aec hook project`), so a body fix
ships with a Telosmith release instead of a settings edit in every repository. Kate's gate for replacing any
repository's hook includes "compatibility tests show the same exit behaviour as today's hook"; these run both
hooks on the same checkouts and compare. They also cover the two diagnostics the line adds.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = str(ROOT / "src")
sys.path.insert(0, SRC)

from aec.init import HOOK, HOOK_COMMAND, HOOK_LINE, HOOK_LINE_COMMAND, init  # noqa: E402

FORMS = {"inline": HOOK_COMMAND, "line": HOOK_LINE_COMMAND}


@unittest.skipUnless(shutil.which("bash") and shutil.which("git"), "needs bash and git")
class SideBySide(unittest.TestCase):
    def setUp(self):
        self._dirs = [tempfile.TemporaryDirectory() for _ in range(2)]
        self.project = pathlib.Path(self._dirs[0].name).resolve()
        self.outside = pathlib.Path(self._dirs[1].name).resolve()
        (self.project / "pkg").mkdir()
        (self.project / "pkg" / "__init__.py").write_text("def f():\n    return 1\n")
        init(self.project, owner="tester", hooks=True)
        self._git("init", "-q")
        self._commit("init")

    def tearDown(self):
        for d in self._dirs:
            d.cleanup()

    def _git(self, *args):
        subprocess.run(["git", "-C", str(self.project), *args], check=True, capture_output=True)

    def _commit(self, msg):
        self._git("add", "-A")
        self._git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)

    def _run(self, command, pythonpath=SRC):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.project))
        env.pop("PYTHONPATH", None)
        if pythonpath is not None:
            env["PYTHONPATH"] = pythonpath
        return subprocess.run(["bash", "-c", command], env=env, capture_output=True, text=True, timeout=120)

    def _both(self):
        return {name: self._run(cmd) for name, cmd in FORMS.items()}

    def assertSameExit(self, expected):
        done = self._both()
        for name, d in done.items():
            self.assertEqual(d.returncode, expected, f"{name}: {d.stderr}")
        return done

    def test_clean_checkout_is_quiet(self):
        self.assertSameExit(0)

    def test_record_check_failure_reports_2(self):
        with open(self.project / ".aec" / "records.jsonl", "a") as fh:
            fh.write(json.dumps({"id": "R-1", "version": 1, "type": "requirement", "text": "x",
                                 "relations": [{"rel": "depends_on", "to": "NOPE@1"}]}) + "\n")
        done = self.assertSameExit(2)
        self.assertEqual(done["inline"].stderr, done["line"].stderr)

    def test_linked_code_change_reports_2(self):
        rec = {"id": "R-1", "version": 1, "type": "requirement", "text": "f returns 1",
               "relations": [{"rel": "implemented_by", "to": "code:pkg.f"}]}
        with open(self.project / ".aec" / "records.jsonl", "a") as fh:
            fh.write(json.dumps(rec) + "\n")
        self._commit("record")
        (self.project / "pkg" / "__init__.py").write_text("def f():\n    return 2\n")
        done = self.assertSameExit(2)
        self.assertEqual(done["inline"].stderr, done["line"].stderr)
        self.assertIn("R-1@1", done["line"].stderr)

    def test_symlinked_outputs_are_refused_by_both(self):
        victim = self.outside / "bashrc"
        for rel in (".aec/edges.jsonl", ".aec/hook-before.jsonl"):
            victim.write_text("keep\n")
            path = self.project / rel
            if os.path.lexists(path):
                path.unlink()
            path.symlink_to(victim)
            done = self.assertSameExit(2)
            self.assertTrue(all("symlink" in d.stderr for d in done.values()), rel)
            self.assertEqual(victim.read_text(), "keep\n")
            path.unlink()

    def test_no_aec_importable_gets_its_own_message(self):
        done = self._run(HOOK_LINE_COMMAND, pythonpath=None)
        if done.returncode == 0:
            self.skipTest("an aec is installed in this interpreter; the missing-install path is not reachable")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("no aec is importable", done.stderr)

    def test_aec_without_hook_project_gets_its_own_message(self):
        fake = self.outside / "old"
        (fake / "aec").mkdir(parents=True)
        (fake / "aec" / "__init__.py").write_text("")
        (fake / "aec" / "__main__.py").write_text(
            "import sys\n"
            "if '--version' in sys.argv: print('aec 0.5.0'); sys.exit(0)\n"
            "sys.exit(2)\n")
        done = self._run(HOOK_LINE_COMMAND, pythonpath=str(fake))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("aec 0.5.0 has no 'hook project'", done.stderr)

    def test_line_is_short_and_carries_no_body(self):
        self.assertLess(len(HOOK_LINE_COMMAND), len(HOOK_COMMAND))
        for step in ("aec edges", "aec check", "aec snapshot", "code-impact"):
            self.assertNotIn(step, HOOK_LINE_COMMAND)
        self.assertIn('aec hook project "$P"', HOOK_LINE_COMMAND)


class InitStyles(unittest.TestCase):
    def test_default_stays_inline_and_line_is_opt_in(self):
        for style, expected in ((None, HOOK), ("inline", HOOK), ("line", HOOK_LINE)):
            with tempfile.TemporaryDirectory() as d:
                kwargs = {} if style is None else {"hook_style": style}
                init(d, owner="t", hooks=True, **kwargs)
                got = json.loads((pathlib.Path(d) / ".aec" / "snippets" / "claude-settings.json").read_text())
                self.assertEqual(got, expected, style)

    def test_unknown_style_is_refused_before_writing(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                init(d, owner="t", hooks=True, hook_style="bogus")
            self.assertFalse((pathlib.Path(d) / ".aec").exists())


if __name__ == "__main__":
    unittest.main()
