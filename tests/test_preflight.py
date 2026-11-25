"""tools/preflight.py reports offline skips as skips, not failures (HO-AEC-20261124-HMM6, Telosmith #114)."""
import importlib.util
import pathlib
import unittest

_p = pathlib.Path(__file__).resolve().parents[1] / "tools" / "preflight.py"
_spec = importlib.util.spec_from_file_location("preflight", _p)
pf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pf)

_spec = importlib.util.spec_from_file_location("install_t", pathlib.Path(__file__).resolve().parent / "test_install.py")
test_install = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(test_install)

VERBOSE = """\
test_pip_install_and_run (test_install.TestInstall.test_pip_install_and_run) ... skipped 'needs internet: package index https://pypi.org/simple/ unreachable (URLError: [Errno -3] Temporary failure in name resolution)'
test_versions_agree (test_install.TestVersionAgreement.test_versions_agree)
pyproject.toml, aec.__version__ and the newest CHANGELOG entry name the same version. ... ok
test_other (test_x.T) ... skipped 'needs specify-cli'
test_quoted (test_y.T.test_quoted)
A docstring line. ... skipped "needs internet: it's down"
"""


class Preflight(unittest.TestCase):
    def test_counts_only_network_skips(self):
        got = pf.network_skips(VERBOSE)
        self.assertEqual([t for t, _ in got], ["test_pip_install_and_run", "test_quoted"])
        self.assertTrue(all(why.startswith("needs internet") for _, why in got))

    def test_no_skips_when_online(self):
        self.assertEqual(pf.network_skips("test_a (m.T.test_a) ... ok\n"), [])

    def test_prefix_matches_the_install_test(self):
        self.assertEqual(pf.NETWORK_SKIP, test_install.NETWORK_SKIP)


if __name__ == "__main__":
    unittest.main()
