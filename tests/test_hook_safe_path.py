"""The generated Claude hook never imports aec from the checkout.

Started inside the checkout, `python3 -m aec` would import an `aec.py`, `runpy.py` or any other
module that a branch adds there, ahead of the installed Telosmith, and run it as the developer
(Codex security reviews on eraevous/crank-mem-eval#7). The hook's `aec` shell function starts
Python from `/` and passes the project as absolute paths, on every supported Python (3.10+).
CI snippets are out of scope: a pull request can edit the workflow itself, so shadowing adds
nothing there.
"""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from aec.init import HOOK_COMMAND


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class HookSafePathTests(unittest.TestCase):
    def test_hook_never_imports_a_checkout_aec(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = pathlib.Path(tmp)
            marker = project / "shadow-ran"
            shadow = f"open({json.dumps(str(marker))}, 'w').write('ran')\nprint('--exit-code')\n"
            (project / "aec").mkdir()
            (project / "aec" / "__init__.py").write_text("")
            (project / "aec" / "__main__.py").write_text(shadow)
            for name in ("aec", "runpy", "os", "site", "sitecustomize", "encodings", "codecs", "io", "abc"):
                (project / f"{name}.py").write_text(shadow)
            env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
            env.pop("PYTHONPATH", None)
            subprocess.run(["bash", "-c", HOOK_COMMAND], env=env, capture_output=True, timeout=60)
            self.assertFalse(marker.exists(), "the hook imported aec from the checkout")

    def test_python_starts_only_outside_the_checkout(self):
        launcher, rest = HOOK_COMMAND.split("aec code-impact --help", 1)
        self.assertNotIn("python3", rest, "every aec call must go through the launcher")
        self.assertEqual(launcher.count("python3"), 2, "the PYTHONPATH filter and aec itself")
        self.assertLess(launcher.index("cd / && "), launcher.index("python3"))
        self.assertIn("python3 -I -c", launcher)

    def _probe(self, project, extra_env):
        """Run the launcher with a stand-in `aec` package placed outside the checkout; it reports the
        environment it saw and which file it was imported from."""
        with tempfile.TemporaryDirectory() as outside:
            pkg = pathlib.Path(outside) / "aec"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "__main__.py").write_text(
                "import json, os, aec\n"
                "print(json.dumps({'file': aec.__file__, 'cwd': os.getcwd(),"
                " 'records': os.environ.get('RELAYKIT_RECORDS'), 'pythonpath': os.environ.get('PYTHONPATH')}))\n")
            env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
            env.pop("RELAYKIT_RECORDS", None)
            env.update({k: v.replace("{outside}", outside) for k, v in extra_env.items()})
            launcher = "cd \"$CLAUDE_PROJECT_DIR\" || exit 0; " + HOOK_COMMAND.split("aec code-impact --help")[0]
            done = subprocess.run(["bash", "-c", launcher + "aec probe"], env=env,
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            return json.loads(done.stdout), outside

    def test_inherited_pythonpath_into_the_checkout_is_dropped(self):
        # Copilot on #77 (637782f): `cd /` leaves absolute PYTHONPATH entries alone, so one pointing into
        # the checkout would still import a branch's aec.py.
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as linkdir:
            project = pathlib.Path(tmp).resolve()
            marker = project / "shadow-ran"
            shadow = f"open({json.dumps(str(marker))}, 'w').write('ran')\n"
            for sub in (project, project / "src", project / "deep" / "er"):
                sub.mkdir(parents=True, exist_ok=True)
                (sub / "aec").mkdir(exist_ok=True)
                (sub / "aec" / "__init__.py").write_text(shadow)
                (sub / "aec" / "__main__.py").write_text(shadow)
            link = pathlib.Path(linkdir) / "into-checkout"
            link.symlink_to(project / "src")
            pp = os.pathsep.join([str(project), str(project / "src"), str(project / "deep" / "er"),
                                  str(link), str(project) + "/../" + project.name + "/src", "{outside}"])
            seen, outside = self._probe(project, {"PYTHONPATH": pp})
            self.assertFalse(marker.exists(), "the hook imported aec from the checkout via PYTHONPATH")
            self.assertTrue(seen["file"].startswith(outside), seen)
            self.assertEqual(seen["pythonpath"], outside, "only entries outside the checkout survive")
            self.assertEqual(seen["cwd"], "/")

    def test_pythonpath_unset_or_all_inside_leaves_it_unset(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = pathlib.Path(tmp).resolve()
            sh = HOOK_COMMAND.split("aec code-impact --help")[0]
            for pp in (None, str(project)):
                env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
                env.pop("PYTHONPATH", None)
                if pp is not None:
                    env["PYTHONPATH"] = pp
                # stop just before aec runs and report what it would get
                probe = sh.replace("python3 -m aec \"$@\"", "echo \"${PYTHONPATH-<unset>}\"")
                done = subprocess.run(["bash", "-c", probe + "aec"], env=env, capture_output=True,
                                      text=True, timeout=60)
                self.assertEqual(done.stdout.strip(), "<unset>", (pp, done.stderr))

    def test_relative_records_root_stays_project_relative(self):
        # Copilot on #77 (637782f): after `cd /`, RELAYKIT_RECORDS=records would mean /records, not the
        # checkout's records/ (docs/integrations/relay-kit.md: relative to the working directory, which
        # the hook sets to the project).
        with tempfile.TemporaryDirectory() as tmp:
            project = pathlib.Path(tmp).resolve()
            for value, expected in (("records", f"{project}/records"), ("  ../recs", f"{project}/../recs"),
                                    ("/abs/records", "/abs/records"), ("", "")):
                seen, _ = self._probe(project, {"PYTHONPATH": "{outside}", "RELAYKIT_RECORDS": value})
                self.assertEqual(seen["records"], expected, value)
            seen, _ = self._probe(project, {"PYTHONPATH": "{outside}"})
            self.assertIsNone(seen["records"], "an unset RELAYKIT_RECORDS stays unset")

    def test_relative_records_root_points_at_the_project_directory(self):
        # The rewritten value names the existing records/ directory, seen from Python running in /.
        src = str(pathlib.Path(__file__).resolve().parents[1] / "src")
        with tempfile.TemporaryDirectory() as tmp:
            project = pathlib.Path(tmp).resolve()
            (project / "records").mkdir()
            env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), PYTHONPATH=src, RELAYKIT_RECORDS="records")
            sh = "cd \"$CLAUDE_PROJECT_DIR\" || exit 0; " + HOOK_COMMAND.split("aec code-impact --help")[0]
            probe = sh.replace("python3 -m aec \"$@\"", "python3 -c 'import os; print(os.environ[\"RELAYKIT_RECORDS\"]); print(os.path.isdir(os.environ[\"RELAYKIT_RECORDS\"]))'")
            done = subprocess.run(["bash", "-c", probe + "aec"], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(done.stdout.split(), [f"{project}/records", "True"], done.stderr)

    def test_hook_still_finds_the_installed_aec(self):
        src = str(pathlib.Path(__file__).resolve().parents[1] / "src")
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, CLAUDE_PROJECT_DIR=tmp, PYTHONPATH=src)
            launcher = HOOK_COMMAND.split("aec code-impact --help")[0]
            done = subprocess.run(["bash", "-c", launcher + "aec --version"], env=env,
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
