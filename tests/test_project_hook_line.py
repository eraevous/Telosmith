"""The one-line project hook (`aec init --hook-style line`) behaves like the inline hook it would replace.

AEC-D-braided-dcc@1, propagation D: the hook body moves into the package (`aec hook project`), so a body fix
ships with a Telosmith release instead of a settings edit in every repository. Kate's gate for replacing any
repository's hook includes "compatibility tests show the same exit behaviour as today's hook"; these run both
hooks on the same checkouts and compare. They also cover the line's pre-import gate (Kate's
AEC-R-hook-launcher-preimport@1 and AEC-R-hook-line-pin-gate@1, under AEC-D-pin-check-scope@1): the line runs only
an aec pip-installed from git at the commit in tools/aec_upstream.json, and checks that before any aec code runs.
Each test builds such an install from this checkout's src/aec plus PEP 610 metadata.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from _platform import BASH, NO_BASH
from _platform import rmtree as force_rmtree

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = str(ROOT / "src")
sys.path.insert(0, SRC)

from aec.init import HOOK, HOOK_COMMAND, HOOK_LINE, HOOK_LINE_COMMAND, HOOK_LINE_GATE, init  # noqa: E402

PIN = "0123456789abcdef0123456789abcdef01234567"
OTHER = "fedcba9876543210fedcba9876543210fedcba98"


def install(site, commit=PIN, *, vcs="git", editable=False, direct_url=True, package=None):
    """A pip-installed telosmith in `site`: the aec package (this checkout's, or `package`) and a dist-info with
    PEP 610 direct_url.json naming `commit`."""
    site.mkdir(parents=True, exist_ok=True)
    if package is None:
        shutil.copytree(pathlib.Path(SRC) / "aec", site / "aec", ignore=shutil.ignore_patterns("__pycache__"))
    else:
        shutil.copytree(package, site / "aec")
    info = site / "telosmith-0.5.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: telosmith\nVersion: 0.5.0\n")
    if direct_url:
        data = {"url": "https://github.com/eraevous/Telosmith.git"}
        if editable:
            data["dir_info"] = {"editable": True}
        else:
            data["vcs_info"] = {"vcs": vcs, "commit_id": commit}
        (info / "direct_url.json").write_text(json.dumps(data))
    return site


FORMS = {"inline": HOOK_COMMAND, "line": HOOK_LINE_COMMAND}


class Checkout(unittest.TestCase):
    """A git checkout with Telosmith set up, its pin file, and a pinned install of this checkout's aec."""

    def setUp(self):
        self._dirs = [tempfile.TemporaryDirectory() for _ in range(2)]
        self.project = pathlib.Path(self._dirs[0].name).resolve()
        self.outside = pathlib.Path(self._dirs[1].name).resolve()
        (self.project / "pkg").mkdir()
        (self.project / "pkg" / "__init__.py").write_text("def f():\n    return 1\n")
        (self.project / "tools").mkdir()
        (self.project / "tools" / "aec_upstream.json").write_text(json.dumps({"commit": PIN}))
        self.site = install(self.outside / "site")
        init(self.project, owner="tester", hooks=True)
        self._git("init", "-q")
        # No background maintenance: newer Git (macOS runners) detaches `maintenance run --auto` after a commit,
        # and its maintenance.lock can vanish mid-copytree in _both (CI on #111).
        self._git("config", "maintenance.auto", "false")
        self._git("config", "gc.auto", "0")
        self._commit("init")

    def tearDown(self):
        for d in self._dirs:
            d.cleanup()

    def _git(self, *args):
        subprocess.run(["git", "-C", str(self.project), *args], check=True, capture_output=True)

    def _commit(self, msg):
        self._git("add", "-A")
        self._git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)

    def _run(self, command, pythonpath="", project=None, env_extra=None):
        pythonpath = str(self.site) if pythonpath == "" else pythonpath
        # An empty user base by default, so the runner's own ~/.local can't change a result.
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project or self.project),
                   PYTHONUSERBASE=str(self.outside / "userbase"))
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONNOUSERSITE", None)
        env.update(env_extra or {})
        if pythonpath is not None:
            env["PYTHONPATH"] = pythonpath
        return subprocess.run([BASH, "-c", command], env=env, capture_output=True, text=True, timeout=120)

    def _both(self):
        # Each form runs on its own restored copy of the checkout, so one form's outputs can't shape the other's
        # result (Kate, AEC-R-hook-project-parity@1). Symlinks are copied as links, pointing where they did.
        done = {}
        for name, cmd in FORMS.items():
            copy = pathlib.Path(self._dirs[0].name + "-" + name)
            shutil.copytree(self.project, copy, symlinks=True)
            try:
                done[name] = self._run(cmd, project=copy)
            finally:
                force_rmtree(copy)
        return done

    def assertSameExit(self, expected):
        done = self._both()
        for name, d in done.items():
            self.assertEqual(d.returncode, expected, f"{name}: {d.stderr}")
        return done


@unittest.skipUnless(BASH and shutil.which("git"), NO_BASH + "; and git")
class SideBySide(Checkout):
    def test_clean_checkout_is_quiet(self):
        self.assertSameExit(0)

    def test_record_check_failure_reports_2(self):
        with open(self.project / ".aec" / "records.jsonl", "a") as fh:
            fh.write(json.dumps({"id": "R-1", "version": 1, "type": "requirement", "text": "x",
                                 "relations": [{"rel": "depends_on", "to": "NOPE@1"}]}) + "\n")
        done = self.assertSameExit(2)
        self.assertEqual(done["inline"].stderr, done["line"].stderr)

    def test_linked_code_change_reports_2(self):
        rec = {"id": "R-1", "version": 1, "type": "requirement", "text": "f returns 1",
               "relations": [{"rel": "implemented_by", "to": "code:pkg.f"}]}
        with open(self.project / ".aec" / "records.jsonl", "a") as fh:
            fh.write(json.dumps(rec) + "\n")
        self._commit("record")
        (self.project / "pkg" / "__init__.py").write_text("def f():\n    return 2\n")
        done = self.assertSameExit(2)
        self.assertEqual(done["inline"].stderr, done["line"].stderr)
        self.assertIn("R-1@1", done["line"].stderr)

    def test_symlinked_outputs_are_refused_by_both(self):
        victim = self.outside / "bashrc"
        for rel in (".aec/edges.jsonl", ".aec/hook-before.jsonl"):
            victim.write_text("keep\n")
            path = self.project / rel
            if os.path.lexists(path):
                path.unlink()
            path.symlink_to(victim)
            done = self.assertSameExit(2)
            self.assertTrue(all("symlink" in d.stderr for d in done.values()), rel)
            self.assertEqual(victim.read_text(), "keep\n")
            path.unlink()

    def test_symlinked_aec_dir_and_records_are_refused_by_both(self):
        # .aec itself and the records file, each separately; nothing behind the link is written.
        aec = self.project / ".aec"
        shutil.copytree(aec, self.outside / "aec-real")
        before = {f.name: f.read_bytes() for f in (self.outside / "aec-real").iterdir() if f.is_file()}
        shutil.rmtree(aec)
        aec.symlink_to(self.outside / "aec-real")
        done = self.assertSameExit(2)
        self.assertTrue(all("symlink" in d.stderr for d in done.values()))
        after = {f.name: f.read_bytes() for f in (self.outside / "aec-real").iterdir() if f.is_file()}
        self.assertEqual(after, before)
        aec.unlink()
        shutil.copytree(self.outside / "aec-real", aec)

        records = aec / "records.jsonl"
        real = self.outside / "records.jsonl"
        real.write_bytes(records.read_bytes())
        records.unlink()
        records.symlink_to(real)
        kept = real.read_bytes()
        done = self.assertSameExit(2)
        self.assertTrue(all("symlink" in d.stderr for d in done.values()))
        self.assertEqual(real.read_bytes(), kept)

    def test_dangling_output_links_are_refused_and_never_created(self):
        for rel in (".aec/edges.jsonl", ".aec/hook-before.jsonl"):
            target = self.outside / ("missing-" + rel.replace("/", "_"))
            path = self.project / rel
            if os.path.lexists(path):
                path.unlink()
            path.symlink_to(target)
            done = self.assertSameExit(2)
            self.assertTrue(all("symlink" in d.stderr for d in done.values()), rel)
            self.assertFalse(os.path.lexists(target), rel)
            path.unlink()

    def test_output_that_cannot_be_replaced_exits_like_inline(self):
        # A directory where an output file goes: the inline hook's `aec ... -o <dir>` fails and takes its
        # failure branch; the line must take the same branch, not raise (Copilot on #89).
        for rel in (".aec/hook-before.jsonl", ".aec/edges.jsonl"):
            path = self.project / rel
            if os.path.lexists(path):
                path.unlink()
            path.mkdir()
            done = self._both()
            self.assertEqual(done["inline"].returncode, done["line"].returncode,
                             f"{rel}: inline {done['inline'].stderr!r} line {done['line'].stderr!r}")
            self.assertNotIn("Traceback", done["line"].stderr, rel)
            path.rmdir()

    def test_no_aec_importable_gets_its_own_message(self):
        # Probe the way the launcher does (from /, PYTHONPATH cleared): an installed aec of any version makes
        # the missing-install path unreachable, so skip rather than read its "old aec" diagnostic as a failure.
        probe = subprocess.run(["python3", "-c",
                                "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('aec') else 1)"],
                               cwd="/", env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
                               capture_output=True)
        if probe.returncode == 0:
            self.skipTest("an aec is installed for the launcher's python3; the missing-install path is not reachable")
        done = self._run(HOOK_LINE_COMMAND, pythonpath=None)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("no aec is importable", done.stderr)

    def test_aec_without_hook_project_gets_its_own_message(self):
        fake = self.outside / "old"
        (fake / "aec").mkdir(parents=True)
        (fake / "aec" / "__init__.py").write_text("")
        (fake / "aec" / "__main__.py").write_text("import sys\nsys.exit(2)\n")
        site = install(self.outside / "oldsite", package=fake / "aec")
        done = self._run(HOOK_LINE_COMMAND, pythonpath=str(site))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("the pinned aec has no hook project", done.stderr)

    def test_line_is_short_and_carries_no_body(self):
        # The pre-import gate has to be settings text (nothing it checks may run first); the rest of the line
        # stays shorter than the inline hook.
        self.assertLess(len(HOOK_LINE_COMMAND) - len(HOOK_LINE_GATE), len(HOOK_COMMAND))
        for step in ("aec edges", "aec check", "aec snapshot", "code-impact"):
            self.assertNotIn(step, HOOK_LINE_COMMAND)
        self.assertIn("sys.argv=['aec','hook','project',P]", HOOK_LINE_GATE)


@unittest.skipUnless(BASH and shutil.which("git"), NO_BASH + "; and git")
class PreImportGate(Checkout):
    """The line runs `aec hook project` only for an aec pip-installed from git at the pinned commit, and decides
    that before any aec code, or any code on an environment import path, runs."""

    def line(self, pythonpath="", **kw):
        return self._run(HOOK_LINE_COMMAND, pythonpath=pythonpath, **kw)

    def refused(self, done, text):
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn(text, done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def planted(self, directory, name):
        """A module in `directory` that drops a marker file when it is imported."""
        marker = self.outside / f"ran-{name.replace('/', '-')}"
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"open({str(marker)!r}, 'w').close()\n")
        return marker

    def test_pinned_install_runs(self):
        done = self.line()
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_pin_file_missing_symlinked_or_not_a_full_commit_is_refused(self):
        pin = self.project / "tools" / "aec_upstream.json"
        real = self.outside / "pin.json"
        real.write_text(json.dumps({"commit": PIN}))
        cases = {
            "missing": None, "abbreviated": {"commit": PIN[:12]}, "tag": {"commit": "v0.5.0"},
            "uppercase": {"commit": PIN.upper()}, "no commit": {"other": PIN}, "list": [PIN], "symlink": "link",
        }
        for name, content in cases.items():
            with self.subTest(name):
                pin.unlink(missing_ok=True)
                if content == "link":
                    pin.symlink_to(real)
                elif content is not None:
                    pin.write_text(json.dumps(content))
                self.refused(self.line(), "names no full commit")
        pin.unlink()
        pin.write_text("{not json")
        self.refused(self.line(), "names no full commit")

    def test_install_that_is_not_the_pinned_git_commit_is_refused(self):
        variants = {
            "other commit": dict(commit=OTHER), "abbreviated commit": dict(commit=PIN[:12]),
            "hg": dict(vcs="hg"), "editable": dict(editable=True), "no direct_url": dict(direct_url=False),
        }
        for name, kwargs in variants.items():
            with self.subTest(name):
                site = install(self.outside / f"site-{name.replace(' ', '-')}", **kwargs)
                self.refused(self.line(str(site)), "is not a non-editable pip install from git of the pinned commit")

    def test_wrong_commit_names_expected_and_installed_and_the_fix(self):
        # Kate, DBN5 round 14: a git install at the wrong commit exits 1 naming both revisions and the pinned
        # pip command.
        site = install(self.outside / "site-wrong", commit=OTHER)
        done = self.line(str(site))
        self.refused(done, f"pinned commit {PIN[:12]} (tools/aec_upstream.json; installed: {OTHER[:12]})")
        self.assertIn(f"pip install git+https://github.com/eraevous/Telosmith.git@{PIN}", done.stderr)

    def _user_site(self):
        """The user site `python3 -I` would compute under this test's PYTHONUSERBASE, or skip in a venv."""
        probe = subprocess.run(
            ["python3", "-I", "-c", "import site,sys;print(sys.prefix==sys.base_prefix);print(site.getusersitepackages())"],
            env=dict(os.environ, PYTHONUSERBASE=str(self.outside / "userbase")), capture_output=True, text=True)
        plain, path = probe.stdout.split("\n")[:2]
        if plain != "True":
            self.skipTest("python3 on PATH is a virtual environment; it has no user site")
        return pathlib.Path(path)

    def test_pinned_user_site_install_runs(self):
        # Codex P2 on MtG#59: -I hides `pip install --user`; the gate adds the user site back as a plain path.
        user = install(self._user_site())
        marker = self.outside / "ran-user-pth"
        (user / "evil.pth").write_text(f"import os; open({str(marker)!r}, 'w').close()\n")
        usercustom = self.planted(user, "usercustomize.py")
        done = self.line(None)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(marker.exists() or usercustom.exists(), "user-site startup code ran")

    def test_user_site_install_at_the_wrong_commit_is_refused(self):
        install(self._user_site(), commit=OTHER)
        self.refused(self.line(None), f"installed: {OTHER[:12]}")

    def test_pythonnousersite_keeps_the_user_site_out(self):
        install(self._user_site())
        self.refused(self.line(None, env_extra={"PYTHONNOUSERSITE": "1"}), "no aec is importable here")

    def test_malformed_provenance_shapes_get_the_one_line_diagnostic(self):
        # Copilot on #92: valid JSON of the wrong shape must not end in a traceback.
        shapes = {"null": None, "list": [], "string": "x", "vcs_info list": {"vcs_info": []},
                  "dir_info list": {"dir_info": [], "vcs_info": {"vcs": "git", "commit_id": PIN}},
                  "vcs_info string": {"vcs_info": "git"}, "invalid json": "{nope"}
        for name, data in shapes.items():
            with self.subTest(name):
                site = install(self.outside / f"shape-{name.replace(' ', '-')}")
                text = data if name == "invalid json" else json.dumps(data)
                (site / "telosmith-0.5.0.dist-info" / "direct_url.json").write_text(text)
                self.refused(self.line(str(site)), "is not a non-editable pip install from git of the pinned commit")

    def test_source_checkout_is_refused_before_its_code_runs(self):
        # Kate's case: an ignored shadow package in a writable checkout (src/aec/records/__init__.py) must not run.
        checkout = self.outside / "checkout" / "src"
        shutil.copytree(pathlib.Path(SRC) / "aec", checkout / "aec", ignore=shutil.ignore_patterns("__pycache__"))
        shadow = self.planted(checkout, "aec/records/__init__.py")
        top = self.planted(checkout, "aec/__init__.py")
        done = self.line(str(checkout))
        self.refused(done, "is not a non-editable pip install from git of the pinned commit")
        self.assertFalse(shadow.exists() or top.exists(), "checkout code ran before the gate decided")

    def test_shadow_aec_earlier_on_the_path_is_refused_without_running(self):
        shadow_dir = self.outside / "shadow"
        marker = self.planted(shadow_dir, "aec/__init__.py")
        done = self.line(os.pathsep.join([str(shadow_dir), str(self.site)]))
        self.refused(done, "is not a non-editable pip install")
        self.assertFalse(marker.exists())

    def test_startup_hooks_on_environment_paths_do_not_run(self):
        # PYTHONPATH entries are appended after the gate's isolated start, so sitecustomize, usercustomize and .pth
        # files there never run, and they can't shadow the standard library the gate or aec imports.
        extra = self.outside / "extra"
        markers = [self.planted(extra, n) for n in ("sitecustomize.py", "usercustomize.py", "json.py", "re.py")]
        (extra / "evil.pth").write_text(f"import os; open({str(self.outside / 'ran-pth')!r}, 'w').close()\n")
        done = self.line(os.pathsep.join([str(extra), str(self.site)]))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([m.name for m in markers if m.exists()], [])
        self.assertFalse((self.outside / "ran-pth").exists())

    def test_working_directory_and_project_cannot_supply_the_gate_or_aec(self):
        # The project is filtered from PYTHONPATH and the gate starts from / in isolated mode: a pinned-looking
        # install inside the project is never found.
        inside = install(self.project / "vendor")
        marker = self.planted(self.project, "json.py")
        done = self.line(str(inside))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertFalse(marker.exists())

    def test_missing_python_capability_fails_closed(self):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.project), PATH="/nonexistent")
        done = subprocess.run([BASH, "-c", HOOK_LINE_COMMAND], env=env, capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)
        self.assertNotEqual(done.returncode, 2)


class InitStyles(unittest.TestCase):
    def test_default_stays_inline_and_line_is_opt_in(self):
        for style, expected in ((None, HOOK), ("inline", HOOK), ("line", HOOK_LINE)):
            with tempfile.TemporaryDirectory() as d:
                kwargs = {} if style is None else {"hook_style": style}
                init(d, owner="t", hooks=True, **kwargs)
                got = json.loads((pathlib.Path(d) / ".aec" / "snippets" / "claude-settings.json").read_text())
                self.assertEqual(got, expected, style)

    def test_unknown_style_is_refused_before_writing(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                init(d, owner="t", hooks=True, hook_style="bogus")
            self.assertFalse((pathlib.Path(d) / ".aec").exists())


if __name__ == "__main__":
    unittest.main()
