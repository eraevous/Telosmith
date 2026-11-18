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

    def _run(self, command, pythonpath=SRC, project=None):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project or self.project))
        env.pop("PYTHONPATH", None)
        if pythonpath is not None:
            env["PYTHONPATH"] = pythonpath
        return subprocess.run(["bash", "-c", command], env=env, capture_output=True, text=True, timeout=120)

    def _both(self):
        # Each form runs on its own restored copy of the checkout, so one form's outputs can't shape the other's
        # result (Kate, AEC-R-hook-project-parity@1). Symlinks are copied as links, pointing where they did.
        done = {}
        for name, cmd in FORMS.items():
            copy = pathlib.Path(self._dirs[0].name + "-" + name)
            shutil.copytree(self.project, copy, symlinks=True)
            try:
                done[name] = self._run(cmd, project=copy)
            finally:
                shutil.rmtree(copy)
        return done

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

    def test_symlinked_aec_dir_and_records_are_refused_by_both(self):
        # .aec itself and the records file, each separately; nothing behind the link is written.
        aec = self.project / ".aec"
        shutil.copytree(aec, self.outside / "aec-real")
        before = {f.name: f.read_bytes() for f in (self.outside / "aec-real").iterdir() if f.is_file()}
        shutil.rmtree(aec)
        aec.symlink_to(self.outside / "aec-real")
        done = self.assertSameExit(2)
        self.assertTrue(all("symlink" in d.stderr for d in done.values()))
        after = {f.name: f.read_bytes() for f in (self.outside / "aec-real").iterdir() if f.is_file()}
        self.assertEqual(after, before)
        aec.unlink()
        shutil.copytree(self.outside / "aec-real", aec)

        records = aec / "records.jsonl"
        real = self.outside / "records.jsonl"
        real.write_bytes(records.read_bytes())
        records.unlink()
        records.symlink_to(real)
        kept = real.read_bytes()
        done = self.assertSameExit(2)
        self.assertTrue(all("symlink" in d.stderr for d in done.values()))
        self.assertEqual(real.read_bytes(), kept)

    def test_dangling_output_links_are_refused_and_never_created(self):
        for rel in (".aec/edges.jsonl", ".aec/hook-before.jsonl"):
            target = self.outside / ("missing-" + rel.replace("/", "_"))
            path = self.project / rel
            if os.path.lexists(path):
                path.unlink()
            path.symlink_to(target)
            done = self.assertSameExit(2)
            self.assertTrue(all("symlink" in d.stderr for d in done.values()), rel)
            self.assertFalse(os.path.lexists(target), rel)
            path.unlink()

    def test_output_that_cannot_be_replaced_exits_like_inline(self):
        # A directory where an output file goes: the inline hook's `aec ... -o <dir>` fails and takes its
        # failure branch; the line must take the same branch, not raise (Copilot on #89).
        for rel in (".aec/hook-before.jsonl", ".aec/edges.jsonl"):
            path = self.project / rel
            if os.path.lexists(path):
                path.unlink()
            path.mkdir()
            done = self._both()
            self.assertEqual(done["inline"].returncode, done["line"].returncode,
                             f"{rel}: inline {done['inline'].stderr!r} line {done['line'].stderr!r}")
            self.assertNotIn("Traceback", done["line"].stderr, rel)
            path.rmdir()

    def test_no_aec_importable_gets_its_own_message(self):
        # Probe the way the launcher does (from /, PYTHONPATH cleared): an installed aec of any version makes
        # the missing-install path unreachable, so skip rather than read its "old aec" diagnostic as a failure.
        probe = subprocess.run(["python3", "-c",
                                "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('aec') else 1)"],
                               cwd="/", env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
                               capture_output=True)
        if probe.returncode == 0:
            self.skipTest("an aec is installed for the launcher's python3; the missing-install path is not reachable")
        done = self._run(HOOK_LINE_COMMAND, pythonpath=None)
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
