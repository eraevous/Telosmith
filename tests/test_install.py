"""T029 / FR-009: the package installs into a clean venv and runs; only `aec` is shipped (T028)."""
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Skip reasons that start with this text mean "this machine is offline", not "this test is broken";
# tools/preflight.py counts them separately in its summary. Keep the two in step.
NETWORK_SKIP = "needs internet"


def index_url() -> str:
    """The package index pip would use: PIP_INDEX_URL if set, else PyPI's simple index."""
    return os.environ.get("PIP_INDEX_URL") or "https://pypi.org/simple/"


def index_unreachable(url: str | None = None, timeout: float = 5.0) -> str | None:
    """None if the package index answers within `timeout` seconds, else a one-line reason.

    `pip install .` builds in an isolated environment and fetches setuptools from the index, so without the
    index the install test can only fail. Any HTTP answer (even an error status) counts as reachable: the
    network path works, and a real index problem should still show up as a failing install.
    """
    url = url or index_url()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=timeout):
            return None
    except urllib.error.HTTPError:
        return None
    except (urllib.error.URLError, OSError, ValueError) as e:
        return f"{type(e).__name__}: {getattr(e, 'reason', e)}"


def install_skip_reason() -> str | None:
    """Why the install test should skip here, or None to run it.

    Under CI (the CI variable is set, as on GitHub Actions) it never skips for the network: an unreachable
    index there is a failure to see, not a newcomer's offline machine.
    """
    if os.environ.get("AEC_SKIP_INSTALL_TEST"):
        return "install test disabled (AEC_SKIP_INSTALL_TEST)"
    if os.environ.get("CI"):
        return None
    why = index_unreachable()
    if why:
        return f"{NETWORK_SKIP}: package index {index_url()} unreachable ({why})"
    return None


class TestInstall(unittest.TestCase):
    def test_pip_install_and_run(self):
        why = install_skip_reason()
        if why:
            self.skipTest(why)
        d = Path(tempfile.mkdtemp())
        subprocess.run([sys.executable, "-m", "venv", str(d / "v")], check=True)
        py = d / "v" / ("Scripts" if os.name == "nt" else "bin") / "python"
        r = subprocess.run([str(py), "-m", "pip", "install", "-q", str(ROOT)], capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        r = subprocess.run([str(py), "-m", "aec", "edges", str(ROOT / "tests" / "fixtures" / "edges_pkg_v1")],
                           capture_output=True, text=True, cwd=d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"aec_edges": 1', r.stdout.splitlines()[0])
        # The console script is installed and agrees with the package version (v0.4 readiness).
        from importlib import util
        spec = util.spec_from_file_location("aec_pkg", ROOT / "src" / "aec" / "__init__.py")
        mod = util.module_from_spec(spec); spec.loader.exec_module(mod)
        for name in ("telosmith", "aec"):  # the product name, and its pre-0.5 alias
            exe = py.parent / (name + ".exe" if os.name == "nt" else name)
            r = subprocess.run([str(exe), "--version"], capture_output=True, text=True, cwd=d)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), f"{name} {mod.__version__}")
        r = subprocess.run([str(py), "-c", "import core"], capture_output=True, text=True, cwd=d)
        self.assertNotEqual(r.returncode, 0, "legacy top-level 'core' package must not be installed")


class TestInstallSkip(unittest.TestCase):
    """The install test skips cleanly offline, and only offline (HO-AEC-20261124-HMM6, Telosmith #114)."""

    def setUp(self):
        keys = ("AEC_SKIP_INSTALL_TEST", "CI", "PIP_INDEX_URL", "NO_PROXY", "no_proxy")
        self._env = {k: os.environ.get(k) for k in keys}
        for k in keys[:3]:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_unreachable_index_skips_with_network_reason(self):
        # Port 9 on loopback (discard) has no listener here: the connection is refused at once, no network used.
        os.environ["PIP_INDEX_URL"] = "http://127.0.0.1:9/simple/"
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1"
        why = install_skip_reason()
        self.assertIsNotNone(why)
        self.assertTrue(why.startswith(NETWORK_SKIP + ":"), why)
        self.assertIn("127.0.0.1:9", why)

    def test_reachable_index_runs(self):
        import http.server
        import threading
        class Quiet(http.server.BaseHTTPRequestHandler):
            def do_HEAD(self):
                self.send_response(404)
                self.end_headers()

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), Quiet)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            os.environ["PIP_INDEX_URL"] = f"http://127.0.0.1:{srv.server_port}/simple/"  # a 404 still answers
            os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1"
            self.assertIsNone(install_skip_reason())
        finally:
            srv.shutdown()
            srv.server_close()

    def test_ci_never_skips_for_network(self):
        os.environ["PIP_INDEX_URL"] = "http://127.0.0.1:9/simple/"
        os.environ["CI"] = "true"
        self.assertIsNone(install_skip_reason())

    def test_explicit_opt_out_still_works(self):
        os.environ["AEC_SKIP_INSTALL_TEST"] = "1"
        why = install_skip_reason()
        self.assertIsNotNone(why)
        self.assertFalse(why.startswith(NETWORK_SKIP), why)


class TestVersionAgreement(unittest.TestCase):
    """pyproject.toml, aec.__version__ and the newest CHANGELOG entry name the same version."""

    def test_versions_agree(self):
        import re
        toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        pkg = (ROOT / "src" / "aec" / "__init__.py").read_text(encoding="utf-8")
        log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        v_toml = re.search(r'^version = "([^"]+)"', toml, re.M).group(1)
        v_pkg = re.search(r'__version__ = "([^"]+)"', pkg).group(1)
        v_log = re.search(r"^## \[?v?(\d+\.\d+\.\d+)", log, re.M).group(1)
        self.assertEqual(v_toml, v_pkg)
        self.assertEqual(v_toml, v_log)


if __name__ == "__main__":
    unittest.main()
