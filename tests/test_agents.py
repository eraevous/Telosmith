"""aec agents: the shared governance block of AGENTS.md, rendered from .aec/config.json (DEC-256 item 4)."""
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

from aec import agents, config  # noqa: E402
from aec.__main__ import main  # noqa: E402

OWN = "# Repo\n\nOur own rules.\n\n"
TAIL = "\n## Ours again\n\nMore of our own text.\n"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "repo"
        (self.root / ".aec").mkdir(parents=True)
        (self.root / ".git").mkdir()
        self.md = self.root / "AGENTS.md"

    def conf(self, agents_section=None, **top):
        doc = dict(top)
        if agents_section is not None:
            doc["agents"] = agents_section
        (self.root / config.CONFIG_PATH).write_text(json.dumps(doc), encoding="utf-8")

    def agents(self, *args):
        return run(["agents", *args, "--repo", str(self.root)])

    def with_markers(self, inner="stale\n"):
        self.md.write_text(OWN + agents.BEGIN + "\n" + inner + agents.END + "\n" + TAIL, encoding="utf-8")


class Render(Case):
    def test_defaults_without_a_config(self):
        block = agents.render(config.own(self.root))
        self.assertTrue(block.startswith(agents.BEGIN + "\n") and block.endswith(agents.END + "\n"))
        self.assertIn("belongs to the repository owner", block)
        self.assertIn("- `.aec/records.jsonl`", block)
        self.assertIn("No glossary is configured", block)
        self.assertEqual(block, agents.render(config.own(self.root)))   # deterministic

    def test_config_values_rendered(self):
        self.conf({"owner": "Ana", "glossary": "https://example.org/glossary", "read_first": ["CHARTER.md", "VISION.md"],
                   "ledgers": ["decisions/log.jsonl", "data/records.jsonl"], "hard_rules": ["Never write to the sheet."]},
                  records="data/records.jsonl")
        block = agents.render(config.own(self.root))
        self.assertIn("belongs to Ana", block)
        self.assertIn("until Ana decides otherwise", block)
        self.assertIn("1. The purpose records in `data/records.jsonl`", block)
        self.assertIn("2. `CHARTER.md`\n3. `VISION.md`\n", block)
        self.assertIn("glossary: `https://example.org/glossary`", block)
        self.assertIn("- Never write to the sheet.\n", block)
        # the records file is listed once, first, even when a ledger repeats it
        ledgers = block.split("### Records and ledgers")[1].split("Record terms")[0]
        self.assertEqual([ln for ln in ledgers.splitlines() if ln.startswith("- ")],
                         ["- `data/records.jsonl`", "- `decisions/log.jsonl`"])


class KateRound7(Case):
    """Gaps her round-7 records name (AEC-R-agents-render/-config/-block/-write/-check@1, independent)."""

    def test_default_render_matches_the_fixture_exactly(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "agents" / "default-block.md"
        self.assertEqual(agents.render(config.own(self.root)), fixture.read_text(encoding="utf-8"))

    def test_cwd_config_is_not_used(self):
        other = Path(self._tmp.name) / "other"
        (other / ".aec").mkdir(parents=True)
        (other / ".aec" / "config.json").write_text(json.dumps({"agents": {"owner": "Wrong"}}), encoding="utf-8")
        cwd = os.getcwd()
        os.chdir(other)
        try:
            self.assertNotIn("Wrong", self.agents("show")[1])
        finally:
            os.chdir(cwd)

    def test_300_and_301_characters(self):
        self.conf({"owner": "x" * 300})
        self.assertEqual(config.own(self.root).get("agents.owner"), "x" * 300)
        self.conf({"owner": "x" * 301})
        with self.assertRaises(config.ConfigError):
            config.own(self.root)
        self.conf({"owner": "a\tb"})
        with self.assertRaises(config.ConfigError):
            config.own(self.root)

    def test_non_ascii_and_crlf_outside_the_block_are_kept_byte_for_byte(self):
        before = "# Dépôt 日本\r\n\r\nRègle ✓\r\n".encode()
        after = "\r\n## Fin — ok\r\n".encode()
        self.md.write_bytes(before + (agents.BEGIN + "\nold\n" + agents.END + "\n").encode("utf-8") + after)
        self.assertEqual(self.agents("write")[0], 0)
        data = self.md.read_bytes()
        self.assertTrue(data.startswith(before) and data.endswith(after))
        self.assertEqual(self.agents("check")[0], 0)

    def test_a_unicode_line_separator_does_not_make_a_marker_line(self):
        text = OWN + agents.BEGIN + "\nx\n" + "prose\u2028" + agents.END + "\n" + agents.END + "\n"
        self.md.write_text(text, encoding="utf-8", newline="")
        self.assertEqual(self.agents("write")[0], 0)
        self.assertNotIn("prose", self.md.read_text(encoding="utf-8"))   # replaced as block interior, not a split point
        self.assertEqual(self.agents("check")[0], 0)

    def test_no_op_keeps_the_inode(self):
        self.with_markers()
        self.agents("write")
        inode = self.md.stat().st_ino
        self.agents("write")
        self.assertEqual(self.md.stat().st_ino, inode)

    def test_a_failure_before_the_rename_leaves_the_original(self):
        self.with_markers()
        before = self.md.read_bytes()
        with mock.patch("aec.agents.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.agents("write")
        self.assertEqual(self.md.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), [".aec", ".git", "AGENTS.md"])

    def test_a_new_file_gets_the_umask_mode(self):
        old = os.umask(0o027)
        try:
            self.assertEqual(self.agents("write", "--append")[0], 0)
        finally:
            os.umask(old)
        self.assertEqual(self.md.stat().st_mode & 0o777, 0o640)

    def test_show_and_check_take_no_append_and_never_write(self):
        self.with_markers()
        before = (self.md.read_bytes(), self.md.stat().st_mtime_ns)
        for cmd in ("show", "check"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.agents(cmd, "--append")[0], 2)   # argparse: unknown option
                self.agents(cmd)
        self.assertEqual((self.md.read_bytes(), self.md.stat().st_mtime_ns), before)

    def test_invalid_config_fails_check_and_show(self):
        self.with_markers()
        self.agents("write")
        self.conf({"owner": "a`b"})
        for cmd in ("show", "check"):
            with self.subTest(cmd=cmd):
                code, _, err = self.agents(cmd)
                self.assertEqual(code, 1)
                self.assertIn("agents.owner", err)


class Write(Case):
    def test_replaces_only_between_markers(self):
        self.conf({"owner": "Ana"})
        self.with_markers()
        code, out, err = self.agents("write")
        self.assertEqual(code, 0, err)
        text = self.md.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(OWN))
        self.assertTrue(text.endswith(TAIL))
        self.assertNotIn("stale", text)
        self.assertEqual(text, OWN + agents.render(config.own(self.root)) + TAIL)

    def test_a_short_begin_marker_is_found_and_normalised(self):
        self.md.write_text(OWN + "<!-- telosmith:agents:begin -->\nold\n" + agents.END + "\n", encoding="utf-8")
        self.assertEqual(self.agents("write")[0], 0)
        self.assertIn(agents.BEGIN, self.md.read_text(encoding="utf-8"))

    def test_second_write_changes_nothing(self):
        self.with_markers()
        self.agents("write")
        before = self.md.stat().st_mtime_ns
        code, out, _ = self.agents("write")
        self.assertEqual(code, 0)
        self.assertIn("already up to date", out)
        self.assertEqual(self.md.stat().st_mtime_ns, before)

    def test_no_markers_is_refused_unless_append(self):
        self.md.write_text(OWN, encoding="utf-8")
        code, _, err = self.agents("write")
        self.assertEqual(code, 1)
        self.assertIn("no telosmith:agents markers", err)
        self.assertEqual(self.md.read_text(encoding="utf-8"), OWN)
        self.assertEqual(self.agents("write", "--append")[0], 0)
        text = self.md.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(OWN.rstrip("\n") + "\n\n" + agents.BEGIN))
        self.assertEqual(self.agents("check")[0], 0)

    def test_append_keeps_existing_bytes_verbatim(self):
        # Copilot on #101: trailing blank lines and whitespace-only files were trimmed
        for before, sep in (("# Repo\n\n\n\n", ""), ("# Repo", "\n\n"), ("# Repo\n", "\n"),
                            ("  \n\t\n", "\n"), ("# Repo\r\n", "\n")):
            with self.subTest(before=before):
                self.md.write_bytes(before.encode("utf-8"))
                self.assertEqual(self.agents("write", "--append")[0], 0)
                text = self.md.read_bytes().decode("utf-8")
                self.assertEqual(text, before + sep + agents.render(config.own(self.root)))
                self.assertEqual(self.agents("check")[0], 0)

    def test_missing_file_is_refused_unless_append(self):
        self.assertEqual(self.agents("write")[0], 1)
        self.assertFalse(self.md.exists())
        self.assertEqual(self.agents("write", "--append")[0], 0)
        self.assertEqual(self.md.read_text(encoding="utf-8"), agents.render(config.own(self.root)))

    def test_malformed_markers_are_refused(self):
        b, e = agents.BEGIN + "\n", agents.END + "\n"
        for text in (OWN + b + "x\n" + b + "y\n" + e,          # two begins
                     OWN + e + "x\n" + b,                       # end before begin
                     OWN + b + "x\n",                           # begin only
                     OWN + b + e + b + e):                      # two blocks
            with self.subTest(text=text):
                self.md.write_text(text, encoding="utf-8")
                code, _, err = self.agents("write", "--append")
                self.assertEqual(code, 1)
                self.assertIn("expected one begin marker", err)
                self.assertEqual(self.md.read_text(encoding="utf-8"), text)

    def test_a_line_that_only_starts_like_a_marker_is_refused(self):   # Codex P2 on #101
        b, e = agents.BEGIN + "\n", agents.END + "\n"
        for text in (OWN + "<!-- telosmith:agents:begin --> keep this prose\nour rule\n" + e,
                     OWN + "<!-- telosmith:agents:begin (anything) --> and more\nx\n" + e,
                     OWN + b + "x\n" + "<!-- telosmith:agents:end --> trailing\n",
                     OWN + "<!-- telosmith:agents:beginning -->\n" + b + "x\n" + e):
            with self.subTest(text=text):
                self.md.write_text(text, encoding="utf-8")
                for cmd in (("write",), ("write", "--append"), ("check",)):
                    code, _, err = self.agents(*cmd)
                    self.assertEqual(code, 1)
                    self.assertIn("starts like a telosmith:agents marker but isn't one", err)
                self.assertEqual(self.md.read_text(encoding="utf-8"), text)

    def test_indented_exact_markers_still_count(self):   # decoy
        self.md.write_text(OWN + "  <!-- telosmith:agents:begin -->\nold\n  " + agents.END + "\n", encoding="utf-8")
        self.assertEqual(self.agents("write")[0], 0)
        self.assertEqual(self.agents("check")[0], 0)

    def test_marker_text_inside_a_line_is_not_a_marker(self):
        text = OWN + "Mention `" + agents.END + "` in prose.\n"
        self.md.write_text(text, encoding="utf-8")
        self.assertEqual(self.agents("write")[1:], ("", f"agents: {self.md}: has no telosmith:agents markers; add "
                                                    "them where the block belongs, or use --append to add the block at the end\n"))

    def test_invalid_config_writes_nothing(self):
        self.conf({"owner": "a`b"})
        self.with_markers()
        before = self.md.read_text(encoding="utf-8")
        code, _, err = self.agents("write")
        self.assertEqual(code, 1)
        self.assertIn("agents.owner", err)
        self.assertEqual(self.md.read_text(encoding="utf-8"), before)

    def test_keeps_the_file_mode(self):
        self.with_markers()
        os.chmod(self.md, 0o640)
        self.agents("write")
        self.assertEqual(self.md.stat().st_mode & 0o777, 0o640)


class Safety(Case):
    def test_symlinked_agents_md_is_refused(self):
        outside = Path(self._tmp.name) / "outside.md"
        outside.write_text(agents.BEGIN + "\nx\n" + agents.END + "\n", encoding="utf-8")
        self.md.symlink_to(outside)
        before = outside.read_text(encoding="utf-8")
        for cmd in (("write",), ("write", "--append"), ("check",)):
            with self.subTest(cmd=cmd):
                code, _, err = self.agents(*cmd)
                self.assertEqual(code, 1)
                self.assertIn("is a symlink", err)
        self.assertEqual(outside.read_text(encoding="utf-8"), before)

    def test_symlinked_parent_folder_is_refused(self):
        outside = Path(self._tmp.name) / "elsewhere"
        outside.mkdir()
        (self.root / "docs").symlink_to(outside)
        code, _, err = self.agents("write", "--append", "--file", "docs/AGENTS.md")
        self.assertEqual(code, 1)
        self.assertIn("is a symlink", err)
        self.assertEqual(list(outside.iterdir()), [])

    def test_file_outside_the_repository_is_refused(self):
        for bad in ("../AGENTS.md", str(Path(self._tmp.name) / "x.md"), " AGENTS.md",
                    "\\AGENTS.md", "D:AGENTS.md", "C:\\x\\AGENTS.md", "sub\\..\\..\\AGENTS.md"):   # Copilot on #101
            with self.subTest(bad=bad):
                code, _, err = self.agents("write", "--append", "--file", bad)
                self.assertEqual(code, 1)
                self.assertIn("relative path inside the repository", err)
        self.assertEqual(sorted(p.name for p in Path(self._tmp.name).iterdir()), ["repo"])

    def test_decoy_subfolder_file_is_written(self):
        (self.root / "docs").mkdir()
        self.assertEqual(self.agents("write", "--append", "--file", "docs/AGENTS.md")[0], 0)
        self.assertTrue((self.root / "docs" / "AGENTS.md").is_file())


class Check(Case):
    def test_missing_different_and_matching(self):
        self.assertEqual(self.agents("check")[0], 1)                     # no file
        self.md.write_text(OWN, encoding="utf-8")
        self.assertIn("no shared block", self.agents("check")[2])         # no markers
        self.with_markers()
        self.assertIn("differs", self.agents("check")[2])                 # stale block
        self.agents("write")
        self.assertEqual(self.agents("check")[0], 0)
        self.conf({"owner": "Ana"})                                       # the config changed
        self.assertEqual(self.agents("check")[0], 1)

    def test_show_prints_the_block(self):
        code, out, _ = self.agents("show")
        self.assertEqual((code, out), (0, agents.render(config.own(self.root))))


class ConfigKeys(Case):
    def bad(self, section, *needles):
        self.conf(section)
        with self.assertRaises(config.ConfigError) as caught:
            config.own(self.root)
        for needle in needles:
            self.assertIn(needle, str(caught.exception))

    def test_refused_values(self):
        self.bad({"colour": "red"}, "unknown key 'agents.colour'")
        self.bad([], "agents: must be an object")
        self.bad({"owner": ""}, "agents.owner: must be a non-empty string")
        self.bad({"owner": "a\nb"}, "agents.owner: must be one printable line")
        self.bad({"owner": "a\u2028b"}, "agents.owner: must be one printable line")
        self.bad({"owner": "x" * 301}, "at most 300")
        self.bad({"owner": "<!-- telosmith:agents:end -->"}, "HTML comment marker")
        self.bad({"hard_rules": ["ok", "-->"]}, "agents.hard_rules[1]")
        self.bad({"hard_rules": "one rule"}, "agents.hard_rules: must be a list")
        self.bad({"read_first": ["A.md", "A.md"]}, "agents.read_first[1]: repeated value")
        self.bad({"read_first": ["/etc/passwd"]}, "agents.read_first[0]: must be a relative path")
        self.bad({"ledgers": ["../x.jsonl"]}, "agents.ledgers[0]: must stay inside")
        self.bad({"ledgers": [3]}, "agents.ledgers[0]: must be a non-empty string")
        self.bad({"glossary": "http://example.org/g"}, "must start with https://")
        self.bad({"glossary": "C:/g.md"}, "agents.glossary: must be a relative path")

    def test_records_path_cannot_break_the_block(self):   # Codex P2 on #101: records is rendered too
        for bad in ("a\n<!-- telosmith:agents:end -->\nb.jsonl", "a`b.jsonl", "a<!--b.jsonl", "a-->b.jsonl"):
            with self.subTest(bad=bad):
                self.conf(records=bad)
                with self.assertRaises(config.ConfigError) as caught:
                    config.own(self.root)
                self.assertIn("records:", str(caught.exception))
                self.with_markers()
                before = self.md.read_text(encoding="utf-8")
                self.assertEqual(self.agents("write")[0], 1)
                self.assertEqual(self.md.read_text(encoding="utf-8"), before)
        self.conf(records="data/my records-v2.jsonl")   # decoy: an ordinary path still renders
        self.assertIn("`data/my records-v2.jsonl`", agents.render(config.own(self.root)))

    def test_accepted_values(self):   # decoys for the refusals above
        self.conf({"owner": "Ana (maintainer)", "glossary": "https://example.org/g", "read_first": ["a/B.md"],
                   "ledgers": [], "hard_rules": ["Use <b> sparingly -- not as markers."]})
        cfg = config.own(self.root)
        self.assertEqual(cfg.get("agents.owner"), "Ana (maintainer)")
        self.assertEqual(cfg.source("agents.ledgers"), "config")
        self.conf({"glossary": "docs/glossary.md"})
        self.assertEqual(config.own(self.root).get("agents.glossary"), "docs/glossary.md")

    def test_list_defaults_are_not_shared(self):
        cfg = config.own(self.root)
        cfg.get("agents.read_first").append("X.md")
        self.assertEqual(config.own(self.root).get("agents.read_first"), [])

    def test_config_show_lists_the_agents_keys(self):
        code, out, _ = run(["config", "show", "--repo", str(self.root), "--json"])
        self.assertEqual(code, 0)
        settings = json.loads(out)["settings"]
        self.assertEqual(settings["agents.owner"], {"value": "the repository owner", "from": "default"})
        self.assertEqual(settings["agents.hard_rules"], {"value": [], "from": "default"})


if __name__ == "__main__":
    unittest.main()
