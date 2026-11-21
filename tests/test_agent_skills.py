"""aec skills: the Agent Skills (SKILL.md) folder a Telosmith-based project ships its know-how in (DEC-256 item 5, slice 3)."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from aec import skills  # noqa: E402
from aec.__main__ import main  # noqa: E402

EXAMPLE = ROOT / "examples" / "skills" / "telosmith-records"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def write_skill(parent: Path, folder: str, text: str) -> Path:
    d = parent / folder
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(text, encoding="utf-8")
    return d


GOOD = '---\nname: demo-skill\ndescription: Does a demo. Use when testing.\n---\n# Body\n'


class Parse(unittest.TestCase):
    def test_plain_quoted_and_metadata(self):
        fm, body, problems = skills.parse_skill_md(
            "---\nname: a-b\ndescription: 'it''s fine'  # c\nlicense: \"MIT\"\nmetadata:\n  k: v\n  q: \"x: y\"\n---\nhello\n")
        self.assertEqual(problems, [])
        self.assertEqual(fm, {"name": "a-b", "description": "it's fine", "license": "MIT",
                              "metadata": {"k": "v", "q": "x: y"}})
        self.assertEqual(body, "hello")

    def test_no_front_matter_or_unclosed(self):
        self.assertTrue(skills.parse_skill_md("# no front matter\n")[2])
        self.assertIn("no closing", skills.parse_skill_md("---\nname: a\n")[2][0])

    def test_yaml_outside_the_subset_is_reported_not_guessed(self):
        for raw in ("description: >\n  folded", "description: [a, b]", "description: {a: b}", "description: &x y"):
            fm, _, problems = skills.parse_skill_md(f"---\nname: a\n{raw}\n---\n")
            self.assertTrue(problems, raw)
            self.assertNotIn("description", fm, raw)

    def test_repeated_key_and_plain_value_with_colon(self):
        self.assertIn("repeated key", skills.parse_skill_md("---\nname: a\nname: b\n---\n")[2][0])
        self.assertIn("': '", skills.parse_skill_md("---\nname: a\ndescription: x: y\n---\n")[2][0])


class Validate(unittest.TestCase):
    def test_name_rules_from_the_specification(self):
        for bad in ("PDF-Processing", "-pdf", "pdf-", "pdf--processing", "a_b", "", "a" * 65):
            self.assertTrue(skills.validate_frontmatter({"name": bad, "description": "d"}), bad)
        for good in ("pdf-processing", "a", "a1-b2", "a" * 64):
            self.assertEqual(skills.validate_frontmatter({"name": good, "description": "d"}), [], good)

    def test_name_must_match_folder(self):
        self.assertIn("must match the folder",
                      skills.validate_frontmatter({"name": "a", "description": "d"}, "b")[0])

    def test_lengths_required_unknown_and_types(self):
        v = skills.validate_frontmatter
        self.assertEqual(len(v({})), 2)
        self.assertTrue(v({"name": "a", "description": "x" * 1025}))
        self.assertTrue(v({"name": "a", "description": "   "}))
        self.assertTrue(v({"name": "a", "description": "d", "compatibility": "x" * 501}))
        self.assertTrue(v({"name": "a", "description": "d", "version": "1"}))  # not a spec field
        self.assertTrue(v({"name": "a", "description": "d", "metadata": "x"}))
        self.assertTrue(v({"name": "a", "description": {}}))
        self.assertEqual(v([]), ["the front matter is not a mapping"])
        self.assertEqual(v({"name": "a", "description": "d", "allowed-tools": "Bash(git:*) Read",
                            "metadata": {"k": "v"}, "license": "MIT", "compatibility": "py3"}), [])

    def test_every_problem_reported_at_once(self):
        self.assertGreaterEqual(len(skills.validate_frontmatter({"name": "Bad--", "description": "", "x": "y"})), 3)


class Render(unittest.TestCase):
    def test_round_trip_through_the_checker(self):
        text = skills.render_skill(name="demo", description='Quotes " and \\ and: colons # too',
                                   license="MIT", metadata={"a": "b: c"}, body="# demo")
        fm, body, problems = skills.parse_skill_md(text)
        self.assertEqual(problems, [])
        self.assertEqual(fm["description"], 'Quotes " and \\ and: colons # too')
        self.assertEqual(fm["metadata"], {"a": "b: c"})
        self.assertEqual(body, "# demo")

    def test_invalid_values_raise_skill_error(self):
        with self.assertRaises(skills.SkillError):
            skills.render_skill(name="Bad", description="")


class Folders(unittest.TestCase):
    def test_the_shipped_example_is_valid(self):
        self.assertEqual(skills.check_skill_dir(EXAMPLE), [])

    def test_new_writes_a_valid_skill_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as t:
            code, out, err = run(["skills", "new", "my-skill", "--description", "Does X. Use for Y.", "--dir", t])
            self.assertEqual(code, 0, err)
            self.assertEqual(skills.check_skill_dir(Path(t) / "my-skill"), [])
            before = (Path(t) / "my-skill" / "SKILL.md").read_text()
            code, _, err = run(["skills", "new", "my-skill", "--description", "other", "--dir", t])
            self.assertEqual(code, 1)
            self.assertIn("not overwriting", err)
            self.assertEqual((Path(t) / "my-skill" / "SKILL.md").read_text(), before)

    def test_new_refuses_an_invalid_name_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as t:
            code, _, err = run(["skills", "new", "Bad_Name", "--description", "d", "--dir", t])
            self.assertEqual(code, 1)
            self.assertIn("lowercase", err)
            self.assertEqual(list(Path(t).iterdir()), [])

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symlinks")
    def test_new_does_not_write_through_a_symlinked_skill_folder(self):
        with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as outside:
            os.symlink(outside, Path(t) / "my-skill")
            code, _, err = run(["skills", "new", "my-skill", "--description", "d", "--dir", t])
            self.assertEqual(code, 1, err)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_check_a_folder_of_skills_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)
            write_skill(p, "demo-skill", GOOD)
            code, out, err = run(["skills", "check", t])
            self.assertEqual(code, 0, err)
            self.assertIn("valid skill", out)
            write_skill(p, "other", GOOD)  # name doesn't match folder
            code, out, err = run(["skills", "check", t])
            self.assertEqual(code, 1)
            self.assertIn("must match the folder name 'other'", err)

    def test_check_reports_a_path_with_no_skill(self):
        with tempfile.TemporaryDirectory() as t:
            code, _, err = run(["skills", "check", t])
            self.assertEqual(code, 1)
            self.assertIn("no SKILL.md", err)

    def test_check_never_raises_on_unreadable_text(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "bin"
            d.mkdir()
            (d / "SKILL.md").write_bytes(b"\xff\xfe---")
            self.assertIn("cannot read", skills.check_skill_dir(d)[0])


if __name__ == "__main__":
    unittest.main()
