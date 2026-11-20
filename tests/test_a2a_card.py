"""aec a2a: the A2A 1.0 Agent Card a Telosmith-based project describes itself with (DEC-256 item 5, slice 2)."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aec import a2a  # noqa: E402
from aec.__main__ import main  # noqa: E402

BASE = dict(name="demo", description="A demo tool.", version="0.1.0", url="https://example.test/a2a")


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class BuildCard(unittest.TestCase):
    def test_minimal_card_has_every_required_field(self):
        card = a2a.build_card(**BASE)
        for k in a2a.CARD_REQUIRED:
            self.assertIn(k, card)
        self.assertEqual(card["supportedInterfaces"],
                         [{"url": BASE["url"], "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}])
        self.assertEqual(card["skills"], [])
        self.assertEqual(a2a.validate_card(card), [])

    def test_no_v03_top_level_fields(self):
        card = a2a.build_card(**BASE)
        for k in ("url", "preferredTransport", "protocolVersion"):
            self.assertNotIn(k, card)

    def test_skills_provider_and_round_trip(self):
        s = a2a.skill("records", "Records", "Read the records.", ["records", "read-only"], examples=["list"])
        card = a2a.build_card(**BASE, skills=[s], provider={"organization": "Org", "url": "https://org.test"},
                              documentation_url="https://example.test/docs", streaming=True)
        self.assertEqual(json.loads(json.dumps(card)), card)
        self.assertEqual(card["skills"][0]["examples"], ["list"])
        self.assertTrue(card["capabilities"]["streaming"])

    def test_bad_values_raise_naming_each_problem(self):
        with self.assertRaises(a2a.CardError) as cm:
            a2a.build_card(**{**BASE, "name": " ", "url": "ftp://x"})
        self.assertIn("'name'", str(cm.exception))
        self.assertIn("http(s) URL", str(cm.exception))


class ValidateCard(unittest.TestCase):
    def good(self):
        return a2a.build_card(**BASE, skills=[a2a.skill("a", "A", "Does a.", ["t"])])

    def test_not_an_object(self):
        self.assertEqual(a2a.validate_card([]), ["the card is not a JSON object"])

    def test_each_missing_required_field_is_named(self):
        for k in a2a.CARD_REQUIRED:
            card = self.good()
            del card[k]
            self.assertIn(f"missing required field {k!r}", a2a.validate_card(card), k)

    def test_empty_interfaces_and_interface_fields(self):
        card = self.good()
        card["supportedInterfaces"] = []
        self.assertIn("'supportedInterfaces' must be a non-empty list", a2a.validate_card(card))
        card["supportedInterfaces"] = [{"url": "/relative"}]
        problems = a2a.validate_card(card)
        self.assertIn("supportedInterfaces[0] is missing 'protocolBinding'", problems)
        self.assertIn("supportedInterfaces[0].url must be an absolute http(s) URL", problems)

    def test_skill_fields_and_duplicate_ids(self):
        card = self.good()
        card["skills"].append({"id": "a", "name": "A2", "description": "x", "tags": []})
        problems = a2a.validate_card(card)
        self.assertIn("skills[1].tags must be a non-empty list of strings", problems)
        self.assertIn("skills[1].id 'a' repeats an earlier skill id", problems)

    def test_modes_capabilities_and_provider_types(self):
        card = self.good()
        card["defaultInputModes"] = []
        card["capabilities"] = {"streaming": "yes"}
        card["provider"] = {"organization": "Org"}
        problems = a2a.validate_card(card)
        self.assertIn("'defaultInputModes' must be a non-empty list of media types", problems)
        self.assertIn("'capabilities.streaming' must be true or false", problems)
        self.assertIn("provider is missing 'url'", problems)

    def test_never_raises_on_odd_shapes(self):
        for odd in ({"skills": [1, None]}, {"supportedInterfaces": "x"}, {"capabilities": []}, {"provider": 3}):
            self.assertIsInstance(a2a.validate_card({**self.good(), **odd}), list)


class Cli(unittest.TestCase):
    def test_card_prints_a_valid_card(self):
        code, out, _ = run(["a2a", "card", "--name", "demo", "--description", "D", "--version", "1",
                            "--url", "https://example.test/a2a", "--skill", "r=Records|Read records.|records,read-only",
                            "--provider", "Org=https://org.test"])
        self.assertEqual(code, 0)
        card = json.loads(out)
        self.assertEqual(a2a.validate_card(card), [])
        self.assertEqual(card["skills"][0]["tags"], ["records", "read-only"])

    def test_bad_skill_flag_is_refused(self):
        code, out, err = run(["a2a", "card", "--name", "d", "--description", "D", "--version", "1",
                              "--url", "https://e.test", "--skill", "nope"])
        self.assertEqual((code, out), (1, ""))
        self.assertIn("expected ID=NAME|DESCRIPTION|tag1,tag2", err)

    def test_out_writes_then_never_overwrites_and_check_passes(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / a2a.WELL_KNOWN_PATH
            argv = ["a2a", "card", "--name", "d", "--description", "D", "--version", "1",
                    "--url", "https://e.test", "-o", str(path)]
            self.assertEqual(run(argv)[0], 0)
            before = path.read_text()
            code, _, err = run(argv[:-1] + [str(path)])
            self.assertEqual(code, 1)
            self.assertIn("not overwriting", err)
            self.assertEqual(path.read_text(), before)
            code, out, _ = run(["a2a", "check", str(path)])
            self.assertEqual(code, 0)
            self.assertIn("is an A2A 1.0 Agent Card", out)

    def test_check_reports_problems_and_unreadable_files(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "card.json"
            bad.write_text(json.dumps({"name": "x"}))
            code, _, err = run(["a2a", "check", str(bad)])
            self.assertEqual(code, 1)
            self.assertIn("missing required field 'skills'", err)
            bad.write_text("{not json")
            code, _, err = run(["a2a", "check", str(bad)])
            self.assertEqual(code, 1)
            self.assertIn("JSONDecodeError", err)


if __name__ == "__main__":
    unittest.main()
