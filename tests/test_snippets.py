"""aec snippets: the hook and CI snippets rendered from .aec/config.json (DEC-256 item 3).

AEC-R-snippets-render-impl@1 (implementer). `show` prints exactly what `aec init` writes for the same settings;
`check` compares committed copies under .aec/snippets/ with a fresh render. Commit resolution is never needed
(`--ref` or the pin file); init's resolution is mocked. These tests touch no network."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import aec.init as I  # noqa: E402
from aec import config, snippets  # noqa: E402
from aec.__main__ import main  # noqa: E402
from aec.init import init  # noqa: E402
from aec.pin import UPSTREAM_FILE  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER = "fedcba9876543210fedcba9876543210fedcba98"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "repo"
        (self.root / ".aec").mkdir(parents=True)
        (self.root / ".git").mkdir()
        (self.root / "m.py").write_text("x = 1\n")

    def tearDown(self):
        self._tmp.cleanup()

    def cfg(self, init_section):
        (self.root / config.CONFIG_PATH).write_text(json.dumps({"init": init_section}), encoding="utf-8")

    def pin(self, commit=SHA):
        (self.root / "tools").mkdir(exist_ok=True)
        (self.root / UPSTREAM_FILE).write_text(json.dumps({"commit": commit}), encoding="utf-8")

    def init(self, **kw):
        with mock.patch.object(I, "resolve_install_ref", return_value=(SHA, None)), \
                mock.patch.object(I, "resolve_commit", side_effect=lambda rev, **_: rev):
            return init(self.root, owner="t", hooks=True, **kw)


class Show(Base):
    def test_hook_defaults_to_the_inline_settings(self):
        code, out, _ = run(["snippets", "show", "hook", "--repo", str(self.root)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), I.HOOK)

    def test_hook_follows_the_configured_style(self):
        self.cfg({"hook_style": "line"})
        self.assertEqual(json.loads(snippets.render(self.root, "hook")), I.HOOK_LINE)

    def test_ci_uses_ref_and_configured_name(self):
        self.cfg({"ci_name": "gov"})
        code, out, _ = run(["snippets", "show", "ci", "--repo", str(self.root), "--ref", SHA])
        self.assertEqual(code, 0)
        self.assertEqual(out, I.ci_snippet(SHA, "gov"))

    def test_ci_reads_the_pin_file_and_ref_wins_over_it(self):
        self.pin(SHA)
        self.assertEqual(snippets.render(self.root, "ci"), I.ci_snippet(SHA))
        self.assertEqual(snippets.render(self.root, "ci", OTHER), I.ci_snippet(OTHER))

    def test_ci_without_a_commit_fails_and_says_what_to_supply(self):
        code, out, err = run(["snippets", "show", "ci", "--repo", str(self.root)])
        self.assertEqual((code, out), (1, ""))
        self.assertIn("--ref", err)

    def test_short_or_symbolic_refs_are_refused(self):
        for ref in ("main", SHA[:12], "v0.6.0", SHA.upper()):
            code, _, err = run(["snippets", "show", "ci", "--repo", str(self.root), "--ref", ref])
            self.assertEqual(code, 1, ref)
            self.assertIn("full 40-character", err)

    def test_a_symlinked_tools_directory_is_not_read(self):
        outside = Path(self._tmp.name) / "outside"
        (outside).mkdir()
        (outside / "aec_upstream.json").write_text(json.dumps({"commit": SHA}))
        os.symlink(outside, self.root / "tools")
        with self.assertRaises(snippets.SnippetError):
            snippets.render(self.root, "ci")

    def test_only_the_repositorys_own_config_counts(self):
        (self.root / config.CONFIG_PATH).write_text(json.dumps({"init": {"hook_style": "line"}}))
        inner = self.root / "inner"
        (inner / ".aec").mkdir(parents=True)
        self.assertEqual(json.loads(snippets.render(inner, "hook")), I.HOOK)  # no config of its own: defaults

    def test_an_invalid_config_fails(self):
        self.cfg({"hook_style": "loud"})
        code, _, err = run(["snippets", "show", "hook", "--repo", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("init.hook_style", err)

    def test_show_matches_what_init_writes_for_each_style(self):
        for style in ("inline", "line"):
            with self.subTest(style=style):
                self.tearDown(); self.setUp()
                self.init(hook_style=style, ci_name="gov")
                folder = self.root / ".aec" / "snippets"
                self.cfg({"hook_style": style, "ci_name": "gov"})
                self.assertEqual((folder / "claude-settings.json").read_text(), snippets.render(self.root, "hook"))
                self.assertEqual((folder / "gov-ci.yml").read_text(), snippets.render(self.root, "ci", SHA))


class Check(Base):
    def copies(self, style="inline", name="aec"):
        folder = self.root / ".aec" / "snippets"
        folder.mkdir()
        (folder / "claude-settings.json").write_text(json.dumps(I.HOOK_STYLES[style], indent=2) + "\n")
        (folder / f"{name}-ci.yml").write_text(I.ci_snippet(SHA, name))
        return folder

    def test_no_copies_is_ok(self):
        code, out, _ = run(["snippets", "check", "--repo", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("nothing to check", out)

    def test_current_copies_pass(self):
        self.copies()
        self.pin()
        code, out, _ = run(["snippets", "check", "--repo", str(self.root)])
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count(": current"), 2)

    def test_hook_copy_is_compared_as_json_not_layout(self):
        folder = self.copies()
        (folder / "claude-settings.json").write_text(json.dumps(I.HOOK))  # one line, same content
        ok, bad = snippets.check(self.root, SHA)
        self.assertEqual(bad, [])

    def test_style_change_makes_the_hook_copy_stale(self):
        self.copies("inline")
        self.cfg({"hook_style": "line"})
        code, out, _ = run(["snippets", "check", "--repo", str(self.root), "--ref", SHA])
        self.assertEqual(code, 1)
        self.assertIn("claude-settings.json: stale", out)

    def test_moved_pin_makes_the_ci_copy_stale(self):
        self.copies()
        self.pin(OTHER)
        ok, bad = snippets.check(self.root)
        self.assertEqual(len(bad), 1)
        self.assertIn("aec-ci.yml: stale", bad[0])

    def test_ci_copy_without_a_commit_is_a_problem_not_a_pass(self):
        self.copies()
        ok, bad = snippets.check(self.root)
        self.assertTrue(any("no commit to compare" in b for b in bad))

    def test_ci_copy_under_another_name_is_reported(self):
        self.copies(name="old")
        ok, bad = snippets.check(self.root, SHA)
        self.assertTrue(any("old-ci.yml" in b and "init.ci_name" in b for b in bad))

    def test_unrelated_files_are_listed_not_failed(self):
        folder = self.copies()
        (folder / "notes.txt").write_text("hi")
        ok, bad = snippets.check(self.root, SHA)
        self.assertEqual(bad, [])
        self.assertTrue(any("notes.txt: not a Telosmith snippet" in o for o in ok))

    def test_symlinks_are_not_read(self):
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        (outside / "claude-settings.json").write_text(json.dumps(I.HOOK))
        folder = self.root / ".aec" / "snippets"
        folder.mkdir()
        os.symlink(outside / "claude-settings.json", folder / "claude-settings.json")
        ok, bad = snippets.check(self.root, SHA)
        self.assertTrue(any("not a regular file" in b for b in bad))
        os.unlink(folder / "claude-settings.json"); folder.rmdir()
        os.symlink(outside, folder)
        ok, bad = snippets.check(self.root, SHA)
        self.assertEqual(ok, [])
        self.assertTrue(any("symlink" in b for b in bad))

    def test_unrelated_symlinks_and_folders_fail(self):
        # Copilot on #102 (fixed in 22e9b14): an unrelated name was listed as OK before the file-type check
        folder = self.copies()
        outside = Path(self._tmp.name) / "notes-target.txt"
        outside.write_text("hi")
        os.symlink(outside, folder / "notes.txt")
        (folder / "drafts").mkdir()
        ok, bad = snippets.check(self.root, SHA)
        self.assertTrue(any("notes.txt: not a regular file" in b for b in bad))
        self.assertTrue(any("drafts: not a regular file" in b for b in bad))
        self.assertFalse(any("notes.txt" in o or "drafts" in o for o in ok))
        self.assertNotEqual(run(["snippets", "check", "--repo", str(self.root), "--ref", SHA])[0], 0)

    def test_check_writes_nothing(self):
        self.copies()
        before = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*"))
        run(["snippets", "check", "--repo", str(self.root), "--ref", SHA])
        self.assertEqual(sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*")), before)


class SnippetFilesSetting(Base):
    def test_validation(self):
        self.assertEqual(config.validate({"init": {"snippet_files": False}}), ({"init.snippet_files": False}, []))
        for bad in (0, "false", None):
            values, problems = config.validate({"init": {"snippet_files": bad}})
            self.assertTrue(problems and "init.snippet_files" in problems[0], bad)

    def test_default_is_unchanged(self):
        self.assertIs(config.load(self.root).get("init.snippet_files"), True)
        rep = self.init()
        self.assertIn(".aec/snippets/claude-settings.json", rep["created"])

    def test_false_writes_no_copies_and_points_to_show(self):
        rep = self.init(snippet_files=False)
        self.assertFalse((self.root / ".aec" / "snippets").exists())
        self.assertFalse(any("snippets/" in c for c in rep["created"]))
        self.assertIn("aec snippets show hook --hook-style inline", rep["next_steps"])
        self.assertIn(f"aec snippets show ci --ci-name aec --ref {SHA}", rep["next_steps"])
        self.assertNotIn("Copy .aec/snippets", rep["next_steps"])

    def test_cli_init_reads_the_setting(self):
        self.cfg({"snippet_files": False})
        with mock.patch.object(I, "resolve_install_ref", return_value=(SHA, None)), \
                mock.patch.object(I, "resolve_commit", side_effect=lambda rev, **_: rev):
            code, out, _ = run(["init", str(self.root), "--owner", "t", "--hooks"])
        self.assertEqual(code, 0)
        self.assertNotIn("snippets/", out.split("Next steps:")[0])
        self.assertIn("aec snippets show hook", out)

    def test_init_flags_not_in_the_config_reach_the_suggested_commands(self):  # Codex P2 on #102 (3d699cb)
        self.cfg({"snippet_files": False})
        with mock.patch.object(I, "resolve_install_ref", return_value=(SHA, None)), \
                mock.patch.object(I, "resolve_commit", side_effect=lambda rev, **_: rev):
            code, out, _ = run(["init", str(self.root), "--owner", "t", "--hooks", "--hook-style", "line",
                                "--ci-name", "gov"])
        self.assertEqual(code, 0)
        hook_cmd = "aec snippets show hook --hook-style line"
        ci_cmd = f"aec snippets show ci --ci-name gov --ref {SHA}"
        self.assertIn(hook_cmd, out)
        self.assertIn(ci_cmd, out)
        self.assertEqual(json.loads(snippets.render(self.root, "hook", hook_style="line")), I.HOOK_LINE)
        code, ci_out, _ = run(["snippets", "show", "ci", "--repo", str(self.root), "--ci-name", "gov", "--ref", SHA])
        self.assertEqual(ci_out, I.ci_snippet(SHA, "gov"))
        self.assertIn(".github/workflows/gov.yml", out)


class KateRound8(Base):
    """Cases her round-8 records name (AEC-R-snippets-show-ci@1, -check@1, AEC-R-init-snippet-files@1)."""

    def test_an_invalid_ref_does_not_fall_back_to_a_valid_pin(self):
        self.pin(SHA)
        code, out, _ = run(["snippets", "show", "ci", "--repo", str(self.root), "--ref", "main"])
        self.assertEqual((code, out), (1, ""))

    def test_show_and_check_work_with_the_network_blocked(self):
        self.pin(SHA)
        boom = AssertionError("network or resolution attempted")
        with mock.patch("socket.socket", side_effect=boom), mock.patch("subprocess.run", side_effect=boom), \
                mock.patch.object(I, "resolve_commit", side_effect=boom), \
                mock.patch.object(I, "resolve_install_ref", side_effect=boom):
            self.assertEqual(snippets.render(self.root, "ci"), I.ci_snippet(SHA))
            self.assertEqual(snippets.check(self.root), ([], []))
        self.tearDown(); self.setUp()
        with mock.patch("socket.socket", side_effect=boom), mock.patch("subprocess.run", side_effect=boom):
            with self.assertRaises(snippets.SnippetError):   # no pin: fails, never resolves
                snippets.render(self.root, "ci")

    def test_malformed_json_dangling_links_and_directories_fail(self):
        folder = self.root / ".aec" / "snippets"
        folder.mkdir()
        (folder / "claude-settings.json").write_text("{not json")
        self.assertTrue(any("claude-settings.json: stale" in b for b in snippets.check(self.root, SHA)[1]))
        (folder / "claude-settings.json").unlink()
        os.symlink(self.root / "missing", folder / "claude-settings.json")
        self.assertTrue(any("not a regular file" in b for b in snippets.check(self.root, SHA)[1]))
        (folder / "claude-settings.json").unlink()
        (folder / "aec-ci.yml").mkdir()
        self.assertTrue(any("aec-ci.yml: not a regular file" in b for b in snippets.check(self.root, SHA)[1]))

    def test_empty_snippets_folder_passes(self):
        (self.root / ".aec" / "snippets").mkdir()
        self.assertEqual(snippets.check(self.root, SHA), ([], []))

    def test_snippet_files_false_leaves_existing_copies_untouched(self):
        folder = self.root / ".aec" / "snippets"
        folder.mkdir()
        (folder / "claude-settings.json").write_text("mine\n")
        rep = self.init(snippet_files=False)
        self.assertEqual((folder / "claude-settings.json").read_text(), "mine\n")
        self.assertEqual(sorted(x.name for x in folder.iterdir()), ["claude-settings.json"])
        self.assertFalse(any("snippets/" in k for k in rep["created"] + rep["kept"]))

    def test_snippet_files_true_explicitly_writes_copies(self):
        self.cfg({"snippet_files": True})
        self.assertIs(config.load(self.root).get("init.snippet_files"), True)
        rep = self.init(snippet_files=True)
        self.assertIn(".aec/snippets/aec-ci.yml", rep["created"])


class ExplicitFlags(Base):
    def test_flags_win_over_the_config(self):
        self.cfg({"hook_style": "line", "ci_name": "gov"})
        code, out, _ = run(["snippets", "show", "hook", "--repo", str(self.root), "--hook-style", "inline"])
        self.assertEqual(json.loads(out), I.HOOK)
        self.assertEqual(snippets.render(self.root, "ci", SHA, ci_name="other"), I.ci_snippet(SHA, "other"))

    def test_bad_flag_values_are_refused(self):
        code, _, err = run(["snippets", "show", "ci", "--repo", str(self.root), "--ref", SHA, "--ci-name", "a b"])
        self.assertEqual(code, 1)
        self.assertIn("--ci-name", err)
        code, _, _ = run(["snippets", "show", "hook", "--repo", str(self.root), "--hook-style", "loud"])
        self.assertEqual(code, 2)  # argparse choices

    def test_check_uses_the_flags(self):
        folder = self.root / ".aec" / "snippets"
        folder.mkdir()
        (folder / "claude-settings.json").write_text(json.dumps(I.HOOK_LINE))
        (folder / "gov-ci.yml").write_text(I.ci_snippet(SHA, "gov"))
        self.assertTrue(snippets.check(self.root, SHA)[1])  # defaults: stale and misnamed
        self.assertEqual(snippets.check(self.root, SHA, "line", "gov")[1], [])


if __name__ == "__main__":
    unittest.main()
