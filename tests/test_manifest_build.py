"""aec manifest build|check (DEC-256 item 5 slice 2; docs/integrations/manifest-build.md).

Test list from Kate's round-12 records (independent): AEC-R-manifest-rebuild-drift@2, -cache-policy@2 and
-collection-safety@2. A fake MCP 2026-07-28 server (stdlib only, written into each temporary repository) plays the
configured server; its behaviour comes from fake.json beside it.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
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
for line in sys.stdin:
    msg = json.loads(line)
    m, p = msg["method"], msg.get("params", {})
    if spec.get("hang") == m:
        time.sleep(60)
    if spec.get("exit") == m:
        sys.exit(3)
    if spec.get("error") == m:
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": "boom SECRET"}}))
        sys.stdout.flush(); continue
    if m == "server/discover":
        r = {"supportedVersions": ["2026-07-28"], "capabilities": spec.get("caps", {"tools": {}})}
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
    r["resultType"] = "complete"
    r["_meta"] = {"io.modelcontextprotocol/serverInfo": {"name": "fake", "version": spec.get("version", "1.2.3")}}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": r})); sys.stdout.flush()
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
        self.assertEqual((self.tmp / ".aec" / "manifest.json").read_bytes(), before)
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
        self.fake(lists={"tools/list": [{"items": [TOOL2], "policy": POLICY}]})
        before = self.path.read_bytes()
        self.assertEqual(self.cmd("check")[0], 1)
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
        self.assertTrue(set(seen) <= set(manifest_build.BASE_ENV) | {"PWD", "LC_CTYPE", "__CF_USER_TEXT_ENCODING"},
                        sorted(seen))

    def test_subprocess_stderr_is_never_shown(self):
        self.config(pass_env=["SECRET_FOR_TEST"])
        code, out, err = self.cmd("build")
        self.assertEqual(code, 0)
        self.assertNotIn("hunter2", out + err)

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

    def test_missing_section_is_a_config_error(self):
        (self.tmp / ".aec" / "config.json").write_text(json.dumps({"version": 1}), encoding="utf-8")
        code, _, err = self.cmd("build")
        self.assertEqual(code, 2)
        self.assertIn("manifest", err)


if __name__ == "__main__":
    unittest.main()
