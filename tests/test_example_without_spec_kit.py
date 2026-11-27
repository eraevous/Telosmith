"""Regression test for the without-spec-kit demo script against expected output."""
import difflib
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "examples" / "without-spec-kit"
RUN_SH = DEMO_DIR / "run.sh"
EXPECTED_TXT = DEMO_DIR / "expected.txt"


def normalize_output(text: str) -> str:
    """Replace ephemeral commit hashes and temp paths with fixed placeholders."""
    text = text.replace("\r\n", "\n")
    text = re.sub(r"vs [0-9a-f]{40,64}", "vs <SHA40>", text)
    text = re.sub(r"origin/main \([0-9a-f]{7,12}\)", "origin/main (<SHA8>)", text)
    text = re.sub(r"content at [0-9a-f]{7,12};", "content at <SHA8>;", text)
    text = re.sub(r"/tmp/[^\s]+", "<TMP_PATH>", text)
    return text


class ExampleWithoutSpecKitTest(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "the demo is a bash script that needs POSIX tools (mktemp, sed -i, git hooks "
                                      "run by bash); not supported on Windows")
    def test_demo_matches_expected_output(self):
        if shutil.which("git") is None:
            self.skipTest("git is not available on PATH")
        if shutil.which("bash") is None:
            self.skipTest("bash is not available on PATH")

        env = os.environ.copy()
        env.pop("TELOSMITH_BLOCK", None)
        env.pop("TELOSMITH_BASE", None)
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["PYTHONPATH"] = str(ROOT / "src")
        py_bin = str(Path(sys.executable).parent)
        env["PATH"] = py_bin + os.pathsep + env.get("PATH", "")

        proc = subprocess.run(
            ["bash", str(RUN_SH)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"run.sh exited with {proc.returncode}:\n{proc.stdout}",
        )

        actual = normalize_output(proc.stdout)
        expected = EXPECTED_TXT.read_text(encoding="utf-8").replace("\r\n", "\n")
        if actual != expected:
            diff = "".join(
                difflib.unified_diff(
                    expected.splitlines(keepends=True),
                    actual.splitlines(keepends=True),
                    fromfile="expected.txt",
                    tofile="actual",
                )
            )
            self.fail(f"Demo output differs from {EXPECTED_TXT}:\n{diff}")


if __name__ == "__main__":
    unittest.main()
