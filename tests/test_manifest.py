"""aec manifest validate: the telosmith.manifest/1.0 schema check (AEC-D-manifest-schema@3, DEC-256 item 7 follow-up).

Test list from Kate's round-9 records (independent): AEC-R-manifest-socket-inventory@1 (MAN-01),
-versioned-validation@1 (MAN-02), -authority-consistency@1 (MAN-05), -collection-safety@1 (MAN-06, the validation
half) and -cache-policy@1 (MAN-04, the validation half). MAN-03 (rebuild drift) belongs to `aec manifest build|check`.
"""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from aec import a2a, manifest  # noqa: E402
from aec.__main__ import main  # noqa: E402

EXAMPLE = ROOT / "examples" / "manifest" / "telosmith.manifest.json"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def base() -> dict:
    """A minimal valid manifest: every socket key present in its empty form."""
    return {
        "manifest": "telosmith.manifest/1.0",
        "tool": {"id": "demo", "name": "Demo", "version": "0.1.0", "description": "A demo tool."},
        "sockets": {"mcp": None, "a2a": None, "skills": [], "other": [],
                    "authority": {"needs": [], "accepts": [], "grants": [], "protocol": a2a.AUTHORITY_PROTOCOL}},
        "runtime": {"network": "never", "model_calls": "never"},
    }


def mcp_section(version="0.1.0") -> dict:
    return {"transport": "stdio", "command": ["python3", "-m", "demo", "mcp"], "protocolVersions": ["2025-11-25"],
            "serverInfo": {"name": "demo", "version": version}, "capabilities": {"tools": {"listChanged": False}},
            "tools": [{"name": "t", "description": "d", "inputSchema": {"type": "object"}, "x-vendor": 1}],
            "resources": [], "resourceTemplates": [], "prompts": [], "listPolicy": {}}


NO_AUTHORITY = {"needs": [], "accepts": [], "grants": []}


def card(version="0.1.0", authority=NO_AUTHORITY, *, extension=True) -> dict:
    """A card; rule 4 makes the authority extension part of every card in a manifest, empty lists included."""
    return a2a.build_card(name="demo", description="A demo tool.", version=version, url="https://example.test/a2a",
                          authority=authority if extension else None)


def problems(m, **kw):
    return manifest.validate(m, **kw)[0]


class SocketInventory(unittest.TestCase):  # MAN-01
    def test_minimal_empty_forms_pass(self):
        self.assertEqual(problems(base()), [])

    def test_each_missing_socket_key_fails(self):
        for k in manifest.SOCKET_KEYS:
            with self.subTest(k=k):
                m = base()
                del m["sockets"][k]
                self.assertTrue(any(f"sockets.{k}" in p for p in problems(m)), problems(m))

    def test_wrong_empty_form_fails(self):
        for k, bad in (("mcp", []), ("a2a", {}), ("skills", None), ("other", None), ("authority", None)):
            with self.subTest(k=k):
                m = base()
                m["sockets"][k] = bad
                self.assertTrue(problems(m))

    def test_populated_sockets_pass(self):
        m = base()
        m["sockets"]["mcp"] = mcp_section()
        m["sockets"]["a2a"] = {"agentCard": card()}
        m["sockets"]["other"] = [{"id": "inbox", "kind": "folder", "direction": "in", "location": "content/",
                                  "planned": "MCP resource"}]
        self.assertEqual(problems(m), [])

    def test_other_is_reported_as_transitional_not_an_error(self):
        m = base()
        m["sockets"]["other"] = [{"id": "inbox", "kind": "folder", "direction": "in", "location": "content/",
                                  "planned": "MCP resource"}]
        errs, notes = manifest.validate(m)
        self.assertEqual(errs, [])
        self.assertTrue(any("transitional" in n and "inbox" in n for n in notes))

    def test_other_direction_must_be_in_or_out(self):
        m = base()
        m["sockets"]["other"] = [{"id": "x", "kind": "cli", "direction": "both", "location": "x", "planned": ""}]
        self.assertTrue(problems(m))


class VersionedValidation(unittest.TestCase):  # MAN-02
    def test_unknown_key_in_each_owned_object_fails(self):
        cases = {
            "envelope": lambda m: m.__setitem__("_doc", "x"),
            "tool": lambda m: m["tool"].__setitem__("homepage", "x"),
            "sockets": lambda m: m["sockets"].__setitem__("grpc", None),
            "authority": lambda m: m["sockets"]["authority"].__setitem__("note", "x"),
            "runtime": lambda m: m["runtime"].__setitem__("dependencies", []),
            "mcp": lambda m: (m["sockets"].__setitem__("mcp", mcp_section()),
                              m["sockets"]["mcp"].__setitem__("env", {})),
            "a2a": lambda m: m["sockets"].__setitem__("a2a", {"agentCard": card(), "url": "x"}),
            "other": lambda m: m["sockets"].__setitem__("other", [{"id": "x", "kind": "cli", "direction": "out",
                                                                   "location": "x", "planned": "", "extra": 1}]),
        }
        for where, mutate in cases.items():
            with self.subTest(where=where):
                m = base()
                mutate(m)
                self.assertTrue(any("unknown key" in p for p in problems(m)), problems(m))

    def test_upstream_objects_may_carry_fields_telosmith_does_not_know(self):
        m = base()
        m["sockets"]["mcp"] = mcp_section()  # its tool carries "x-vendor"
        m["sockets"]["mcp"]["capabilities"]["experimental"] = {"anything": True}
        m["sockets"]["mcp"]["serverInfo"]["title"] = "Demo"
        c = card()
        c["x-future-field"] = {"ok": True}
        m["sockets"]["a2a"] = {"agentCard": c}
        self.assertEqual(problems(m), [])

    def test_newer_minor_is_refused_naming_both_versions(self):
        m = base()
        m["manifest"] = "telosmith.manifest/1.1"
        p = problems(m)
        self.assertTrue(any("1.1" in x and "1.0" in x for x in p), p)

    def test_other_major_or_malformed_version_is_refused(self):
        for v in ("telosmith.manifest/2.0", "telosmith.manifest/1", "kairos.tool-manifest.provisional", 1.0, None):
            with self.subTest(v=v):
                m = base()
                m["manifest"] = v
                self.assertTrue(problems(m))

    def test_types_are_checked(self):
        for path, bad in ((("tool", "version"), 1), (("tool", "id"), ""), (("runtime", "network"), False),
                          (("runtime", "model_calls"), "sometimes")):
            with self.subTest(path=path):
                m = base()
                m[path[0]][path[1]] = bad
                self.assertTrue(problems(m))

    def test_runtime_unknown_is_accepted_and_listed(self):
        m = base()
        m["runtime"] = {"network": "unknown", "model_calls": "optional"}
        errs, notes = manifest.validate(m)
        self.assertEqual(errs, [])
        self.assertTrue(any("runtime.network" in n and "unknown" in n for n in notes))

    def test_runtime_needs_both_keys(self):
        m = base()
        del m["runtime"]["model_calls"]
        self.assertTrue(problems(m))

    def test_versions_must_agree(self):
        m = base()
        m["sockets"]["mcp"] = mcp_section(version="0.2.0")
        self.assertTrue(any("serverInfo.version" in p for p in problems(m)))
        m = base()
        m["sockets"]["a2a"] = {"agentCard": card(version="0.2.0")}
        self.assertTrue(any("agentCard.version" in p for p in problems(m)))

    def test_invalid_card_is_reported_under_its_path(self):
        m = base()
        c = card()
        del c["supportedInterfaces"]
        m["sockets"]["a2a"] = {"agentCard": c}
        self.assertTrue(any(p.startswith("sockets.a2a.agentCard") for p in problems(m)), problems(m))

    def test_mcp_tool_needs_name_and_input_schema(self):
        m = base()
        m["sockets"]["mcp"] = mcp_section()
        m["sockets"]["mcp"]["tools"] = [{"description": "no name"}]
        self.assertTrue(problems(m))

    def test_not_an_object_is_one_problem_not_a_crash(self):
        for v in ([], "x", None, 3):
            with self.subTest(v=v):
                self.assertTrue(problems(v))


class CachePolicy(unittest.TestCase):  # MAN-04, validation half
    def test_valid_policy_passes(self):
        m = base()
        m["sockets"]["mcp"] = mcp_section()
        m["sockets"]["mcp"]["listPolicy"] = {"tools": {"ttlMs": 60000, "cacheScope": "server"}}
        self.assertEqual(problems(m), [])

    def test_invalid_policy_fails(self):
        for pol in ({"tools": {"ttlMs": -1}}, {"tools": {"ttlMs": "60"}}, {"tools": {"ttlMs": True}},
                    {"tools": {"cacheScope": ""}}, {"widgets": {}}, {"tools": []}, []):
            with self.subTest(pol=pol):
                m = base()
                m["sockets"]["mcp"] = mcp_section()
                m["sockets"]["mcp"]["listPolicy"] = pol
                self.assertTrue(problems(m))


class AuthorityConsistency(unittest.TestCase):  # MAN-05
    AUTH = {"needs": ["read records"], "accepts": [], "grants": []}

    def test_placeholder_protocol_and_empty_grants_pass(self):
        m = base()
        m["sockets"]["authority"] = dict(self.AUTH, protocol=a2a.AUTHORITY_PROTOCOL)
        m["sockets"]["a2a"] = {"agentCard": card(authority=self.AUTH)}
        self.assertEqual(problems(m), [])

    def test_another_protocol_fails(self):
        m = base()
        m["sockets"]["authority"]["protocol"] = "oauth2"
        self.assertTrue(problems(m))

    def test_missing_extension_on_the_card_fails(self):
        m = base()
        m["sockets"]["authority"] = dict(self.AUTH, protocol=a2a.AUTHORITY_PROTOCOL)
        m["sockets"]["a2a"] = {"agentCard": card(extension=False)}
        self.assertTrue(any("authority" in p for p in problems(m)), problems(m))
        m = base()  # rule 4 holds with an empty declaration too
        m["sockets"]["a2a"] = {"agentCard": card(extension=False)}
        self.assertTrue(any("authority" in p for p in problems(m)), problems(m))

    def test_mismatched_params_fail(self):
        m = base()
        m["sockets"]["authority"] = dict(self.AUTH, protocol=a2a.AUTHORITY_PROTOCOL)
        m["sockets"]["a2a"] = {"agentCard": card(authority={"needs": ["something else"]})}
        self.assertTrue(any("authority" in p for p in problems(m)), problems(m))

    def test_extension_present_twice_fails(self):
        m = base()
        m["sockets"]["authority"] = dict(self.AUTH, protocol=a2a.AUTHORITY_PROTOCOL)
        c = card(authority=self.AUTH)
        c["capabilities"]["extensions"].append(copy.deepcopy(c["capabilities"]["extensions"][0]))
        m["sockets"]["a2a"] = {"agentCard": c}
        self.assertTrue(problems(m))

    def test_declared_grants_are_listed_as_declarations_not_grants(self):
        # Reading (unconfirmed): the accepted page lets a declaration name grants (as aec a2a does) and says it
        # grants nothing; MAN-05 would fail them. Kept as a note; asked of Kate and Zach in the handoff output.
        m = base()
        m["sockets"]["authority"]["grants"] = ["review sign-off"]
        errs, notes = manifest.validate(m)
        self.assertEqual(errs, [])
        self.assertTrue(any("grants" in n and "nothing is granted" in n for n in notes))

    def test_absent_list_or_non_string_entry_fails(self):
        for k, bad in (("needs", None), ("accepts", "x"), ("grants", [""]), ("needs", [1])):
            with self.subTest(k=k):
                m = base()
                m["sockets"]["authority"][k] = bad
                self.assertTrue(problems(m))


class CollectionSafety(unittest.TestCase):  # MAN-06, validation half
    SECRETS = ["ghp_" + "a" * 36, "AKIA" + "B" * 16, "xoxb-1234-abcd", "sk-" + "c" * 40,
               "https://user:hunter2@example.test/x", "API_TOKEN=abc123"]

    def test_secret_shaped_values_fail_and_are_not_echoed(self):
        for s in self.SECRETS:
            with self.subTest(s=s[:6]):
                m = base()
                m["sockets"]["mcp"] = mcp_section()
                m["sockets"]["mcp"]["command"] = ["demo", "--token", s]
                p = problems(m)
                self.assertTrue(any("sockets.mcp.command[2]" in x for x in p), p)
                self.assertFalse(any(s in x for x in p), "a diagnostic echoed the secret")

    def test_secret_inside_server_output_fails_without_echo(self):
        s = self.SECRETS[0]
        m = base()
        m["sockets"]["mcp"] = mcp_section()
        m["sockets"]["mcp"]["tools"][0]["description"] = f"use {s} to call"
        code, out, err = self._cli(m)
        self.assertEqual(code, 1)
        self.assertNotIn(s, out + err)

    def test_host_paths_fail(self):
        for where, val in ((("mcp", "command"), ["/home/someone/.venv/bin/python", "-m", "demo"]),
                           (("skills",), [{"path": "/home/someone/skills/x", "name": "x", "description": "d"}]),
                           (("other",), [{"id": "x", "kind": "folder", "direction": "in",
                                          "location": "C:\\Users\\someone\\inbox", "planned": ""}])):
            with self.subTest(where=where):
                m = base()
                if where[0] == "mcp":
                    m["sockets"]["mcp"] = mcp_section()
                    m["sockets"]["mcp"]["command"] = val
                else:
                    m["sockets"][where[0]] = val
                self.assertTrue(problems(m))

    def test_decoys_pass(self):
        # ordinary words that look a little like the patterns: a relative path, a URL without credentials,
        # a flag with = and lower case, the word "token"
        m = base()
        m["sockets"]["mcp"] = mcp_section()
        m["sockets"]["mcp"]["command"] = ["python3", "-m", "demo", "--mode=read", "--root", "data/sub"]
        m["sockets"]["mcp"]["tools"][0]["description"] = "Reads a token count from https://example.test/api"
        m["sockets"]["other"] = [{"id": "x", "kind": "folder", "direction": "in", "location": "content/inbox",
                                  "planned": "MCP resource"}]
        self.assertEqual(problems(m), [])

    def test_validation_never_launches_the_manifests_command(self):
        m = base()
        m["sockets"]["mcp"] = mcp_section()
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "launched"
            m["sockets"]["mcp"]["command"] = [sys.executable, "-c", f"open({str(marker)!r}, 'w')"]
            f = Path(d) / "m.json"
            f.write_text(json.dumps(m), encoding="utf-8")
            with mock.patch("subprocess.Popen", side_effect=AssertionError("launched")), \
                 mock.patch("os.system", side_effect=AssertionError("launched")):
                run(["manifest", "validate", str(f), "--root", d])
            self.assertFalse(marker.exists())

    def test_secrets_in_notes_and_version_diagnostics_are_not_echoed(self):  # Codex P2 on add4914
        s = self.SECRETS[0]
        for mutate in (lambda m: m["sockets"].__setitem__("other", [{"id": s, "kind": "folder", "direction": "in",
                                                                     "location": "x", "planned": s}]),
                       lambda m: m.__setitem__("manifest", f"telosmith.manifest/{s}"),
                       lambda m: m["sockets"].__setitem__("skills", [{"path": f"skills/{s}", "name": "x",
                                                                      "description": "d"}])):
            with self.subTest(mutate=mutate):
                m = base()
                mutate(m)
                code, out, err = self._cli(m)
                self.assertEqual(code, 1)
                self.assertNotIn(s, out + err)
                self.assertNotIn(s[:12], out + err)  # no prefix either (Copilot on ec34c81: truncation)

    def test_environment_assignment_is_redacted_whole_even_inside_quotes(self):  # Codex P2 on 3dc9165
        for mutate in (lambda m: m["sockets"].__setitem__("other", [{"id": "x", "kind": "folder", "direction": "in",
                                                                     "location": "x", "planned": "API_TOKEN=abc123"}]),
                       lambda m: m.__setitem__("manifest", "API_TOKEN=abc123"),
                       lambda m: m.__setitem__("manifest", "x(DB_PASSWORD=abc123)"),
                       # quoted values (Codex P2 on b4ef850): both quote styles, and an unterminated quote
                       lambda m: m["sockets"].__setitem__("other", [{"id": "x", "kind": "folder", "direction": "in",
                                                                     "location": "x", "planned": 'API_TOKEN="abc123"'}]),
                       lambda m: m["sockets"].__setitem__("other", [{"id": "x", "kind": "folder", "direction": "in",
                                                                     "location": "x", "planned": "API_TOKEN='abc123'"}]),
                       lambda m: m.__setitem__("manifest", 'API_TOKEN="abc123'),
                       lambda m: m.__setitem__("manifest", "API_TOKEN='abc 123'")):
            with self.subTest(mutate=mutate):
                m = base()
                mutate(m)
                code, out, err = self._cli(m)
                self.assertEqual(code, 1)
                self.assertNotIn("bc", out + err)

    def test_copilot_findings_on_ec34c81(self):  # five findings, one subtest each, plus decoys
        def other(**kw):
            return [dict({"id": "x", "kind": "folder", "direction": "in", "location": "x", "planned": ""}, **kw)]
        leaks = {
            # 1. bare sensitive names
            "bare TOKEN=": lambda m: m["sockets"].__setitem__("other", other(planned="TOKEN=abc123")),
            "bare PASSWORD=": lambda m: (m["sockets"].__setitem__("mcp", mcp_section()),
                                         m["sockets"]["mcp"].__setitem__("command", ["demo", "PASSWORD=abc123"])),
            # 2. redact before quoting: a mixed-quote value inside repr()
            "mixed quotes in version": lambda m: m.__setitem__("manifest", "API_TOKEN='abc\"123'"),
            "secret as an unknown key": lambda m: m["tool"].__setitem__("ghp_" + "a" * 36, "x"),
            # 3. credential-shaped dictionary keys inside embedded objects
            "secret key in capabilities": lambda m: (m["sockets"].__setitem__("mcp", mcp_section()),
                                                     m["sockets"]["mcp"]["capabilities"].__setitem__(
                                                         "ghp_" + "b" * 36, {})),
        }
        for name, mutate in leaks.items():
            with self.subTest(name=name):
                m = base()
                mutate(m)
                code, out, err = self._cli(m)
                self.assertEqual(code, 1, name)
                for frag in ("abc", "123", "aaaaaaaa", "bbbbbbbb"):
                    self.assertNotIn(frag, out + err, name)
        # 4. host paths inside --option=value arguments
        for arg in ("--root=/home/alice/data", "--config=C:\\Users\\alice\\c.json", "--x=~/y"):
            with self.subTest(arg=arg):
                m = base()
                m["sockets"]["mcp"] = mcp_section()
                m["sockets"]["mcp"]["command"] = ["demo", arg]
                self.assertTrue(any("host path" in p for p in problems(m)), arg)
        # decoys: relative option values and ordinary names stay valid
        m = base()
        m["sockets"]["mcp"] = mcp_section()
        m["sockets"]["mcp"]["command"] = ["demo", "--root=data/sub", "KEYBOARD=us", "--mode=read"]
        self.assertEqual(problems(m), [])

    def test_nul_in_a_skill_path_is_a_problem_not_a_crash(self):  # Copilot on ec34c81
        m = base()
        m["sockets"]["skills"] = [{"path": "skills/\x00x", "name": "x", "description": "d"}]
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(problems(m, root=Path(d)))
            self.assertTrue(problems(m))

    def test_user_text_is_echoed_only_when_plain(self):  # Codex security review on ec34c81
        # adjacent shell segments (API_TOKEN=""abc123), escapes, and anything with = or quotes are never printed
        for planned in ('API_TOKEN=""abc123', "API_TOKEN=\\abc123", "x=abc123", 'say "abc123"'):
            with self.subTest(planned=planned):
                m = base()
                m["sockets"]["other"] = [{"id": "x", "kind": "folder", "direction": "in", "location": "x",
                                          "planned": planned}]
                _, out, err = self._cli(m)
                self.assertNotIn("abc123", out + err)
        # decoy: plain text is still shown, so the note stays useful
        m = base()
        m["sockets"]["other"] = [{"id": "inbox", "kind": "folder", "direction": "in", "location": "content/",
                                  "planned": "MCP resource"}]
        _, out, _ = self._cli(m)
        self.assertIn("inbox", out)
        self.assertIn("MCP resource", out)

    def _cli(self, m):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "m.json"
            f.write_text(json.dumps(m), encoding="utf-8")
            return run(["manifest", "validate", str(f), "--root", d])


class Skills(unittest.TestCase):
    def test_skill_folders_are_checked_against_root(self):
        with tempfile.TemporaryDirectory() as d:
            m = base()
            m["sockets"]["skills"] = [{"path": "skills/missing", "name": "missing", "description": "d"}]
            self.assertTrue(problems(m, root=Path(d)))
            self.assertEqual(problems(m), [])  # shape only without a root

    def test_skill_name_and_description_must_match_the_folder(self):
        m = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        m["sockets"]["skills"][0]["description"] = "something else"
        self.assertTrue(any("description" in p for p in problems(m, root=ROOT)))

    def test_skill_folder_reached_through_a_symlink_outside_root_fails(self):  # Codex P2 on add4914
        src = ROOT / "examples" / "skills" / "telosmith-records"
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as outside:
            import shutil
            shutil.copytree(src, Path(outside) / "telosmith-records")
            (Path(repo) / "skills").mkdir()
            (Path(repo) / "skills" / "telosmith-records").symlink_to(Path(outside) / "telosmith-records")
            m = json.loads(EXAMPLE.read_text(encoding="utf-8"))
            m["sockets"]["skills"][0]["path"] = "skills/telosmith-records"
            p = problems(m, root=Path(repo))
            self.assertTrue(any("outside" in x for x in p), p)
            # decoy: the same folder copied inside the repository passes
            (Path(repo) / "skills" / "telosmith-records").unlink()
            shutil.copytree(src, Path(repo) / "skills" / "telosmith-records")
            self.assertEqual(problems(m, root=Path(repo)), [])

    def test_skill_path_may_not_climb(self):
        m = base()
        m["sockets"]["skills"] = [{"path": "../x", "name": "x", "description": "d"}]
        self.assertTrue(problems(m))


class Cli(unittest.TestCase):
    def test_example_validates(self):
        code, out, err = run(["manifest", "validate", str(EXAMPLE), "--root", str(ROOT)])
        self.assertEqual(code, 0, err)
        self.assertIn("telosmith.manifest/1.0", out)

    def test_unreadable_file_exits_1(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "m.json"
            f.write_text("{not json", encoding="utf-8")
            code, _, err = run(["manifest", "validate", str(f)])
            self.assertEqual(code, 1)
            self.assertIn("cannot read", err)

    def test_problems_exit_1(self):
        with tempfile.TemporaryDirectory() as d:
            m = base()
            del m["sockets"]["a2a"]
            f = Path(d) / "m.json"
            f.write_text(json.dumps(m), encoding="utf-8")
            code, _, err = run(["manifest", "validate", str(f)])
            self.assertEqual(code, 1)
            self.assertIn("sockets.a2a", err)


if __name__ == "__main__":
    unittest.main()
