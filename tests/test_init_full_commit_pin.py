"""aec init pins a full commit (AEC-R-init-full-commit-pin@1, Kate; AEC-R-init-full-commit-pin-impl@1).

A local git repository stands in for the Telosmith remote, so no test touches the network."""
import functools
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import aec.init as I  # noqa: E402
from aec.init import PinResolutionError, init, resolve_commit  # noqa: E402

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_GLOBAL": os.devnull}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env=ENV).stdout.strip()


class Remote(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        r = cls.repo = Path(cls.tmp.name) / "telosmith"
        r.mkdir()
        git(r, "init", "-q", "-b", "main")
        (r / "a").write_text("1")
        git(r, "add", "a")
        git(r, "commit", "-qm", "one")
        cls.c1 = git(r, "rev-parse", "HEAD")
        (r / "a").write_text("2")
        git(r, "commit", "-qam", "two")
        cls.c2 = git(r, "rev-parse", "HEAD")
        git(r, "tag", "light", cls.c1)
        git(r, "tag", "-a", "-m", "release", "v9.9.9", cls.c1)
        cls.tag_object = git(r, "rev-parse", "v9.9.9")
        git(r, "branch", "feature", cls.c2)
        git(r, "tag", "both", cls.c1)        # a tag and a branch named alike, on different commits
        git(r, "branch", "both", cls.c2)
        git(r, "tag", "same", cls.c2)        # alike, on the same commit: not ambiguous
        git(r, "tag", "treetag", git(r, "rev-parse", "HEAD^{tree}"))     # a tag naming a tree (Codex on #91)
        git(r, "tag", "blobtag", git(r, "rev-parse", "HEAD:a"))
        git(r, "tag", "-a", "-m", "x", "annotree", git(r, "rev-parse", "HEAD^{tree}"))
        git(r, "branch", "same", cls.c2)
        cls.resolve = staticmethod(functools.partial(resolve_commit, source=str(r)))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # test_must_show 1 and 2: branch, tag and abbreviated commit resolve; an annotated tag gives its commit
    def test_branch_resolves_to_its_commit(self):
        self.assertEqual(self.resolve("main"), self.c2)
        self.assertEqual(self.resolve("feature"), self.c2)

    def test_lightweight_tag_resolves_to_its_commit(self):
        self.assertEqual(self.resolve("light"), self.c1)

    def test_annotated_tag_resolves_to_its_commit_not_the_tag_object(self):
        self.assertNotEqual(self.tag_object, self.c1)
        self.assertEqual(self.resolve("v9.9.9"), self.c1)

    def test_abbreviated_commit_resolves_in_a_checkout(self):
        self.assertEqual(resolve_commit(self.c1[:10], local=self.repo), self.c1)

    def test_git_source_prefix_is_accepted(self):
        self.assertEqual(resolve_commit("light", source="git+" + str(self.repo)), self.c1)

    # test_must_show 3: a full commit is kept
    def test_full_commit_is_preserved(self):
        self.assertEqual(self.resolve(self.c2), self.c2)
        self.assertEqual(resolve_commit(self.c1, local=self.repo), self.c1)

    def test_full_id_of_a_non_commit_or_missing_object_fails(self):  # Kate, round 10
        tree = git(self.repo, "rev-parse", "HEAD^{tree}")
        blob = git(self.repo, "rev-parse", "HEAD:a")
        for sha, why in ((tree, "a tree"), (blob, "a blob"), ("0" * 40, "no such object")):
            with self.subTest(sha=sha):
                with self.assertRaises(PinResolutionError) as cm:
                    resolve_commit(sha, local=self.repo)
                self.assertIn(why, str(cm.exception))
                with self.assertRaises(PinResolutionError) as cm:
                    self.resolve(sha)
                self.assertIn("not a commit" if why != "no such object" else "no such object", str(cm.exception))

    def test_same_commit_tag_and_branch_is_not_ambiguous(self):
        self.assertEqual(self.resolve("same"), self.c2)

    # test_must_show 5: unresolvable, ambiguous or non-commit revisions fail with a diagnostic
    def test_failures_raise_with_a_reason(self):
        cases = {
            "nope": "no tag or branch",
            "both": "both a tag",
            "treetag": "a tree, not a commit",
            "blobtag": "a blob, not a commit",
            "annotree": "a tree, not a commit",
            self.c1[:10]: "abbreviated",            # no checkout given
            "": "not a commit",
            "-x": "not a commit",
            "a b": "not a commit",
            self.c1.upper(): "",                    # not lowercase hex: looked up as a name, not found
        }
        for rev, why in cases.items():
            with self.subTest(rev=rev), self.assertRaises(PinResolutionError) as cm:
                self.resolve(rev)
            self.assertIn(why, str(cm.exception))

    def test_abbreviated_prefix_that_is_unknown_or_not_a_commit_fails(self):
        tree = git(self.repo, "rev-parse", "HEAD^{tree}")
        for rev in ("0000000", tree[:12]):
            with self.subTest(rev=rev), self.assertRaises(PinResolutionError):
                resolve_commit(rev, local=self.repo)

    def test_unreachable_remote_fails(self):
        with self.assertRaises(PinResolutionError) as cm:
            resolve_commit("main", source=str(Path(self.tmp.name) / "missing"))
        self.assertIn("ls-remote", str(cm.exception))

    # test_must_show 4 and 5 through init: one resolved commit everywhere; nothing written on failure
    def _init(self, selected):
        d = Path(tempfile.mkdtemp())
        (d / "m.py").write_text("x = 1\n")
        with mock.patch.object(I, "resolve_install_ref", return_value=(selected, None)), \
                mock.patch.object(I, "resolve_commit", self.resolve):
            return d, init(d, owner="t", hooks=True)

    def test_init_writes_the_resolved_commit_wherever_it_repeats_the_pin(self):
        for selected, want in (("v9.9.9", self.c1), ("main", self.c2), (self.c2, self.c2)):
            with self.subTest(selected=selected):
                d, rep = self._init(selected)
                ci = (d / ".aec/snippets/aec-ci.yml").read_text()
                self.assertIn(f"Telosmith.git@{want}\"", ci)
                self.assertNotIn("@main", ci)
                self.assertIn(want, rep["next_steps"])
                for line in rep["next_steps"].splitlines():
                    if "pip install" in line:
                        self.assertIn(f"@{want}", line)

    def test_init_writes_nothing_when_the_commit_cannot_be_established(self):
        for selected in ("nope", "both"):
            with self.subTest(selected=selected):
                d = Path(tempfile.mkdtemp())
                (d / "m.py").write_text("x = 1\n")
                with mock.patch.object(I, "resolve_install_ref", return_value=(selected, None)), \
                        mock.patch.object(I, "resolve_commit", self.resolve), \
                        self.assertRaises(PinResolutionError) as cm:
                    init(d, owner="t", hooks=True)
                self.assertIn("--no-hooks", str(cm.exception))
                self.assertFalse((d / ".aec").exists())

    def test_cli_reports_the_diagnostic_and_exits_nonzero(self):
        from aec.__main__ import main
        d = Path(tempfile.mkdtemp())
        (d / "m.py").write_text("x = 1\n")
        with mock.patch.object(I, "resolve_install_ref", return_value=("nope", None)), \
                mock.patch.object(I, "resolve_commit", self.resolve), \
                mock.patch("sys.stderr") as err, self.assertRaises(SystemExit) as cm:
            main(["init", str(d), "--owner", "t", "--hooks"])
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("no tag or branch", "".join(c.args[0] for c in err.write.call_args_list))
        self.assertFalse((d / ".aec").exists())

    def test_no_hooks_needs_no_resolution(self):
        d = Path(tempfile.mkdtemp())
        (d / "m.py").write_text("x = 1\n")
        with mock.patch.object(I, "resolve_commit", side_effect=AssertionError("resolved")):
            rep = init(d, owner="t", hooks=False)
        self.assertIn(".aec/records.jsonl", rep["created"])


if __name__ == "__main__":
    unittest.main()
