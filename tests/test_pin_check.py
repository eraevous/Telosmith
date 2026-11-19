"""`aec pin-check` (src/aec/pin.py) under the owner decision AEC-D-pin-check-scope@1 (Zach, 2026-11-18, #90):
the pin comes only from tools/aec_upstream.json, and only a pip install from git with a recorded commit counts as
the local version.

Kept from Kate's records: a matching full commit passes; a mismatch, a missing or unreadable pin, an abbreviated,
tag or branch pin, and an indeterminate local version fail (exit 1, with a diagnostic). Workflow files are no
longer read, so the workflow cases Codex and Copilot raised are tested as "ignored" rather than parsed.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aec import pin  # noqa: E402
from aec.__main__ import main  # noqa: E402

SHA = "03f85ef" + "0" * 33
OTHER = "1dc99bd" + "1" * 33


def repo(upstream=None, raw_upstream=None, workflow=None):
    d = Path(tempfile.mkdtemp())
    if upstream is not None or raw_upstream is not None:
        (d / "tools").mkdir()
        (d / "tools" / "aec_upstream.json").write_text(
            raw_upstream if raw_upstream is not None else json.dumps({"commit": upstream}))
    if workflow is not None:
        (d / ".github" / "workflows").mkdir(parents=True)
        (d / ".github" / "workflows" / "aec.yml").write_text(workflow)
    return d


def local(commit=SHA):
    return {"commit": commit, "how": "test"}


class PinCheck(unittest.TestCase):
    def test_matching_commit_passes(self):
        self.assertIn("matches", pin.check(repo(SHA), local()))

    def test_mismatch_fails(self):
        with self.assertRaisesRegex(pin.PinError, "but tools/aec_upstream.json pins"):
            pin.check(repo(OTHER), local())

    def test_abbreviated_tag_and_branch_pins_fail(self):
        with self.assertRaisesRegex(pin.PinError, "abbreviated commit"):
            pin.check(repo(SHA[:12]), local())
        for ref in ("v0.6.0", "main", "aec/pin-check", SHA + "+hotfix"):
            with self.assertRaisesRegex(pin.PinError, "not a commit", msg=ref):
                pin.check(repo(ref), local())

    def test_missing_pin_fails(self):
        with self.assertRaisesRegex(pin.PinError, "no Telosmith pin"):
            pin.check(repo(), local())

    def test_unreadable_pin_fails(self):
        with self.assertRaisesRegex(pin.PinError, "cannot read"):
            pin.check(repo(raw_upstream="{not json"), local())
        for raw in ('{"repo": "x"}', "[1]", '"x"'):
            with self.assertRaisesRegex(pin.PinError, "has no commit", msg=raw):
                pin.check(repo(raw_upstream=raw), local())

    def test_symlinked_pin_fails(self):
        # Copilot on #90 (0ec4f9c): a dangling symlink made exists() false, so the pin was silently ignored.
        for dangling in (True, False):
            d = repo()
            (d / "tools").mkdir()
            target = d / "elsewhere.json"
            if not dangling:
                target.write_text(json.dumps({"commit": SHA}))
            os.symlink(target, d / "tools" / "aec_upstream.json")
            with self.assertRaisesRegex(pin.PinError, "symlink"):
                pin.check(d, local())

    def test_pin_path_that_is_a_directory_fails(self):
        d = repo()
        (d / "tools" / "aec_upstream.json").mkdir(parents=True)
        with self.assertRaisesRegex(pin.PinError, "not a regular file"):
            pin.check(d, local())

    def test_workflows_are_not_read(self):
        # AEC-D-pin-check-scope@1: workflow text is neither a pin source nor a way to veto the file's pin. The
        # cases Codex and Copilot raised on #90 change nothing here.
        steered = "\n".join([
            f"# git+https://github.com/eraevous/Telosmith.git@{OTHER}",
            '      - run: echo " # x"; pip install "git+https://github.com/eraevous/Telosmith.git@main"',
            '      - run: |\n          name: || pip install "git+https://github.com/eraevous/Telosmith.git@main"',
            '      - run: pip install "$AEC_URL"',
            f'    env: {{OLD: "git+https://github.com/eraevous/Telosmith.git@{OTHER}"}}', ""])
        self.assertIn("matches", pin.check(repo(SHA, workflow=steered), local()))
        with self.assertRaisesRegex(pin.PinError, "no Telosmith pin"):
            pin.check(repo(workflow=steered), local())

    def test_indeterminate_local_fails(self):
        with self.assertRaisesRegex(pin.PinError, "indeterminate"):
            pin.check(repo(SHA), None)

    def test_source_checkout_does_not_qualify(self):
        # AEC-D-pin-check-scope@1 (Codex security P2 on ec563ad): this test suite runs aec from the source tree,
        # which is not a pip install from git, so its identity is indeterminate whatever the checkout's state.
        found, why = pin.local_identity()
        if found is not None:  # running against a pip install from git (e.g. an installed-package CI job)
            self.assertEqual(found["how"], "pip install from git")
            return
        self.assertIn("source checkout", why)
        with self.assertRaisesRegex(pin.PinError, "indeterminate"):
            pin.check(repo(SHA))

    def test_cli_exit_codes(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main(["pin-check", str(repo())]), 1)
        self.assertIn("Telosmith pin check: no Telosmith pin", err.getvalue())


class _FakeDist:
    """A PEP 610 distribution for `telosmith`: direct_url.json text and where its `aec` package sits."""

    def __init__(self, direct_url, where=None):
        self.direct_url = direct_url
        self.where = where if where is not None else Path(pin.__file__).resolve().parent

    def locate_file(self, name):
        return self.where

    def read_text(self, name):
        return self.direct_url if name == "direct_url.json" else None


def git_install(commit=SHA, **extra):
    data = {"url": "https://github.com/eraevous/Telosmith.git",
            "vcs_info": {"vcs": "git", "commit_id": commit, "requested_revision": commit}}
    data.update(extra)
    return json.dumps(data)


class InstalledIdentity(unittest.TestCase):
    """check() without the `local` override, over deterministic PEP 610 fixtures (Copilot on #90, 14c200f;
    Kate's AEC-R-pin-check-local-identity@2)."""

    def run_check(self, direct_url, where=None, pinned=SHA):
        from unittest import mock
        with mock.patch("importlib.metadata.distribution", return_value=_FakeDist(direct_url, where)):
            return pin.check(repo(pinned))

    def test_installed_git_commit_matching_the_pin_passes(self):
        self.assertIn("pip install from git", self.run_check(git_install()))

    def test_installed_git_commit_differing_from_the_pin_fails(self):
        with self.assertRaisesRegex(pin.PinError, "but tools/aec_upstream.json pins"):
            self.run_check(git_install(OTHER))

    def test_non_git_vcs_does_not_qualify(self):
        hg = json.dumps({"url": "https://hg.example/telosmith", "vcs_info": {"vcs": "hg", "commit_id": SHA}})
        for text in (hg, json.dumps({"url": "x", "vcs_info": {"commit_id": SHA}})):
            with self.subTest(text=text), self.assertRaisesRegex(pin.PinError, "indeterminate"):
                self.run_check(text)

    def test_editable_install_does_not_qualify_even_with_matching_git_metadata(self):
        with self.assertRaisesRegex(pin.PinError, "indeterminate"):
            self.run_check(git_install(dir_info={"editable": True}))

    def test_unrelated_install_location_does_not_qualify(self):
        with self.assertRaisesRegex(pin.PinError, "indeterminate"):
            self.run_check(git_install(), where=Path(tempfile.mkdtemp()) / "aec")

    def test_missing_malformed_or_commitless_metadata_does_not_qualify(self):
        cases = [None, "", "{not json", "[]", json.dumps({"url": "x"}),
                 json.dumps({"url": "x", "vcs_info": {"vcs": "git"}}),
                 json.dumps({"url": "x", "vcs_info": {"vcs": "git", "commit_id": SHA[:12]}}),
                 json.dumps({"url": "x", "vcs_info": {"vcs": "git", "commit_id": 7}})]
        for text in cases:
            with self.subTest(text=text), self.assertRaisesRegex(pin.PinError, "indeterminate"):
                self.run_check(text)


if __name__ == "__main__":
    unittest.main()
