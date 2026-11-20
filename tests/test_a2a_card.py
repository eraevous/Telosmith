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

    def test_flags_and_shapes_are_not_coerced(self):  # Copilot review on 8e3e591
        for kwargs, needle in (({"streaming": "false"}, "'capabilities.streaming' must be true or false"),
                               ({"push_notifications": 1}, "'capabilities.pushNotifications' must be true or false"),
                               ({"input_modes": "text/plain"}, "'defaultInputModes' must be a non-empty list"),
                               ({"output_modes": None}, "'defaultOutputModes' must be a non-empty list"),
                               ({"skills": [None]}, "skills[0] must be an object"),
                               ({"skills": None}, "'skills' must be a list"),
                               ({"provider": "Org"}, "'provider' must be an object")):
            with self.assertRaises(a2a.CardError, msg=kwargs) as cm:
                a2a.build_card(**BASE, **kwargs)
            self.assertIn(needle, str(cm.exception))

    def test_bad_values_raise_naming_each_problem(self):
        with self.assertRaises(a2a.CardError) as cm:
            a2a.build_card(**{**BASE, "name": " ", "url": "ftp://x"})
        self.assertIn("'name'", str(cm.exception))
        self.assertIn("http(s) URL", str(cm.exception))


class ValidateCard(unittest.TestCase):
    def good(self):
        return a2a.build_card(**BASE, skills=[a2a.skill("a", "A", "Does a.", ["t"])])

    def test_not_an_object(self):  # AEC-R-a2a-card-validation@1: root scalars, null and lists
        for root in ([], None, 3, "card", True):
            self.assertEqual(a2a.validate_card(root), ["the card is not a JSON object"], root)

    def test_independent_defects_are_reported_together(self):
        card = self.good()
        del card["name"]
        card["version"] = ""
        card["skills"][0]["tags"] = []
        self.assertEqual(len(a2a.validate_card(card)), 3)

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

    def test_malformed_url_is_a_problem_not_a_crash(self):  # Codex P2 on e14e93c
        card = self.good()
        card["supportedInterfaces"][0]["url"] = "https://["
        card["provider"] = {"organization": "Org", "url": "http://[::1"}
        problems = a2a.validate_card(card)
        self.assertIn("supportedInterfaces[0].url must be an absolute http(s) URL", problems)
        self.assertIn("provider.url must be an absolute http(s) URL", problems)
        code, out, err = run(["a2a", "card", "--name", "d", "--description", "D", "--version", "1", "--url", "https://["])
        self.assertEqual((code, out), (1, ""))
        self.assertIn("http(s) URL", err)

    def test_interface_address_follows_the_binding(self):  # Codex P2 on da72235
        card = a2a.build_card(**{**BASE, "url": "grpc.example.test:443"}, binding="GRPC")
        self.assertEqual(card["supportedInterfaces"][0]["url"], "grpc.example.test:443")
        for bad in ("grpc.example.test", "grpc.example.test:0", "grpc.example.test:http", ":443", "a b:443"):
            card["supportedInterfaces"][0]["url"] = bad
            self.assertIn("supportedInterfaces[0].url must be host:port (or a URL) for GRPC",
                          a2a.validate_card(card), bad)
        card["supportedInterfaces"][0].update(protocolBinding="HTTP+JSON", url="grpc.example.test:443")
        self.assertIn("supportedInterfaces[0].url must be an absolute http(s) URL", a2a.validate_card(card))
        card["supportedInterfaces"][0].update(protocolBinding="CUSTOM", url="custom:anything")
        self.assertEqual(a2a.validate_card(card), [])

    def test_hostless_urls_and_bad_ports_are_problems(self):  # Codex P2s on ef2308a
        card = self.good()
        for bad in ("https://:443", "https://example.test:notaport", "https://example.test:70000", "https://example.test:0"):
            card["supportedInterfaces"][0]["url"] = bad
            self.assertIn("supportedInterfaces[0].url must be an absolute http(s) URL", a2a.validate_card(card), bad)
        card["supportedInterfaces"][0].update(protocolBinding="GRPC")
        for bad in ("host:\u00b2", "host:" + "9" * 5000, "host:99999", "grpc://:443"):
            card["supportedInterfaces"][0]["url"] = bad
            self.assertIn("supportedInterfaces[0].url must be host:port (or a URL) for GRPC", a2a.validate_card(card), bad[:20])
        with self.assertRaises(a2a.CardError):
            a2a.build_card(**{**BASE, "url": "host:\u00b2"}, binding="GRPC")
        card["supportedInterfaces"][0]["url"] = "https://example.test:8443/a2a"
        card["supportedInterfaces"][0]["protocolBinding"] = "JSONRPC"
        self.assertEqual(a2a.validate_card(card), [])

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

    def test_unwritable_destination_is_a_clean_failure(self):  # Copilot review on 8e3e591
        with tempfile.TemporaryDirectory() as d:
            blocker = Path(d) / "file"
            blocker.write_text("x")
            code, out, err = run(["a2a", "card", "--name", "d", "--description", "D", "--version", "1",
                                  "--url", "https://e.test", "-o", str(blocker / "card.json")])
            self.assertEqual((code, out), (1, ""))
            self.assertIn("cannot write", err)

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
