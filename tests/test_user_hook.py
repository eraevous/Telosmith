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

    def test_sibling_hooks_in_our_entry_survive(self):
        U.install(self.path, "/env/bin/python3", "a" * 64)
        data = json.loads(self.path.read_text())
        sibling = {"type": "command", "command": "echo unrelated-check"}
        data["hooks"]["PostToolUse"][0]["hooks"].append(sibling)
        self.path.write_text(json.dumps(data))
        self.assertEqual(U.install(self.path, "/env/bin/python3", "b" * 64), "updated")
        post = json.loads(self.path.read_text())["hooks"]["PostToolUse"]
        self.assertEqual(post[0], {"matcher": U.MATCHER, "hooks": [sibling]})
        self.assertIn("b" * 64, post[1]["hooks"][0]["command"])
        self.assertEqual(U.uninstall(self.path), "removed")
        self.assertEqual(json.loads(self.path.read_text())["hooks"]["PostToolUse"],
                         [{"matcher": U.MATCHER, "hooks": [sibling]}])

    def test_refuses_a_settings_file_that_is_not_an_object(self):
        self.path.write_text("[]")
        with self.assertRaises(ValueError):
            U.install(self.path, "/env/bin/python3", "a" * 64)

    def test_command_shape(self):
        cmd = U.hook_command("/my env/bin/python3", "c" * 64)
        self.assertIn("'/my env/bin/python3' -I -c ", cmd)  # absolute, quoted, isolated
        self.assertLess(cmd.index("cd / && exec"), cmd.index(" -I -c "))
        self.assertIn('[ -f "$P/.aec/records.jsonl" ] || exit 0', cmd)
        self.assertNotIn("-m aec", cmd)  # the package is imported only after the bootstrap verified it
        boot = U.BOOTSTRAP_SRC
        self.assertLess(boot.index("verify(sys.argv[1])"), boot.index("from aec"))
        self.assertNotIn("import aec", U.VERIFY_SRC)
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
        target = self.pkg() / "impact.py"  # imported by aec.__main__, so it would run before any in-package check
        original = target.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            ran = pathlib.Path(tmp) / "tampered-ran"
            target.write_bytes(original + f"\nopen({json.dumps(str(ran))}, 'w').write('ran')\n".encode())
            try:
                out = self.aec("hook", "verify")
                self.assertIn("does not match its RECORD hash", out.stderr)
                ran.unlink(missing_ok=True)  # `aec hook verify` imports the package; the hook must not
                project = pathlib.Path(tmp) / "proj"
                (project / ".aec").mkdir(parents=True)
                (project / ".aec" / "records.jsonl").write_text("")
                env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
                run = subprocess.run(["bash", "-c", U.hook_command(str(self.py), pin)], env=env,
                                     capture_output=True, text=True, timeout=60)
                self.assertEqual(run.returncode, U.REFUSED)
                self.assertIn("refused to run", run.stderr)
                self.assertFalse(ran.exists(), "tampered package code ran before the integrity check")
            finally:
                target.write_bytes(original)
        self.assertEqual(self.aec("hook", "verify", "--pin", pin).returncode, 0)

    def test_tampered_bytecode_cache_never_runs(self):
        """A .pyc whose header still matches the unchanged source would be loaded instead of the source."""
        import importlib.util
        import marshal
        pin = self.pin()  # imports the package, so impact.py's cache exists
        source = self.pkg() / "impact.py"
        pyc = pathlib.Path(importlib.util.cache_from_source(str(source)))
        self.assertTrue(pyc.exists(), "expected a bytecode cache to tamper with")
        original = pyc.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            ran = pathlib.Path(tmp) / "pyc-ran"
            payload = source.read_text() + f"\nopen({json.dumps(str(ran))}, 'w').write('ran')\n"
            pyc.write_bytes(original[:16] + marshal.dumps(compile(payload, str(source), "exec")))
            try:
                project = pathlib.Path(tmp) / "proj"
                (project / ".aec").mkdir(parents=True)
                (project / ".aec" / "records.jsonl").write_text("")
                subprocess.run(["git", "init", "-q", str(project)], check=True)
                env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
                subprocess.run(["bash", "-c", U.hook_command(str(self.py), pin)], env=env,
                               capture_output=True, text=True, timeout=120)
                self.assertTrue((project / ".aec" / "edges.jsonl").exists(), "the hook ran aec")
                self.assertFalse(ran.exists(), "the hook loaded unverified cached bytecode")
            finally:
                pyc.write_bytes(original)

    def test_symlinked_directory_in_package_is_refused(self):
        pin = self.pin()
        with tempfile.TemporaryDirectory() as tmp:
            ran = pathlib.Path(tmp) / "symlink-ran"
            payload = pathlib.Path(tmp) / "payload"
            payload.mkdir()
            (payload / "__init__.py").write_text(f"open({json.dumps(str(ran))}, 'w').write('ran')\n")
            link = self.pkg() / "impact"  # a package beats the verified impact.py at import time
            link.symlink_to(payload, target_is_directory=True)
            try:
                project = pathlib.Path(tmp) / "proj"
                (project / ".aec").mkdir(parents=True)
                (project / ".aec" / "records.jsonl").write_text("")
                env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
                run = subprocess.run(["bash", "-c", U.hook_command(str(self.py), pin)], env=env,
                                     capture_output=True, text=True, timeout=60)
                self.assertEqual(run.returncode, U.REFUSED, run.stderr)
                self.assertIn("is a symlink", run.stderr)
                self.assertFalse(ran.exists(), "code behind a symlinked directory ran")
            finally:
                link.unlink()

    def _project(self, tmp):
        project = pathlib.Path(tmp) / "proj"
        (project / ".aec").mkdir(parents=True)
        (project / ".aec" / "records.jsonl").write_text("")
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        return project

    def _hook(self, project, pin):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
        return subprocess.run(["bash", "-c", U.hook_command(str(self.py), pin)], env=env,
                              capture_output=True, text=True, timeout=120)

    def test_symlinked_outputs_are_replaced_not_followed(self):
        pin = self.pin()
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp)
            victims = []
            for name in ("edges.jsonl", "hook-before.jsonl"):
                victim = pathlib.Path(tmp) / f"victim-{name}"
                victim.write_text("keep me\n")
                (project / ".aec" / name).symlink_to(victim)
                victims.append(victim)
            self._hook(project, pin)
            for victim in victims:
                self.assertEqual(victim.read_text(), "keep me\n", "the hook wrote through a symlink")
            self.assertFalse((project / ".aec" / "edges.jsonl").is_symlink())
            self.assertTrue((project / ".aec" / "edges.jsonl").is_file())
            self.assertEqual([p.name for p in (project / ".aec").glob(".hook-*")], [], "temp files left behind")

    def test_symlinked_aec_directory_is_refused(self):
        pin = self.pin()
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp)
            elsewhere = pathlib.Path(tmp) / "elsewhere"
            (project / ".aec").rename(elsewhere)
            (project / ".aec").symlink_to(elsewhere, target_is_directory=True)
            run = self._hook(project, pin)
            self.assertEqual(run.returncode, U.REFUSED, run.stderr)
            self.assertIn("is a symlink", run.stderr)
            self.assertFalse((elsewhere / "edges.jsonl").exists())

    def test_deleted_package_file_and_shadow_module_are_refused(self):
        pin = self.pin()
        init = self.pkg() / "__init__.py"
        original = init.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            ran = pathlib.Path(tmp) / "shadow-ran"
            shadow = self.pkg().parent / "aec.py"  # site-packages, outside the walked package directory
            shadow.write_text(f"open({json.dumps(str(ran))}, 'w').write('ran')\n")
            init.unlink()
            try:
                run = self._hook(self._project(tmp), pin)
                self.assertEqual(run.returncode, U.REFUSED, run.stderr)
                self.assertIn("missing", run.stderr)
                self.assertFalse(ran.exists(), "a module outside the package ran in its place")
                init.write_bytes(original)
                # With the package intact, the package directory wins over a same-named module beside it.
                self._hook(self._project(tmp + "/b"), pin)
                self.assertFalse(ran.exists())
            finally:
                init.write_bytes(original)
                shadow.unlink(missing_ok=True)

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
