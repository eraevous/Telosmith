"""`aec pin-check` (src/aec/pin.py): the equality check AEC-R-hook-line-pin-gate@1 asks the line hook to enforce.

Kate's test lines for that record, as far as they concern the check itself: matching versions pass; a mismatch,
a missing or unreadable pin, and an indeterminate local version fail (exit 1, with a diagnostic). Her round-4
records add: AEC-R-pin-check-consensus@1 (full 40-character commit pins only; abbreviated, tag and `main` pins
fail; a conflicting second pin is never ignored), AEC-R-pin-check-local-identity@1 (exact commit equality; a
matching requested tag is not enough) and AEC-R-pin-check-source-clean@1 (staged, unstaged and non-ignored
untracked files make a checkout dirty; ignored artefacts alone do not). Her round-6 AEC-R-pin-check-source-clean@2
adds ignored importables and this interpreter's bytecode caches; Codex's security review of 11af34e adds that
commented pins are not read and variable-built installs fail. Wiring the check
into the line launcher, and "a blocked replacement leaves settings unchanged", belong to the PR that does the
wiring, after Telosmith#89 merges.
"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aec import pin  # noqa: E402
from aec.__main__ import main  # noqa: E402

SHA = "03f85ef" + "0" * 33
OTHER = "1dc99bd" + "1" * 33
WF = 'jobs:\n  aec:\n    steps:\n      - run: pip install "git+https://github.com/eraevous/Telosmith.git@{ref}"\n'


def repo(workflow_ref=None, upstream=None, raw_upstream=None):
    d = Path(tempfile.mkdtemp())
    if workflow_ref is not None:
        (d / ".github" / "workflows").mkdir(parents=True)
        (d / ".github" / "workflows" / "aec.yml").write_text(WF.format(ref=workflow_ref))
    if upstream is not None or raw_upstream is not None:
        (d / "tools").mkdir()
        (d / "tools" / "aec_upstream.json").write_text(
            raw_upstream if raw_upstream is not None else json.dumps({"commit": upstream}))
    return d


def local(commit=SHA):
    return {"commit": commit, "how": "test"}


def git_repo():
    d = Path(tempfile.mkdtemp())
    run = lambda *a: subprocess.run(["git", "-C", str(d), *a], capture_output=True, check=True)  # noqa: E731
    run("init", "-q")
    (d / ".gitignore").write_text("build/\n__pycache__/\n*.so\n*.py[cod]\nnotes.log\n")
    (d / "aec").mkdir()
    (d / "aec" / "records.py").write_text("")
    run("add", ".")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
    return d, run


class PinCheck(unittest.TestCase):
    def test_matching_commit_passes(self):
        self.assertIn("matches", pin.check(repo(SHA), local()))

    def test_abbreviated_pin_fails(self):
        # AEC-R-pin-check-consensus@1: offline, a prefix does not establish repository-wide uniqueness.
        for where in ("workflow", "upstream"):
            d = repo(SHA[:12]) if where == "workflow" else repo(upstream=SHA[:12])
            with self.assertRaisesRegex(pin.PinError, "abbreviated commit"):
                pin.check(d, local())

    def test_both_pin_sources_agreeing_pass(self):
        self.assertIn("matches", pin.check(repo(SHA, upstream=SHA), local()))

    def test_upstream_file_alone_passes(self):
        self.assertIn("matches", pin.check(repo(upstream=SHA), local()))

    def test_mismatch_fails(self):
        with self.assertRaisesRegex(pin.PinError, "but CI pins"):
            pin.check(repo(OTHER), local())

    def test_pins_that_disagree_fail(self):
        with self.assertRaisesRegex(pin.PinError, "pins disagree"):
            pin.check(repo(SHA, upstream=OTHER), local())
        # A conflicting second pin is not ignored, whichever pin the local aec matches.
        with self.assertRaisesRegex(pin.PinError, "pins disagree"):
            pin.check(repo(SHA, upstream=OTHER), local(OTHER))

    def test_malformed_second_pin_is_not_ignored(self):
        with self.assertRaisesRegex(pin.PinError, "not a commit"):
            pin.check(repo(SHA, upstream="v0.6.0"), local())

    def test_whole_revision_is_captured(self):
        # Codex P2 on #90 (5b8ef40): `@<sha>+hotfix` is a valid branch name, so it must fail rather than pass as
        # the SHA it starts with. pip's `#egg=` fragment is not part of the revision.
        for suffix in ("+hotfix", "-rc", ".1", "/x"):
            with self.assertRaisesRegex(pin.PinError, "not a commit"):
                pin.check(repo(SHA + suffix), local())
        self.assertEqual(pin.find_pins(repo(SHA + "#egg=aec"))[0][1], SHA)
        self.assertIn("matches", pin.check(repo(SHA + "#egg=aec"), local()))

    def test_missing_pin_fails(self):
        with self.assertRaisesRegex(pin.PinError, "no Telosmith pin"):
            pin.check(repo(), local())

    def test_unreadable_pin_fails(self):
        with self.assertRaisesRegex(pin.PinError, "cannot read"):
            pin.check(repo(raw_upstream="{not json"), local())
        with self.assertRaisesRegex(pin.PinError, "has no commit"):
            pin.check(repo(raw_upstream='{"repo": "x"}'), local())

    def test_indeterminate_local_fails(self):
        with self.assertRaisesRegex(pin.PinError, "indeterminate"):
            pin.check(repo(SHA), None)

    def test_tag_pin_fails_even_with_matching_requested_revision(self):
        # AEC-R-pin-check-local-identity@1: a recorded requested tag does not establish commit equality.
        for ref in ("v0.6.0", "v1.2"):
            with self.assertRaisesRegex(pin.PinError, "not a commit"):
                pin.check(repo(ref), dict(local(), requested=ref))

    def test_branch_pins_fail(self):
        # Codex P2 on #90, then AEC-R-pin-check-consensus@1: main or any branch is mutable.
        for ref in ("main", "aec/pin-check", "release"):
            with self.assertRaisesRegex(pin.PinError, "not a commit"):
                pin.check(repo(ref), local())

    def test_clean_checkout_is_not_dirty(self):
        d, _ = git_repo()
        self.assertFalse(pin._dirty(d / "aec"))

    def test_ignored_artefacts_alone_do_not_make_checkout_dirty(self):
        d, _ = git_repo()
        (d / "aec" / "__pycache__").mkdir()
        # A cache for another interpreter's tag cannot be loaded by this one (AEC-R-pin-check-source-clean@2).
        (d / "aec" / "__pycache__" / "records.cpython-29.pyc").write_bytes(b"")
        (d / "build").mkdir()
        (d / "build" / "out.txt").write_text("x")
        self.assertFalse(pin._dirty(d / "aec"))

    def test_ignored_importable_files_make_checkout_dirty(self):
        # Kate, round 5 on #90: an ignored native extension or sourceless bytecode inside the package can be
        # imported ahead of committed code. Each is checked on its own, and the check deletes or changes nothing.
        import importlib.machinery
        ext = importlib.machinery.EXTENSION_SUFFIXES[0]
        for rel in (f"aec/records{ext}", "aec/gone.pyc", f"aec/build/fast{ext}"):
            d, _ = git_repo()
            f = d / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"x")
            self.assertTrue(pin._dirty(d / "aec"), rel)
            self.assertEqual(pin._ignored_importables(d / "aec"), [rel])
            self.assertEqual(f.read_bytes(), b"x")

    def test_ignored_non_importable_files_do_not_make_checkout_dirty(self):
        d, _ = git_repo()
        (d / "aec" / "notes.log").write_text("x")
        self.assertFalse(pin._dirty(d / "aec"))

    def test_unstaged_change_makes_checkout_dirty(self):
        d, _ = git_repo()
        (d / "aec" / "records.py").write_text("x = 1\n")
        self.assertTrue(pin._dirty(d / "aec"))

    def test_staged_change_makes_checkout_dirty(self):
        d, run = git_repo()
        (d / "aec" / "records.py").write_text("x = 1\n")
        run("add", "aec/records.py")
        self.assertTrue(pin._dirty(d / "aec"))

    def test_untracked_files_make_checkout_dirty(self):
        # Codex P2 on #90: an untracked package can shadow a committed module. Kate's source-clean record
        # extends this to any non-ignored untracked file in the checkout.
        d, _ = git_repo()
        (d / "aec" / "records").mkdir()
        (d / "aec" / "records" / "__init__.py").write_text("")
        self.assertTrue(pin._dirty(d / "aec"))
        d, _ = git_repo()
        (d / "notes.txt").write_text("x")
        self.assertTrue(pin._dirty(d / "aec"))

    def test_bytecode_cache_for_this_interpreter_makes_checkout_dirty(self):
        # Kate's AEC-R-pin-check-source-clean@2 and Codex security P2 on 11af34e: an existing cache can load in
        # place of its source (same mtime and size, or an unchecked-hash pyc), so it fails, naming the path,
        # and the check leaves it in place.
        tag = sys.implementation.cache_tag
        for name in (f"records.{tag}.pyc", f"records.{tag}.opt-1.pyc"):
            d, _ = git_repo()
            f = d / "aec" / "__pycache__" / name
            f.parent.mkdir()
            f.write_bytes(b"x")
            why = pin._dirty(d / "aec")
            self.assertTrue(why, name)
            self.assertIn(f"aec/__pycache__/{name}", why)
            self.assertIn("PYTHONDONTWRITEBYTECODE", why)
            self.assertEqual(f.read_bytes(), b"x")

    def test_pycache_prefix_is_unsupported(self):
        # With a cache prefix, caches live outside the checkout, where the check cannot inspect them.
        d, _ = git_repo()
        saved = sys.pycache_prefix
        sys.pycache_prefix = str(d / "elsewhere")
        try:
            self.assertIn("pycache_prefix", pin._dirty(d / "aec"))
        finally:
            sys.pycache_prefix = saved

    def test_dirty_reason_names_the_path(self):
        d, _ = git_repo()
        (d / "notes.txt").write_text("x")
        self.assertIn("notes.txt", pin._dirty(d / "aec"))

    def test_commented_pin_is_not_read(self):
        # Codex security P2 on 11af34e: a comment holding the pinned SHA must not stand in for an executed
        # install of a mutable ref kept in a variable.
        d = repo()
        (d / ".github" / "workflows").mkdir(parents=True)
        (d / ".github" / "workflows" / "aec.yml").write_text(
            "env:\n  AEC_URL: git+https://github.com/eraevous/Telosmith.git\njobs:\n  aec:\n    steps:\n"
            f"      # pinned: git+https://github.com/eraevous/Telosmith.git@{SHA}\n"
            '      - run: pip install "$AEC_URL@main"\n')
        with self.assertRaisesRegex(pin.PinError, "aec.yml:2 .*without a static"):
            pin.check(d, local())

    def test_display_text_is_not_a_pin(self):
        # Codex P2 on ec563ad: a workflow or step name mentioning an older pin is not an install.
        d = repo(SHA)
        text = (d / ".github" / "workflows" / "aec.yml").read_text()
        (d / ".github" / "workflows" / "aec.yml").write_text(
            f"name: Telosmith git+https://github.com/eraevous/Telosmith.git@{OTHER}\n" + text
            + f"      - name: Replaces git+https://github.com/eraevous/Telosmith.git@{OTHER}\n"
            + "        description: was git+https://github.com/eraevous/Telosmith.git\n"
            + f'        run: pip install "git+https://github.com/eraevous/Telosmith.git@{SHA}"\n')
        self.assertIn("matches", pin.check(d, local()))

    def test_comment_alone_is_no_pin(self):
        d = repo()
        (d / ".github" / "workflows").mkdir(parents=True)
        (d / ".github" / "workflows" / "aec.yml").write_text(
            f"# git+https://github.com/eraevous/Telosmith.git@{SHA}\njobs: {{}}\n")
        with self.assertRaisesRegex(pin.PinError, "no Telosmith pin"):
            pin.check(d, local())

    def test_install_from_variable_fails(self):
        for line in ('pip install "$AEC_URL@main"', "python -m pip install ${{ vars.AEC }}@main",
                     'pip install "git+$TELOSMITH"'):
            d = repo(SHA)
            with open(d / ".github" / "workflows" / "aec.yml", "a") as f:
                f.write(f"      - run: {line}\n")
            with self.assertRaisesRegex(pin.PinError, "variable|static", msg=line):
                pin.check(d, local())

    def test_unrelated_variables_in_pip_lines_pass(self):
        d = repo(SHA)
        with open(d / ".github" / "workflows" / "aec.yml", "a") as f:
            f.write('      - run: pip install -r "$GITHUB_WORKSPACE/requirements.txt"\n')
        self.assertIn("matches", pin.check(d, local()))

    def test_cli_exit_codes(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main(["pin-check", str(repo())]), 1)
        self.assertIn("Telosmith pin check: no Telosmith pin", err.getvalue())

    def test_cli_on_this_checkout_compares_its_head(self):
        # This repository has no Telosmith pin of its own, so the CLI fails on "no pin" whatever the checkout's
        # state. A pin at its own HEAD passes when the checkout qualifies; when it doesn't (a change, or bytecode
        # caches some earlier run wrote: AEC-R-pin-check-source-clean@2), the refusal carries the reason. No skip:
        # either branch is asserted.
        root = Path(__file__).resolve().parents[1]
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        found, why = pin.local_identity()
        if found is None:
            self.assertTrue(why)
            with self.assertRaisesRegex(pin.PinError, "indeterminate"):
                pin.check(repo(head or SHA))
            return
        if found["how"] == "clean source checkout":
            self.assertEqual(found["commit"], head)
        self.assertIn("matches", pin.check(repo(found["commit"])))

if __name__ == "__main__":
    unittest.main()
