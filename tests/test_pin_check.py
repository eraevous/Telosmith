"""`aec pin-check` (src/aec/pin.py): the equality check AEC-R-hook-line-pin-gate@1 asks the line hook to enforce.

Kate's test lines for that record, as far as they concern the check itself: matching versions pass; a mismatch,
a missing or unreadable pin, and an indeterminate local version fail (exit 1, with a diagnostic). Wiring the check
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


def local(commit=SHA, requested=None):
    return {"commit": commit, "requested": requested, "how": "test"}


class PinCheck(unittest.TestCase):
    def test_matching_commit_passes(self):
        self.assertIn("matches", pin.check(repo(SHA), local()))

    def test_short_pin_prefix_passes(self):
        self.assertIn("matches", pin.check(repo(SHA[:12]), local()))

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

    def test_tag_pin_needs_matching_requested_revision(self):
        self.assertIn("installed from v0.6.0", pin.check(repo("v0.6.0"), local(requested="v0.6.0")))
        with self.assertRaisesRegex(pin.PinError, "cannot be established offline"):
            pin.check(repo("v0.6.0"), local())

    def test_unpinned_main_fails(self):
        with self.assertRaisesRegex(pin.PinError, "not a commit"):
            pin.check(repo("main"), local(requested=None))

    def test_cli_exit_codes(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main(["pin-check", str(repo())]), 1)
        self.assertIn("Telosmith pin check: no Telosmith pin", err.getvalue())

    def test_cli_on_this_checkout_compares_its_head(self):
        # This repository has no Telosmith pin of its own, so the CLI fails on "no pin" whatever the checkout's
        # state; a pin at its own HEAD passes when the checkout is clean, and is indeterminate when it is dirty.
        root = Path(__file__).resolve().parents[1]
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        found = pin.local_version()
        if not head or found is None:
            self.skipTest("not a clean source checkout")
        self.assertEqual(found["commit"], head)
        self.assertIn("matches", pin.check(repo(head)))


if __name__ == "__main__":
    unittest.main()
