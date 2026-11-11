"""The generated Claude hook and CI snippet never import aec from the checkout.

Both run `python3 ... -m aec` with the repository as the current directory. Without `-P`,
Python would import an `aec.py` or `aec/` package that a branch adds there, ahead of the
installed Telosmith: on a developer machine that runs the branch's code as the developer
(Codex security review on eraevous/crank-mem-eval#7), and in CI it could fake a passing
check. These tests plant such a shadow module and check it never runs.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from aec.init import HOOK_COMMAND, CI_IMPACT


@unittest.skipUnless(sys.version_info >= (3, 11) and shutil.which("bash"), "needs Python 3.11+ and bash")
class HookSafePathTests(unittest.TestCase):
    def test_hook_never_imports_a_checkout_aec(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = pathlib.Path(tmp)
            marker = project / "shadow-ran"
            shadow = f"open({json.dumps(str(marker))}, 'w').write('ran')\nprint('--exit-code')\n"
            (project / "aec").mkdir()
            (project / "aec" / "__init__.py").write_text("")
            (project / "aec" / "__main__.py").write_text(shadow)
            (project / "aec.py").write_text(shadow)
            env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
            env.pop("PYTHONPATH", None)
            subprocess.run(["bash", "-c", HOOK_COMMAND], env=env, capture_output=True, timeout=60)
            self.assertFalse(marker.exists(), "the hook imported aec from the checkout")

    def test_every_aec_call_uses_safe_path(self):
        for name, text in (("HOOK_COMMAND", HOOK_COMMAND), ("CI_IMPACT", CI_IMPACT)):
            with self.subTest(name):
                self.assertNotIn("python3 -m aec", text)
                self.assertIn("python3 -P -m aec", text)


if __name__ == "__main__":
    unittest.main()
