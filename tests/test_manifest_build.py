"""aec manifest build|check (DEC-256 item 5 slice 2; docs/integrations/manifest-build.md).

Test list from Kate's round-12 records (independent): AEC-R-manifest-rebuild-drift@2, -cache-policy@2 and
-collection-safety@2, extended by her round-13 test reading of cad2c3c (HO-AEC-20261127-89MY output). A fake MCP 2026-07-28 server (stdlib only, written into each temporary repository) plays the
configured server; its behaviour comes from fake.json beside it.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from aec import manifest_build  # noqa: E402
from aec.__main__ import main  # noqa: E402

FAKE = r'''
import json, os, sys, time
spec = json.load(open("fake.json"))
META = "io.modelcontextprotocol/protocolVersion"
sys.stderr.write("leak: " + os.environ.get("SECRET_FOR_TEST", "absent") + "\n"); sys.stderr.flush()
if spec.get("dump_env"):
    json.dump(dict(os.environ), open("env_seen.json", "w"))
def out(text):  # every stdout line goes through here, so a test can measure them
    if spec.get("log_lengths"):
        open("lengths.txt", "a").write(str(len((text + "\n").encode("utf-8"))) + "\n")
    print(text); sys.stdout.flush()
if spec.get("descendant"):  # a child that inherits stdout and stderr and outlives the server
    import subprocess
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
for line in sys.stdin:
    msg = json.loads(line)
    m, p = msg["method"], msg.get("params", {})
    if spec.get("hang") == m:
        time.sleep(60)
    if spec.get("notify") == m:  # chatter without ever answering
        for _ in range(300):
            print(json.dumps({"jsonrpc": "2.0", "method": "notifications/progress", "params": {}})); sys.stdout.flush()
            time.sleep(0.2)
    if spec.get("garbage") == m:
        print("this is not json GARBAGE-MARKER"); sys.stdout.flush(); continue
    if spec.get("long_line") == m:  # one line of n bytes, no newline until the end
        print("x" * spec["n"]); sys.stdout.flush(); continue
    if spec.get("flood") == m:  # many short notification lines
        for _ in range(spec["n"]):
            print(json.dumps({"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}))
        sys.stdout.flush(); continue
    if spec.get("retarget") == m:  # change the config's target path mid-collection
        c = json.load(open(".aec/config.json")); c["manifest"]["path"] = "moved.json"
        json.dump(c, open(".aec/config.json", "w"))
    if spec.get("exit") == m:
        sys.exit(3)
    if spec.get("error") == m:
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": "boom SECRET"}}))
        sys.stdout.flush(); continue
    if spec.get("big_cursor") == m and not p.get("cursor"):  # a huge cursor, then stop reading stdin
        out(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": [], "nextCursor": "c" * 1000000,
                        "resultType": "complete"}}))
        time.sleep(60)
    if m == "server/discover":
        r = {"supportedVersions": spec.get("versions", ["2026-07-28"]), "capabilities": spec.get("caps", {"tools": {}})}
    else:
        pages = spec["lists"].get(m, [{"items": []}])
        i = int(p.get("cursor") or 0) if spec.get("cursor_kind") != "loop" else 0
        page = pages[i]
        key = {"tools/list": "tools", "resources/list": "resources", "resources/templates/list": "resourceTemplates",
               "prompts/list": "prompts"}[m]
        r = {key: page["items"]}
        r.update(page.get("policy", {}))
        if i + 1 < len(pages):
            r["nextCursor"] = spec.get("cursor_value", str(i + 1))
    r["resultType"] = "incomplete" if spec.get("not_complete") == m else "complete"
    r["_meta"] = {"io.modelcontextprotocol/serverInfo": {"name": "fake", "version": spec.get("version", "1.2.3")}}
    out(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": r}))
    if spec.get("trailing_bytes") == m:  # answer first, then a bad line
        sys.stdout.buffer.write(spec["bytes"].encode("latin-1")); sys.stdout.flush()
    if spec.get("trailing_flood") == m:  # answer first, then overrun
        for _ in range(spec["n"]):
            print(json.dumps({"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}))
        sys.stdout.flush()
        time.sleep(1)
'''

TOOL = {"name": "t1", "description": "first", "inputSchema": {"type": "object"}}
TOOL2 = {"name": "t2", "description": "second", "inputSchema": {"type": "object"}}
POLICY = {"ttlMs": 0, "cacheScope": "public"}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / ".aec").mkdir()
        (self.tmp / "fake_server.py").write_text(FAKE, encoding="utf-8")
        exe = Path(sys.executable)
        path = str(exe.parent) + os.pathsep + os.environ.get("PATH", "")
        env = mock.patch.dict(os.environ, {"PATH": path, "SECRET_FOR_TEST": "hunter2-value"})
        env.start()
        self.addCleanup(env.stop)
        self.config(command=[exe.name, "fake_server.py"])
        self.fake(lists={"tools/list": [{"items": [TOOL], "policy": POLICY}]})

    def config(self, **over):
        sec = {"tool": {"id": "fake", "name": "Fake", "description": "A fake tool."},
               "authority": {"needs": [], "accepts": [], "grants": []},
               "runtime": {"network": "never", "model_calls": "never"}, "other": [], "skills": []}
        if hasattr(self, "sec"):
            sec = self.sec
        sec.update(over)
        self.sec = sec
        (self.tmp / ".aec" / "config.json").write_text(json.dumps({"version": 1, "manifest": sec}), encoding="utf-8")

    def fake(self, **spec):
        (self.tmp / "fake.json").write_text(json.dumps(spec), encoding="utf-8")

    def cmd(self, which, *extra):
        return run(["manifest", which, "--root", str(self.tmp), "--trust-config", *extra])

    def written(self):
        return json.loads((self.tmp / ".aec" / "manifest.json").read_text(encoding="utf-8"))


class Build(Base):
    def test_builds_a_valid_manifest_and_check_passes(self):
        code, out, err = self.cmd("build")
        self.assertEqual(code, 0, err)
        m = self.written()
        self.assertEqual(m["tool"]["version"], "1.2.3")
        self.assertEqual(m["sockets"]["mcp"]["tools"], [TOOL])
        self.assertEqual(m["sockets"]["mcp"]["listPolicy"], {"tools": POLICY})
        self.assertEqual(m["sockets"]["mcp"]["command"], self.sec["command"])
        self.assertIsNone(m["sockets"]["a2a"])
        code, out, err = self.cmd("check")
        self.assertEqual(code, 0, err)

    def test_multi_page_collection_concatenates_in_page_order(self):
        self.fake(lists={"tools/list": [{"items": [TOOL], "policy": POLICY}, {"items": [TOOL2], "policy": POLICY}]})
        self.assertEqual(self.cmd("build")[0], 0)
        self.assertEqual(self.written()["sockets"]["mcp"]["tools"], [TOOL, TOOL2])

    def test_policy_survives_pagination(self):
        self.fake(lists={"tools/list": [{"items": [TOOL], "policy": POLICY}, {"items": [TOOL2], "policy": POLICY}]})
        self.assertEqual(self.cmd("build")[0], 0)
        self.assertEqual(self.written()["sockets"]["mcp"]["listPolicy"], {"tools": POLICY})

    def test_policy_absent_on_every_page_is_left_out(self):
        self.fake(lists={"tools/list": [{"items": [TOOL]}, {"items": [TOOL2]}]})
        self.assertEqual(self.cmd("build")[0], 0)
        self.assertEqual(self.written()["sockets"]["mcp"]["listPolicy"], {})

    def test_advertised_prompts_are_collected(self):
        self.fake(caps={"prompts": {}}, lists={"prompts/list": [{"items": [{"name": "p1"}]}]})
        self.assertEqual(self.cmd("build")[0], 0)
        mcp = self.written()["sockets"]["mcp"]
        self.assertEqual((mcp["prompts"], mcp["tools"]), ([{"name": "p1"}], []))

    def test_unadvertised_lists_are_empty_with_no_policy(self):
        self.cmd("build")
        mcp = self.written()["sockets"]["mcp"]
        self.assertEqual((mcp["resources"], mcp["resourceTemplates"], mcp["prompts"]), ([], [], []))
        self.assertEqual(list(mcp["listPolicy"]), ["tools"])

    def test_advertised_resources_collects_both_resource_lists(self):
        self.fake(caps={"tools": {}, "resources": {}},
                  lists={"tools/list": [{"items": []}], "resources/list": [{"items": [{"uri": "x:/a", "name": "a"}]}],
                         "resources/templates/list": [{"items": [{"uriTemplate": "x:/{n}", "name": "n"}]}]})
        self.assertEqual(self.cmd("build")[0], 0)
        mcp = self.written()["sockets"]["mcp"]
        self.assertEqual(len(mcp["resources"]), 1)
        self.assertEqual(len(mcp["resourceTemplates"]), 1)
        self.assertEqual(mcp["listPolicy"], {})  # no policy on any page: none supplied

    def test_a2a_card_and_skills(self):
        sk = self.tmp / "skills" / "demo-skill"
        sk.mkdir(parents=True)
        (sk / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Does a demo.\n---\nBody\n", encoding="utf-8")
        self.config(a2a={"url": "https://example.test/a2a"}, skills=["skills/demo-skill"])
        code, _, err = self.cmd("build")
        self.assertEqual(code, 0, err)
        m = self.written()
        self.assertEqual(m["sockets"]["a2a"]["agentCard"]["version"], "1.2.3")
        self.assertEqual(m["sockets"]["skills"], [{"path": "skills/demo-skill", "name": "demo-skill",
                                                   "description": "Does a demo."}])


class CollectionFailures(Base):
    """A failed or incomplete collection exits 2 and leaves the committed manifest as it was."""

    def assert_fails_without_writing(self, *, timeout=None, **spec):
        self.assertEqual(self.cmd("build")[0], 0)
        self.fake(**spec)
        before = (self.tmp / ".aec" / "manifest.json").read_bytes()
        with mock.patch.object(manifest_build, "TIMEOUT_S", timeout or manifest_build.TIMEOUT_S):
            for which in ("build", "check"):
                code, out, err = self.cmd(which)
                self.assertEqual(code, 2, (which, out, err))
                self.assertIn("collection failed", err)
                self.assertNotIn("leak", out + err)  # the server's stderr never reaches the output
                # preserved after each invocation, not only after both (Kate, round 13)
                self.assertEqual((self.tmp / ".aec" / "manifest.json").read_bytes(), before, which)
        return err

    def test_json_rpc_error(self):
        err = self.assert_fails_without_writing(lists={}, error="tools/list")
        self.assertNotIn("boom", err)  # the server's message isn't shown

    def test_early_exit(self):
        self.assert_fails_without_writing(lists={}, exit="tools/list")

    def test_timeout(self):
        self.assert_fails_without_writing(timeout=1.0, lists={}, hang="tools/list")

    def test_repeated_cursor(self):
        self.assert_fails_without_writing(lists={"tools/list": [{"items": [TOOL]}, {"items": [TOOL2]}]}, cursor_kind="loop")

    def test_cursor_of_the_wrong_type(self):
        self.assert_fails_without_writing(lists={"tools/list": [{"items": [TOOL]}, {"items": [TOOL2]}]}, cursor_value=7)

    def test_pages_disagree_on_policy(self):
        self.assert_fails_without_writing(lists={"tools/list": [{"items": [TOOL], "policy": POLICY},
                                        {"items": [TOOL2], "policy": {"ttlMs": 5, "cacheScope": "public"}}]})

    def test_policy_on_some_pages_only(self):
        self.assert_fails_without_writing(lists={"tools/list": [{"items": [TOOL], "policy": POLICY}, {"items": [TOOL2]}]})


    def test_policy_types_are_checked_on_every_page(self):
        # 0 == False == 0.0 in Python: the second page's value must fail on its own (Codex on cad2c3c)
        for bad in (False, 0.0):
            self.fake(lists={"tools/list": [{"items": [TOOL], "policy": POLICY}]})
            self.assert_fails_without_writing(lists={"tools/list": [
                {"items": [TOOL], "policy": POLICY}, {"items": [TOOL2], "policy": {"ttlMs": bad, "cacheScope": "public"}}]})

    def test_notifications_do_not_extend_the_deadline(self):
        self.assert_fails_without_writing(timeout=1.0, lists={}, notify="tools/list")

    def test_expired_deadline_stops_consuming_queued_messages(self):
        # past the deadline, already-queued notifications aren't read one by one (Kate, round 14)
        s = object.__new__(manifest_build._Session)
        s.proc, s.next_id, s.overrun = mock.Mock(), 0, None
        s.lines = manifest_build.queue.Queue()
        for _ in range(5):
            s.lines.put(b'{"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}\n')
        clock = iter([0.0, 0.0, 0.0, 1.0, 99.0, 99.0, 99.0, 99.0, 99.0, 99.0, 99.0])
        with mock.patch.object(manifest_build.time, "monotonic", lambda: next(clock)):
            with self.assertRaises(manifest_build.CollectError):
                s.request("tools/list")
        self.assertEqual(s.lines.qsize(), 3)  # two read before the deadline passed, three left

    def test_short_writes_send_the_whole_request(self):
        s = object.__new__(manifest_build._Session)
        s.proc, s.next_id, s.overrun = mock.Mock(), 0, None
        sent = bytearray()

        def short(view):  # at most 7 bytes per call, as a raw pipe may
            sent.extend(bytes(view[:7]))
            return min(7, len(view))
        s.proc.stdin.write.side_effect = short
        s.lines = manifest_build.queue.Queue()
        s.lines.put(b'{"jsonrpc": "2.0", "id": 1, "result": {"resultType": "complete"}}\n')
        s.request("tools/list")
        self.assertEqual(json.loads(bytes(sent))["method"], "tools/list")
        self.assertTrue(sent.endswith(b"\n"))

    def test_reader_still_running_after_exit_fails_the_session(self):
        s = object.__new__(manifest_build._Session)
        s.proc, s.overrun = mock.Mock(), None
        s.proc.poll.return_value = 0
        s.reader = mock.Mock()
        s.reader.is_alive.return_value = True  # a descendant outside the group still holds stdout
        s.lines = manifest_build.queue.Queue()
        with mock.patch.object(manifest_build.os, "killpg", create=True), \
                self.assertRaises(manifest_build.CollectError) as cm:
            s.finish()
        self.assertIn("didn't close", str(cm.exception))

    def test_result_that_is_not_complete(self):
        self.assert_fails_without_writing(lists={"tools/list": [{"items": [TOOL]}]}, not_complete="tools/list")

    def test_line_that_is_not_json(self):
        err = self.assert_fails_without_writing(lists={}, garbage="tools/list")
        self.assertNotIn("GARBAGE-MARKER", err)  # malformed stdout isn't echoed

    def test_empty_cursor(self):
        self.assert_fails_without_writing(lists={"tools/list": [{"items": [TOOL]}, {"items": [TOOL2]}]}, cursor_value="")

    def test_cache_scope_only_conflict(self):
        self.assert_fails_without_writing(lists={"tools/list": [
            {"items": [TOOL], "policy": {"cacheScope": "public"}}, {"items": [TOOL2], "policy": {"cacheScope": "user"}}]})

    def test_per_key_presence_mismatch(self):  # both pages have policy, but not the same keys
        self.assert_fails_without_writing(lists={"tools/list": [
            {"items": [TOOL], "policy": POLICY}, {"items": [TOOL2], "policy": {"ttlMs": 0}}]})

    def test_line_over_the_byte_cap(self):
        with mock.patch.object(manifest_build, "MAX_LINE", 1000):
            err = self.assert_fails_without_writing(lists={}, long_line="tools/list", n=5000)
        self.assertIn("longer than 1000 bytes", err)

    def test_byte_cap_boundary_is_measured(self):
        # the longest reply line, measured as written: exactly the cap passes, one byte under it fails (Kate, round 14)
        self.fake(lists={"tools/list": [{"items": [TOOL]}]}, log_lengths=True)
        self.assertEqual(self.cmd("build")[0], 0)
        longest = max(int(x) for x in (self.tmp / "lengths.txt").read_text().split())
        with mock.patch.object(manifest_build, "MAX_LINE", longest):
            self.assertEqual(self.cmd("build")[0], 0)
        with mock.patch.object(manifest_build, "MAX_LINE", longest - 1):
            code, _, err = self.cmd("build")
        self.assertEqual(code, 2, err)
        self.assertIn(f"longer than {longest - 1} bytes", err)

    def test_server_that_stops_reading_stdin_times_out(self):
        # a 1 MB cursor, then the server stops reading: the next request's write must not block (Codex on 25f2727)
        start = time.monotonic()
        self.assert_fails_without_writing(timeout=1.0, lists={}, big_cursor="tools/list")
        self.assertLess(time.monotonic() - start, 20)

    def test_descendant_holding_the_pipes_does_not_hang_a_failure(self):
        start = time.monotonic()
        self.assert_fails_without_writing(timeout=1.0, lists={}, hang="tools/list", descendant=True)
        self.assertLess(time.monotonic() - start, 20)

    def test_descendant_holding_the_pipes_after_success(self):  # decoy: a clean session with a descendant passes
        if os.name != "posix":
            self.skipTest("process groups are POSIX")
        self.fake(lists={"tools/list": [{"items": [TOOL]}]}, descendant=True)
        start = time.monotonic()
        code, _, err = self.cmd("build")
        self.assertEqual(code, 0, err)
        self.assertLess(time.monotonic() - start, 8)

    def test_bad_line_after_the_last_answer_fails(self):
        for bad in ("\xff\n", "not json\n"):
            self.fake(lists={"tools/list": [{"items": [TOOL], "policy": POLICY}]})
            self.assert_fails_without_writing(lists={"tools/list": [{"items": [TOOL]}]}, trailing_bytes="tools/list",
                                              bytes=bad)

    def test_overrun_after_the_last_answer_still_fails(self):
        # the last list answers, then floods: the sentinel must not be left unread (Kate, round 14)
        with mock.patch.object(manifest_build, "MAX_STDOUT", 20000):
            err = self.assert_fails_without_writing(lists={"tools/list": [{"items": [TOOL]}]},
                                                    trailing_flood="tools/list", n=2000)
        self.assertIn("more than 20000 bytes", err)

    def test_session_over_the_stdout_cap(self):
        with mock.patch.object(manifest_build, "MAX_STDOUT", 20000):
            err = self.assert_fails_without_writing(lists={}, flood="tools/list", n=2000)
        self.assertIn("more than 20000 bytes", err)

    def test_unsupported_protocol_version(self):
        self.assert_fails_without_writing(lists={"tools/list": [{"items": [TOOL]}]}, versions=["2025-11-25"])

    def test_more_pages_than_the_cap(self):
        with mock.patch.object(manifest_build, "MAX_PAGES", 3):
            self.assert_fails_without_writing(lists={"tools/list": [{"items": [TOOL]}] * 4})

    def test_exactly_the_page_cap_passes(self):  # decoy for the cap
        self.fake(lists={"tools/list": [{"items": [TOOL]}] * 3})
        with mock.patch.object(manifest_build, "MAX_PAGES", 3):
            code, _, err = self.cmd("build")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.written()["sockets"]["mcp"]["tools"], [TOOL] * 3)


class Check(Base):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.cmd("build")[0], 0)
        self.path = self.tmp / ".aec" / "manifest.json"

    def edit(self, fn):
        m = self.written()
        fn(m)
        self.path.write_text(json.dumps(m, indent=2), encoding="utf-8")

    def test_reordered_object_keys_pass(self):
        m = self.written()
        self.path.write_text(json.dumps(dict(reversed(list(m.items())))), encoding="utf-8")
        self.assertEqual(self.cmd("check")[0], 0)

    def test_reordered_arrays_fail(self):
        self.fake(lists={"tools/list": [{"items": [TOOL, TOOL2], "policy": POLICY}]})
        self.cmd("build")
        self.edit(lambda m: m["sockets"]["mcp"]["tools"].reverse())
        code, _, err = self.cmd("check")
        self.assertEqual(code, 1)
        self.assertIn("changed: sockets.mcp.tools[0].name", err)

    def test_changed_config_value_fails(self):
        self.config(runtime={"network": "optional", "model_calls": "never"})
        code, _, err = self.cmd("check")
        self.assertEqual(code, 1)
        self.assertIn("changed: runtime.network", err)

    def test_policy_change_fails(self):
        self.fake(lists={"tools/list": [{"items": [TOOL], "policy": {"ttlMs": 60000, "cacheScope": "public"}}]})
        code, _, err = self.cmd("check")
        self.assertEqual(code, 1)
        self.assertIn("changed: sockets.mcp.listPolicy.tools.ttlMs", err)

    def test_policy_appearing_fails(self):
        self.fake(lists={"tools/list": [{"items": [TOOL]}]})
        self.cmd("build")
        self.fake(lists={"tools/list": [{"items": [TOOL], "policy": POLICY}]})
        code, _, err = self.cmd("check")
        self.assertEqual(code, 1)
        self.assertIn("added: sockets.mcp.listPolicy.tools", err)

    def test_changed_config_derived_value_fails(self):  # tool.* is config-derived, not hand-declared
        self.config(tool={"id": "fake", "name": "Fake", "description": "A different description."})
        code, _, err = self.cmd("check")
        self.assertEqual(code, 1)
        self.assertIn("changed: tool.description", err)

    def test_expected_field_deleted_from_the_file_fails(self):
        self.edit(lambda m: m["sockets"]["mcp"].pop("serverInfo"))
        code, _, err = self.cmd("check")
        self.assertEqual(code, 1)
        self.assertIn("added: sockets.mcp.serverInfo", err)

    def test_nested_key_reordering_passes(self):
        self.edit(lambda m: m["sockets"]["mcp"]["tools"].__setitem__(
            0, dict(reversed(list(m["sockets"]["mcp"]["tools"][0].items())))))
        self.assertEqual(self.cmd("check")[0], 0)

    def test_invalid_committed_manifest_fails_on_its_own(self):
        self.edit(lambda m: m.update({"manifest": "0.1"}))
        code, _, err = self.cmd("check")
        self.assertEqual(code, 1)
        self.assertIn("the committed manifest is invalid", err)

    def test_policy_removal_fails(self):
        self.fake(lists={"tools/list": [{"items": [TOOL]}]})
        code, _, err = self.cmd("check")
        self.assertEqual(code, 1)
        self.assertIn("removed: sockets.mcp.listPolicy.tools", err)

    def test_removed_field_fails(self):
        self.edit(lambda m: m["sockets"]["mcp"].update({"x-old": 1}))
        code, _, err = self.cmd("check")
        self.assertEqual(code, 1)
        self.assertIn("removed: sockets.mcp.x-old", err)

    def test_check_never_writes(self):
        # on success, different, invalid, unreadable and refused (Kate, round 13)
        def same(expect):
            before = self.path.read_bytes()
            code = self.cmd("check")[0]
            self.assertEqual((code, self.path.read_bytes()), (expect, before))
        same(0)
        self.fake(lists={"tools/list": [{"items": [TOOL2], "policy": POLICY}]})
        same(1)
        self.path.write_text("{not json", encoding="utf-8")
        same(1)  # unparsable
        self.path.unlink()
        self.path.mkdir()  # unreadable: a directory where the file should be
        code = self.cmd("check")[0]
        self.assertEqual((code, self.path.is_dir(), list(self.path.iterdir())), (1, True, []))
        self.path.rmdir()
        self.fake(lists={"tools/list": [{"items": [TOOL], "policy": POLICY}]})
        self.assertEqual(self.cmd("build")[0], 0)  # a valid committed file again, so the next case reaches refusal
        self.fake(lists={"tools/list": [{"items": [{"name": "t", "description": "API_TOKEN=hunter2-value",
                                                     "inputSchema": {"type": "object"}}]}]})
        before = self.path.read_bytes()  # snapshot before the refusal (Kate, round 15)
        code, _, err = self.cmd("check")
        self.assertEqual((code, self.path.read_bytes()), (1, before))
        self.assertIn("the built manifest is invalid", err)  # the disclosure refusal, not a read error
        before = self.path.read_bytes()
        self.assertEqual(run(["manifest", "check", "--root", str(self.tmp)])[0], 2)
        self.assertEqual(self.path.read_bytes(), before)

    def test_diff_values_are_not_shown(self):
        self.edit(lambda m: m["tool"].update({"description": "TOKEN=abc123 said hello"}))
        code, out, err = self.cmd("check")
        self.assertEqual(code, 1)
        self.assertNotIn("abc123", out + err)


class Safety(Base):
    def test_refuses_without_trust_config(self):
        self.fake(lists={"tools/list": [{"items": [TOOL]}]}, dump_env=True)
        for which in ("build", "check"):
            code, _, err = run(["manifest", which, "--root", str(self.tmp)])
            self.assertEqual(code, 2)
            self.assertIn("--trust-config", err)
        self.assertFalse((self.tmp / "env_seen.json").exists())  # nothing was launched

    def test_manifest_command_is_never_run(self):
        self.cmd("build")
        m = self.written()
        m["sockets"]["mcp"]["command"] = [Path(sys.executable).name, "-c", "open('pwned', 'w')"]
        (self.tmp / ".aec" / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        self.assertEqual(self.cmd("check")[0], 1)
        self.assertFalse((self.tmp / "pwned").exists())

    def test_only_allowlisted_environment_names_pass(self):
        self.fake(lists={"tools/list": [{"items": [TOOL]}]}, dump_env=True)
        self.config(pass_env=["SECRET_FOR_TEST"])
        self.cmd("build")
        seen = json.loads((self.tmp / "env_seen.json").read_text(encoding="utf-8"))
        self.assertIn("SECRET_FOR_TEST", seen)
        self.config(pass_env=[])
        self.cmd("build")
        seen = json.loads((self.tmp / "env_seen.json").read_text(encoding="utf-8"))
        self.assertNotIn("SECRET_FOR_TEST", seen)
        # a literal allow-set, not BASE_ENV, so widening BASE_ENV fails this test (Kate, round 13)
        self.assertTrue(set(seen) <= {"PATH", "SYSTEMROOT", "PWD", "LC_CTYPE", "__CF_USER_TEXT_ENCODING"},
                        sorted(seen))

    def test_subprocess_stderr_is_never_shown(self):
        self.config(pass_env=["SECRET_FOR_TEST"])
        code, out, err = self.cmd("build")
        self.assertEqual(code, 0)
        self.assertNotIn("hunter2", out + err)
        self.assertNotIn("leak", out + err)  # no stderr at all, not only the secret

    def test_skill_path_escape_is_refused(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        (outside / "SKILL.md").write_text("---\nname: x\ndescription: y\n---\n", encoding="utf-8")
        cases = [["../" + outside.name], [str(outside)]]
        try:
            (self.tmp / "skills").symlink_to(outside, target_is_directory=True)
            cases.append(["skills"])
        except (OSError, NotImplementedError):
            pass
        for paths in cases:
            self.config(skills=paths)
            code, _, err = self.cmd("build")
            self.assertEqual(code, 2, (paths, err))
            self.assertFalse((self.tmp / ".aec" / "manifest.json").exists())

    def test_target_comes_from_the_section_the_build_validated(self):
        # the config changing during collection doesn't move the write (Kate, round 13)
        self.fake(lists={"tools/list": [{"items": [TOOL]}]}, retarget="tools/list")
        self.assertEqual(self.cmd("build")[0], 0)
        self.assertTrue((self.tmp / ".aec" / "manifest.json").exists())
        self.assertFalse((self.tmp / "moved.json").exists())

    def test_unknown_authority_key_is_refused(self):
        self.assertEqual(self.cmd("build")[0], 0)
        path = self.tmp / ".aec" / "manifest.json"
        before = path.read_bytes()
        self.fake(lists={"tools/list": [{"items": [TOOL]}]}, dump_env=True)  # env_seen.json would show a launch
        self.config(authority={"needs": [], "accepts": [], "grants": [], "extra": []})
        for which in ("build", "check"):
            code, _, err = self.cmd(which)
            self.assertEqual(code, 2, which)
            self.assertIn("manifest.authority", err)
            self.assertFalse((self.tmp / "env_seen.json").exists(), which)  # refused before launch (Kate, round 16)
            self.assertEqual(path.read_bytes(), before, which)

    def test_a2a_fields_that_come_from_elsewhere_are_refused(self):
        # AEC-R-manifest-config-provenance@1 (Kate): build and check, before collection, bytes kept
        self.assertEqual(self.cmd("build")[0], 0)
        path = self.tmp / ".aec" / "manifest.json"
        before = path.read_bytes()
        self.fake(lists={"tools/list": [{"items": [TOOL]}]}, dump_env=True)  # env_seen.json would show a launch
        bad = [{k: "x"} for k in ("name", "description", "version", "authority")]  # a literal set, not the constant
        bad.append({"no_such_card_argument": True})
        for extra in bad:
            self.config(a2a={"url": "https://example.test/a2a", **extra})
            for which in ("build", "check"):
                code, _, err = self.cmd(which)
                self.assertEqual(code, 2, (extra, which))
                self.assertIn("manifest.a2a", err)
                self.assertFalse((self.tmp / "env_seen.json").exists(), extra)  # refused before anything starts
                self.assertEqual(path.read_bytes(), before)

    def test_reserved_card_fields_come_from_their_sources(self):
        # values that differ from the fixture defaults, so agreement can't pass for derivation (Kate, round 16)
        self.fake(lists={"tools/list": [{"items": [TOOL]}]}, version="4.5.6")
        self.config(a2a={"url": "https://example.test/a2a"},
                    tool={"id": "other", "name": "Other Name", "description": "Another description."},
                    authority={"needs": ["x.read"], "accepts": ["y.call"], "grants": ["z.do"]})
        self.assertEqual(self.cmd("build")[0], 0)
        m = self.written()
        card = m["sockets"]["a2a"]["agentCard"]
        self.assertEqual((card["name"], card["description"], card["version"]),
                         ("Other Name", "Another description.", "4.5.6"))
        ext = card["capabilities"]["extensions"]
        self.assertEqual(len(ext), 1)
        self.assertEqual({k: ext[0]["params"][k] for k in ("needs", "accepts", "grants")},
                         {"needs": ["x.read"], "accepts": ["y.call"], "grants": ["z.do"]})
        self.assertEqual({k: m["sockets"]["authority"][k] for k in ("needs", "accepts", "grants")},
                         {"needs": ["x.read"], "accepts": ["y.call"], "grants": ["z.do"]})

    def test_missing_authority_keys_default_to_empty_lists(self):
        self.config(authority={"needs": ["x.read"]})
        self.assertEqual(self.cmd("build")[0], 0)
        auth = self.written()["sockets"]["authority"]
        self.assertEqual((auth["needs"], auth["accepts"], auth["grants"]), (["x.read"], [], []))

    def test_write_failure_reports_the_type_and_keeps_the_old_file(self):
        self.assertEqual(self.cmd("build")[0], 0)
        path = self.tmp / ".aec" / "manifest.json"
        before = path.read_bytes()
        self.fake(lists={"tools/list": [{"items": [TOOL2]}]})
        with mock.patch.object(manifest_build.os, "replace", side_effect=PermissionError(13, "denied", str(self.tmp))):
            code, out, err = self.cmd("build")
        self.assertEqual(code, 2)
        self.assertIn("PermissionError", err)
        self.assertNotIn(str(self.tmp), out + err)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list((self.tmp / ".aec").glob("*.tmp")), [])

    def test_secret_shaped_server_output_refuses_the_write(self):
        self.fake(lists={"tools/list": [{"items": [{"name": "t", "description": "API_TOKEN=hunter2-value",
                                                     "inputSchema": {"type": "object"}}]}]})
        code, out, err = self.cmd("build")
        self.assertEqual(code, 1)
        self.assertNotIn("hunter2", out + err)
        self.assertFalse((self.tmp / ".aec" / "manifest.json").exists())

    def test_manifest_path_symlinked_outside_is_refused(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        try:
            (self.tmp / "out").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self.config(path="out/manifest.json")
        self.assertEqual(self.cmd("build")[0], 2)
        self.assertFalse((outside / "manifest.json").exists())

    def test_non_list_skills_is_a_config_error_not_a_crash(self):
        for bad in (None, 3):
            self.config(skills=bad)
            code, _, err = self.cmd("build")
            self.assertEqual(code, 2, err)
            self.assertIn("manifest.skills", err)

    def test_config_errors_follow_the_plain_text_rule(self):
        self.config(**{"private=value-that-must-not-be-shown": 1})
        code, out, err = self.cmd("build")
        self.assertEqual(code, 2)
        self.assertNotIn("value-that-must-not-be-shown", out + err)
        self.assertIn("[not shown]", err)

    def test_symlinked_config_is_refused_before_launch(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        marker = outside / "victim-marker"
        cmd = [Path(sys.executable).name, "-c", f"open({str(marker)!r}, 'w')"]
        (outside / "config.json").write_text(json.dumps({"version": 1, "manifest": dict(self.sec, command=cmd)}),
                                             encoding="utf-8")
        cfg = self.tmp / ".aec" / "config.json"
        cfg.unlink()
        try:
            cfg.symlink_to(outside / "config.json")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        for which in ("build", "check"):
            code, _, err = self.cmd(which)
            self.assertEqual(code, 2, err)
            self.assertIn("symlink", err)
        self.assertFalse(marker.exists())

    def test_missing_section_is_a_config_error(self):
        (self.tmp / ".aec" / "config.json").write_text(json.dumps({"version": 1}), encoding="utf-8")
        code, _, err = self.cmd("build")
        self.assertEqual(code, 2)
        self.assertIn("manifest", err)


if __name__ == "__main__":
    unittest.main()
