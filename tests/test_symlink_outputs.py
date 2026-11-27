"""Generated outputs never write through a symlink the checkout planted.

The project-level Claude hook from `aec init` writes `.aec/edges.jsonl` and `.aec/hook-before.jsonl`
inside the checkout. A branch controls those paths, so it can make either one a symlink to a file the
developer owns (a shell startup file, say); writing through it would overwrite that file on the next
edit (Codex security review on #79, which fixed the user-level hook; this is the same gap in the
project hook and the CLI it calls).

Two layers, either of which stops it:
- `aec edges -o`, `aec edges --legacy-csv` and `aec snapshot -o` write a fresh file and rename it onto
  the destination, which replaces a symlink there instead of following it. Old hook text gets this
  with an upgraded aec.
- The hook text refuses to run when `.aec`, `records.jsonl` or either output is a symlink, so the new
  snippet is safe even against an older installed aec.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from _platform import BASH, NO_BASH, POSIX_MODES

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = str(ROOT / "src")
sys.path.insert(0, SRC)

from aec import edges as E  # noqa: E402
from aec.init import HOOK_COMMAND, init  # noqa: E402

VICTIM_TEXT = "export PRECIOUS=1\n"


def _aec(*args, cwd):
    env = dict(os.environ, PYTHONPATH=SRC)
    return subprocess.run([sys.executable, "-m", "aec", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=60)


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._dirs = [tempfile.TemporaryDirectory() for _ in range(2)]
        self.project = pathlib.Path(self._dirs[0].name).resolve()
        self.outside = pathlib.Path(self._dirs[1].name).resolve()
        (self.project / "pkg").mkdir()
        (self.project / "pkg" / "__init__.py").write_text("def f():\n    return 1\n")
        self.victim = self.outside / "bashrc"
        self.victim.write_text(VICTIM_TEXT)

    def tearDown(self):
        for d in self._dirs:
            d.cleanup()

    def assert_victim_untouched(self):
        self.assertEqual(self.victim.read_text(), VICTIM_TEXT, "a write followed the planted symlink")


class CliOutputTests(_Tmp):
    def _plant(self, rel):
        dest = self.project / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(self.victim)
        return dest

    def test_edges_output_replaces_a_symlink(self):
        dest = self._plant(".aec/edges.jsonl")
        done = _aec("edges", str(self.project), "-o", str(dest), cwd=self.outside)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assert_victim_untouched()
        self.assertFalse(dest.is_symlink())
        self.assertEqual(E.load(dest)["header"]["files"], 1)

    def test_legacy_csv_replaces_a_symlink(self):
        dest = self._plant("edges.csv")
        done = _aec("edges", str(self.project), "--legacy-csv", str(dest), cwd=self.outside)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assert_victim_untouched()
        self.assertFalse(dest.is_symlink())

    def test_snapshot_output_replaces_a_symlink(self):
        dest = self._plant(".aec/hook-before.jsonl")
        done = _aec("snapshot", str(self.project), "-o", str(dest), cwd=self.outside)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assert_victim_untouched()
        self.assertFalse(dest.is_symlink())

    def test_clean_output_is_a_readable_regular_file(self):  # decoy: the ordinary case still works
        dest = self.project / "out" / "edges.jsonl"
        done = _aec("edges", str(self.project), "-o", str(dest), cwd=self.outside)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(dest.is_file() and not dest.is_symlink())
        reference = self.project / "out" / "reference"
        reference.write_text("x")  # an ordinary write under the same umask
        self.assertEqual(os.stat(dest).st_mode & 0o777, os.stat(reference).st_mode & 0o777,
                         "same mode as an ordinary write, not mkstemp's 0600")
        reference.unlink()
        self.assertEqual([p.name for p in dest.parent.iterdir()], ["edges.jsonl"], "no temp file left behind")


    @unittest.skipUnless(os.name == "posix", POSIX_MODES)
    def test_rewrite_keeps_an_existing_files_mode(self):  # Copilot on #83: don't widen a private file to 0644
        dest = self.project / "private.jsonl"
        dest.write_text("old")
        os.chmod(dest, 0o600)
        E.write_replacing(dest, "new")
        self.assertEqual(dest.read_text(), "new")
        self.assertEqual(os.stat(dest).st_mode & 0o777, 0o600)

    @unittest.skipUnless(os.name == "posix", POSIX_MODES)
    def test_restrictive_umask_is_honoured(self):  # Copilot on #83: a 077 umask gives 0600, like an ordinary write
        old = os.umask(0o077)
        try:
            dest = self.project / "fresh.jsonl"
            E.write_replacing(dest, "x")
        finally:
            os.umask(old)
        self.assertEqual(os.stat(dest).st_mode & 0o777, 0o600)

    def test_replaced_symlink_does_not_take_the_targets_mode(self):
        os.chmod(self.victim, 0o640)
        dest = self.project / "link.jsonl"
        dest.symlink_to(self.victim)
        E.write_replacing(dest, "x")
        self.assert_victim_untouched()
        umask = os.umask(0); os.umask(umask)
        self.assertEqual(os.stat(dest).st_mode & 0o777, 0o666 & ~umask)


@unittest.skipUnless(BASH and shutil.which("git"), NO_BASH + "; and git")
class ProjectHookTests(_Tmp):
    def setUp(self):
        super().setUp()
        init(self.project, owner="tester", hooks=True)
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        subprocess.run(["git", "-C", str(self.project), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.project), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-qm", "init"], check=True)

    def _hook(self):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.project), PYTHONPATH=SRC)
        return subprocess.run([BASH, "-c", HOOK_COMMAND], env=env, capture_output=True, text=True, timeout=120)

    def _swap_for_link(self, rel, target):
        path = self.project / rel
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif os.path.lexists(path):
            path.unlink()
        path.symlink_to(target)

    def test_hook_refuses_a_symlinked_edges_output(self):
        self._swap_for_link(".aec/edges.jsonl", self.victim)
        done = self._hook()
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("symlink", done.stderr)
        self.assert_victim_untouched()

    def test_hook_refuses_a_symlinked_before_output(self):
        self._swap_for_link(".aec/hook-before.jsonl", self.victim)
        done = self._hook()
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assert_victim_untouched()

    def test_hook_refuses_a_symlinked_records_file(self):
        (self.outside / "records.jsonl").write_text((self.project / ".aec" / "records.jsonl").read_text())
        self._swap_for_link(".aec/records.jsonl", self.outside / "records.jsonl")
        done = self._hook()
        self.assertEqual(done.returncode, 2, done.stderr)

    def test_hook_refuses_a_symlinked_aec_directory(self):
        elsewhere = self.outside / "dot-aec"
        shutil.copytree(self.project / ".aec", elsewhere)
        (elsewhere / "edges.jsonl").write_text(VICTIM_TEXT)
        self._swap_for_link(".aec", elsewhere)
        done = self._hook()
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertEqual((elsewhere / "edges.jsonl").read_text(), VICTIM_TEXT, "wrote into the link's target")

    def test_clean_project_hook_runs(self):  # decoy: no symlinks, the hook passes and writes its outputs
        done = self._hook()
        self.assertEqual(done.returncode, 0, done.stderr)
        for name in ("edges.jsonl", "hook-before.jsonl"):
            path = self.project / ".aec" / name
            self.assertTrue(path.is_file() and not path.is_symlink(), name)


class InitTests(_Tmp):
    def test_init_does_not_write_through_a_dangling_symlink(self):
        (self.project / ".aec").mkdir()
        missing = self.outside / "planted.jsonl"
        (self.project / ".aec" / "records.jsonl").symlink_to(missing)
        result = init(self.project, owner="tester", hooks=False)
        self.assertFalse(missing.exists(), "init created a file at the symlink's target")
        self.assertIn(".aec/records.jsonl", result["kept"])


if __name__ == "__main__":
    unittest.main()
