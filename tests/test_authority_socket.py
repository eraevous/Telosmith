"""The authority socket (DEC-185) as a declared field of the A2A Agent Card (DEC-256 item 5, slice 3)."""
import contextlib
import io
import json
import sys
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


def ext(card):
    return card["capabilities"]["extensions"][0]


class Declared(unittest.TestCase):
    def test_absent_unless_asked(self):
        self.assertNotIn("extensions", a2a.build_card(**BASE)["capabilities"])

    def test_declares_needs_accepts_grants_as_an_optional_extension(self):
        card = a2a.build_card(**BASE, authority={"needs": ["read the content folder"], "grants": []})
        e = ext(card)
        self.assertEqual(e["uri"], a2a.AUTHORITY_EXTENSION_URI)
        self.assertIs(e["required"], False)
        self.assertEqual(e["params"], {"needs": ["read the content folder"], "accepts": [], "grants": [],
                                       "protocol": a2a.AUTHORITY_PROTOCOL})
        self.assertEqual(a2a.validate_card(card), [])

    def test_unknown_authority_keys_are_refused(self):
        with self.assertRaises(a2a.CardError):
            a2a.build_card(**BASE, authority={"needs": [], "owner": "x"})
        with self.assertRaises(a2a.CardError):
            a2a.build_card(**BASE, authority=["needs"])

    def test_wrong_shapes_are_card_errors_not_type_errors(self):
        for bad in ({"needs": "one string"}, {"grants": [""]}, {"accepts": [1]}):
            with self.assertRaises(a2a.CardError, msg=bad):
                a2a.build_card(**BASE, authority=bad)


class Checked(unittest.TestCase):
    def card(self, **changes):
        card = a2a.build_card(**BASE, authority={"needs": ["x"]})
        ext(card).update(changes)
        return card

    def test_the_declaration_may_not_claim_a_protocol_or_be_required(self):
        self.assertTrue(a2a.validate_card(self.card(required=True)))
        card = self.card()
        ext(card)["params"]["protocol"] = "signed-commits"
        self.assertTrue(a2a.validate_card(card))

    def test_unknown_params_and_missing_params(self):
        card = self.card()
        ext(card)["params"]["owner"] = "zach"
        self.assertIn("unknown keys", " ".join(a2a.validate_card(card)))
        card = self.card()
        del ext(card)["params"]
        self.assertTrue(a2a.validate_card(card))

    def test_each_missing_declaration_member_fails(self):
        # AEC-R-authority-socket@1 (Kate): missing required declaration members fail
        for k in ("needs", "accepts", "grants", "protocol"):
            card = self.card()
            del ext(card)["params"][k]
            self.assertTrue(a2a.validate_card(card), k)

    def test_other_extensions_only_need_a_uri(self):
        card = a2a.build_card(**BASE)
        card["capabilities"]["extensions"] = [{"uri": "https://example.test/ext", "params": {"any": 1}}]
        self.assertEqual(a2a.validate_card(card), [])
        card["capabilities"]["extensions"] = [{"params": {}}, "x"]
        self.assertEqual(len(a2a.validate_card(card)), 2)
        card["capabilities"]["extensions"] = {}
        self.assertTrue(a2a.validate_card(card))


class Cli(unittest.TestCase):
    def test_flags_declare_the_socket(self):
        code, out, err = run(["a2a", "card", "--name", "d", "--description", "D", "--version", "1",
                              "--url", "https://example.test/a2a", "--authority-needs", "read records",
                              "--authority-needs", "append records", "--authority-grants", "none"])
        self.assertEqual(code, 0, err)
        params = ext(json.loads(out))["params"]
        self.assertEqual(params["needs"], ["read records", "append records"])
        self.assertEqual(params["grants"], ["none"])
        self.assertEqual(params["accepts"], [])

    def test_no_flags_no_extension(self):
        code, out, _ = run(["a2a", "card", "--name", "d", "--description", "D", "--version", "1",
                            "--url", "https://example.test/a2a"])
        self.assertEqual(code, 0)
        self.assertNotIn("extensions", json.loads(out)["capabilities"])


if __name__ == "__main__":
    unittest.main()
