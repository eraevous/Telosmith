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
        self.assertEqual(HOOK_COMMAND.count("python3"), 1, "every aec call must go through the launcher")
        self.assertIn("( cd / && python3 -m aec", HOOK_COMMAND)

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
