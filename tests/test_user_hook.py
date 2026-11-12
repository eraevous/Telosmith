"""DEC-223 draft: the user-level hook (`aec hook`) runs only a verified, installed aec.

Unit tests cover the settings-file edits and the shape of the command. The end-to-end class installs this
checkout into a throwaway venv (skipped if that isn't possible offline) and checks the integrity refusals and
that nothing in a hostile checkout is imported.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from aec import userhook as U

ROOT = pathlib.Path(__file__).resolve().parent.parent


class SettingsEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / "settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_install_is_idempotent_and_keeps_other_settings(self):
        other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}
        self.path.write_text(json.dumps({"model": "x", "hooks": {"PostToolUse": [other]}}))
        self.assertEqual(U.install(self.path, "/env/bin/python3", "a" * 64), "installed")
        first = self.path.read_text()
        self.assertEqual(U.install(self.path, "/env/bin/python3", "a" * 64), "unchanged")
        self.assertEqual(self.path.read_text(), first)
        data = json.loads(first)
        self.assertEqual(data["model"], "x")
        self.assertEqual(data["hooks"]["PostToolUse"][0], other)
        self.assertEqual(len(data["hooks"]["PostToolUse"]), 2)

    def test_reinstall_replaces_our_old_entry(self):
        U.install(self.path, "/env/bin/python3", "a" * 64)
        self.assertEqual(U.install(self.path, "/env/bin/python3", "b" * 64), "updated")
        post = json.loads(self.path.read_text())["hooks"]["PostToolUse"]
        self.assertEqual(len(post), 1)
        self.assertIn("b" * 64, post[0]["hooks"][0]["command"])

    def test_uninstall_removes_only_ours(self):
        self.assertEqual(U.uninstall(self.path), "absent")
        self.assertFalse(self.path.exists())
        U.install(self.path, "/env/bin/python3", "a" * 64)
        self.assertEqual(U.uninstall(self.path), "removed")
        self.assertEqual(json.loads(self.path.read_text()), {})
        other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}
        self.path.write_text(json.dumps({"hooks": {"PostToolUse": [other]}}))
        U.install(self.path, "/env/bin/python3", "a" * 64)
        U.uninstall(self.path)
        self.assertEqual(json.loads(self.path.read_text()), {"hooks": {"PostToolUse": [other]}})

    def test_refuses_a_settings_file_that_is_not_an_object(self):
        self.path.write_text("[]")
        with self.assertRaises(ValueError):
            U.install(self.path, "/env/bin/python3", "a" * 64)

    def test_command_shape(self):
        cmd = U.hook_command("/my env/bin/python3", "c" * 64)
        self.assertIn("'/my env/bin/python3' -I -m aec hook run", cmd)  # absolute, quoted, isolated
        self.assertLess(cmd.index("cd / && exec"), cmd.index("-I -m aec"))
        self.assertIn('[ -f "$P/.aec/records.jsonl" ] || exit 0', cmd)
        self.assertNotIn("python3 -m aec", cmd.replace("python3 -I -m aec", ""))
        self.assertTrue(cmd.endswith(U.MARKER))

    def test_source_checkout_is_never_verified(self):
        with self.assertRaises(U.Refused):
            U.verify()


def _venv(dest: pathlib.Path) -> pathlib.Path | None:
    try:
        subprocess.run([sys.executable, "-m", "venv", str(dest)], check=True, capture_output=True, timeout=120)
        py = dest / "bin" / "python3"
        subprocess.run([str(py), "-m", "pip", "install", "-q", "--no-deps", str(ROOT)],
                       check=True, capture_output=True, timeout=300)
        return py
    except (subprocess.SubprocessError, OSError):
        return None


@unittest.skipUnless(shutil.which("bash") and os.name == "posix", "needs bash")
class InstalledHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.py = _venv(pathlib.Path(cls.tmp.name) / "venv")
        if cls.py is None:
            cls.tmp.cleanup()
            raise unittest.SkipTest("could not build a venv with this checkout installed")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def aec(self, *args, env=None, cwd="/"):
        return subprocess.run([str(self.py), "-I", "-m", "aec", *args], capture_output=True, text=True,
                              cwd=cwd, env=env, timeout=120)

    def pkg(self) -> pathlib.Path:
        out = subprocess.run([str(self.py), "-I", "-c", "import aec,os;print(os.path.dirname(aec.__file__))"],
                             capture_output=True, text=True, cwd="/", check=True)
        return pathlib.Path(out.stdout.strip())

    def pin(self) -> str:
        out = self.aec("hook", "verify")
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip().splitlines()[-1].split()[-1]

    def test_verify_then_refusals(self):
        pin = self.pin()
        self.assertEqual(self.aec("hook", "verify", "--pin", pin).returncode, 0)
        wrong = self.aec("hook", "verify", "--pin", "0" * 64)
        self.assertEqual(wrong.returncode, 1)
        self.assertIn("RECORD changed", wrong.stderr)
        planted = self.pkg() / "planted.py"
        planted.write_text("")
        try:
            out = self.aec("hook", "verify")
            self.assertEqual(out.returncode, 1)
            self.assertIn("not in the installed RECORD", out.stderr)
        finally:
            planted.unlink()
        target = self.pkg() / "graph.py"
        original = target.read_bytes()
        target.write_bytes(original + b"\n# tampered\n")
        try:
            out = self.aec("hook", "verify")
            self.assertIn("does not match its RECORD hash", out.stderr)
            run = self.aec("hook", "run", "--pin", pin, "/")
            self.assertEqual(run.returncode, U.REFUSED)
            self.assertIn("refused to run", run.stderr)
        finally:
            target.write_bytes(original)
        self.assertEqual(self.aec("hook", "verify", "--pin", pin).returncode, 0)

    def test_installed_hook_ignores_a_hostile_checkout(self):
        pin = self.pin()
        with tempfile.TemporaryDirectory() as tmp:
            project = pathlib.Path(tmp)
            marker = project / "shadow-ran"
            shadow = f"open({json.dumps(str(marker))}, 'w').write('ran')\n"
            (project / "aec").mkdir()
            (project / "aec" / "__init__.py").write_text(shadow)
            (project / "aec" / "__main__.py").write_text(shadow)
            for name in ("runpy", "site", "sitecustomize", "encodings", "json", "argparse"):
                (project / f"{name}.py").write_text(shadow)
            env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), PYTHONPATH=str(project))
            cmd = U.hook_command(str(self.py), pin)
            quiet = subprocess.run(["bash", "-c", cmd], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual((quiet.returncode, quiet.stderr), (0, ""), "no records: the hook stays quiet")
            (project / ".aec").mkdir()
            (project / ".aec" / "records.jsonl").write_text("")
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            subprocess.run(["bash", "-c", cmd], env=env, cwd=project, capture_output=True, text=True, timeout=120)
            self.assertFalse(marker.exists(), "the hook imported code from the checkout")
            self.assertTrue((project / ".aec" / "edges.jsonl").exists(), "the hook ran the installed aec")


if __name__ == "__main__":
    unittest.main()
