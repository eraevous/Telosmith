"""`aec init --hook-style line` writes the pin file the line hook needs.

Kate's AEC-R-init-line-pin-bootstrap@1, AEC-R-init-pin-preservation@1 and AEC-R-init-unresolved-pin-no-write@1
(independent); AEC-R-init-writes-pin-file-impl@2 (implementer).

`aec pin-check` compares the installed aec against the commit in tools/aec_upstream.json, and the one-line
hook does too once its launcher has the pre-import pin gate (#92; AEC-R-hook-line-pin-gate@1,
AEC-D-pin-check-scope@1). Neither works without that file, so a repository set up with the line style needs one. init writes it with the commit the CI snippet pins, keeps any existing
file, and never writes through a symlinked tools/ directory. The inline default writes no pin file.
Commit resolution is mocked: these tests touch no network."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import aec.init as I  # noqa: E402
from aec.init import init  # noqa: E402
from aec.pin import PinError, read_pin  # noqa: E402
from _platform import readlink  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER = "fedcba9876543210fedcba9876543210fedcba98"
PIN = Path("tools") / "aec_upstream.json"


class InitPinFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()
        (self.root / "m.py").write_text("x = 1\n")
        self.outside = Path(self._tmp.name) / "outside"
        self.outside.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _init(self, **kwargs):
        with mock.patch.object(I, "resolve_install_ref", return_value=(SHA, None)), \
                mock.patch.object(I, "resolve_commit", side_effect=lambda rev, **_: rev):
            return init(self.root, owner="t", hooks=True, **kwargs)

    def test_line_style_writes_a_pin_that_pin_check_reads_and_the_ci_snippet_matches(self):
        rep = self._init(hook_style="line")
        self.assertIn("tools/aec_upstream.json", rep["created"])
        self.assertEqual(read_pin(self.root), SHA)
        data = json.loads((self.root / PIN).read_text())
        self.assertEqual(data["repo"], "https://github.com/eraevous/Telosmith")
        self.assertIn(f"Telosmith.git@{SHA}\"", (self.root / ".aec/snippets/aec-ci.yml").read_text())
        self.assertIn(f"Commit tools/aec_upstream.json: it pins Telosmith commit {SHA}", rep["next_steps"])
        # Copilot on #93: the file and next step must not promise hook enforcement the launcher may not have yet
        for text in (data["_doc"], rep["next_steps"]):
            self.assertIn("pin-check", text)
            self.assertIn("#92", text)

    def test_inline_default_writes_no_pin_file(self):
        for kwargs in ({}, {"hook_style": "inline"}):
            with self.subTest(**kwargs):
                rep = self._init(**kwargs)
                self.assertFalse(os.path.lexists(self.root / "tools"))
                self.assertNotIn("tools/aec_upstream.json", rep["created"])
                self.assertNotIn("aec_upstream.json", rep["next_steps"])

    def test_no_hooks_writes_no_pin_file(self):
        with mock.patch.object(I, "resolve_commit", side_effect=AssertionError("resolved")):
            init(self.root, owner="t", hooks=False, hook_style="line")
        self.assertFalse(os.path.lexists(self.root / "tools"))

    def test_an_existing_pin_is_kept_byte_for_byte_and_the_next_step_says_so(self):
        (self.root / "tools").mkdir()
        before = json.dumps({"commit": OTHER, "note": "mine"})
        (self.root / PIN).write_text(before)
        rep = self._init(hook_style="line")
        self.assertEqual((self.root / PIN).read_text(), before)
        self.assertIn("tools/aec_upstream.json", rep["kept"])
        self.assertNotIn("tools/aec_upstream.json", rep["created"])
        self.assertIn("already existed and was kept", rep["next_steps"])
        self.assertIn(SHA, rep["next_steps"])

    def test_a_dangling_symlink_at_the_pin_path_is_kept_and_its_target_never_created(self):
        (self.root / "tools").mkdir()
        target = self.outside / "planted.json"
        os.symlink(target, self.root / PIN)
        rep = self._init(hook_style="line")
        self.assertFalse(target.exists())
        self.assertTrue((self.root / PIN).is_symlink())
        self.assertIn("tools/aec_upstream.json", rep["kept"])
        with self.assertRaises(PinError):      # pin-check still refuses a symlinked pin
            read_pin(self.root)

    def test_a_live_symlink_at_the_pin_path_is_kept_and_its_target_unchanged(self):  # Kate, round 13
        (self.root / "tools").mkdir()
        target = self.outside / "theirs.json"
        theirs = json.dumps({"commit": OTHER})
        target.write_text(theirs)
        os.symlink(target, self.root / PIN)
        rep = self._init(hook_style="line")
        self.assertEqual(target.read_text(), theirs)
        self.assertEqual(readlink(self.root / PIN), str(target))
        self.assertIn("tools/aec_upstream.json", rep["kept"])
        self.assertIn("already existed and was kept", rep["next_steps"])

    def test_a_symlinked_tools_directory_is_not_written_through(self):
        os.symlink(self.outside, self.root / "tools")
        rep = self._init(hook_style="line")
        self.assertEqual(list(self.outside.iterdir()), [])
        self.assertNotIn("tools/aec_upstream.json", rep["created"] + rep["kept"])
        self.assertIn("was not written: tools is a symlink or not a directory", rep["next_steps"])

    def test_a_file_named_tools_is_left_alone(self):
        (self.root / "tools").write_text("not a directory\n")
        rep = self._init(hook_style="line")
        self.assertEqual((self.root / "tools").read_text(), "not a directory\n")
        self.assertIn("was not written", rep["next_steps"])

    def test_a_second_init_keeps_the_first_pin(self):
        self._init(hook_style="line")
        first = (self.root / PIN).read_text()
        with mock.patch.object(I, "resolve_install_ref", return_value=(OTHER, None)), \
                mock.patch.object(I, "resolve_commit", side_effect=lambda rev, **_: rev):
            rep = init(self.root, owner="t", hooks=True, hook_style="line")
        self.assertEqual((self.root / PIN).read_text(), first)
        self.assertIn("tools/aec_upstream.json", rep["kept"])

    def test_nothing_is_written_when_the_commit_cannot_be_established(self):
        with mock.patch.object(I, "resolve_install_ref", return_value=("nope", None)), \
                mock.patch.object(I, "resolve_commit", side_effect=I.PinResolutionError("cannot pin")), \
                self.assertRaises(I.PinResolutionError):
            init(self.root, owner="t", hooks=True, hook_style="line")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["m.py"])   # Kate, round 13: no write at all
        self.assertEqual((self.root / "m.py").read_text(), "x = 1\n")


if __name__ == "__main__":
    unittest.main()
