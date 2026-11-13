"""Validation of `.aec/extraction.json` (snapshots.configuration).

The extraction config decides which files feed the edge graph, so a bad value
must be refused rather than silently widening or narrowing the scan. Before
this file only one refusal (an absolute source root) was exercised, through a
full git snapshot. These tests call `configuration()` directly on a plain
directory: no git, no extraction, one refusal per test.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from aec import edges as E
from aec import snapshots as S


class ExtractionConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'
        (self.root / '.aec').mkdir(parents=True)
        self.path = self.root / S.CONFIG

    def write(self, data):
        self.path.write_text(data if isinstance(data, str) else json.dumps(data), encoding='utf-8')

    def refused(self, message=None, **kwargs):
        with self.assertRaises(ValueError) as caught:
            S.configuration(self.root, **kwargs)
        if message:
            self.assertIn(message, str(caught.exception))
        return caught.exception

    # Accepted shapes ---------------------------------------------------

    def test_missing_config_gives_defaults(self):
        method = S.configuration(self.root)
        self.assertEqual(method['source_roots'], 'auto')
        self.assertEqual(method['ignore'], sorted(E.DEFAULT_IGNORE))
        self.assertEqual(method['tool_version'], E.TOOL_VERSION)
        self.assertEqual(set(method), {'tool_version', 'ignore', 'source_roots',
                                       'python_ast', 'resolution_names_sha'})

    def test_ignore_merges_defaults_file_and_caller_sorted_without_duplicates(self):
        self.write({'ignore': ['build/', 'docs/', 'build/']})
        method = S.configuration(self.root, ignore=['docs/', 'vendor/'])
        expected = sorted(E.DEFAULT_IGNORE | {'build/', 'docs/', 'vendor/'})
        self.assertEqual(method['ignore'], expected)

    def test_caller_source_roots_override_the_file_and_are_deduplicated(self):
        self.write({'source_roots': ['lib']})
        self.assertEqual(S.configuration(self.root)['source_roots'], ['lib'])
        method = S.configuration(self.root, source_roots=['src', 'pkg', 'src'])
        self.assertEqual(method['source_roots'], ['pkg', 'src'])

    def test_same_inputs_give_same_method_sha(self):
        self.write({'ignore': ['b/', 'a/'], 'source_roots': ['src']})
        first = S.method_sha(S.configuration(self.root))
        self.write({'source_roots': ['src'], 'ignore': ['a/', 'b/']})
        self.assertEqual(first, S.method_sha(S.configuration(self.root)))

    # Refusals: the file itself -----------------------------------------

    def test_invalid_json_is_refused(self):
        self.write('{not json')
        self.refused('invalid ' + S.CONFIG)

    @unittest.skipIf(os.name == 'nt', 'symlinks need privileges on Windows')
    def test_symlinked_config_is_refused_even_when_target_is_valid(self):
        outside = Path(self.tmp.name) / 'outside.json'
        outside.write_text(json.dumps({'source_roots': ['src']}))
        self.path.symlink_to(outside)
        self.refused('invalid ' + S.CONFIG)

    def test_non_object_and_unknown_keys_are_refused(self):
        # '"text"' is written raw: a valid JSON document that is a string.
        for data in ([], '"text"', {'ignore': [], 'include': ['x']}):
            with self.subTest(data=data):
                self.write(data)
                self.refused('accepts ignore and source_roots only')

    # Refusals: ignore ---------------------------------------------------

    def test_ignore_must_be_a_list_of_non_empty_strings(self):
        for value in ('build/', [''], [3], [None]):
            with self.subTest(value=value):
                self.write({'ignore': value})
                self.refused('ignore must be a list')

    def test_ignore_patterns_must_be_repo_relative(self):
        for pattern in ('/abs/', '../up/', 'a/../b', 'C:/drive', 'a\\b'):
            with self.subTest(pattern=pattern):
                self.write({'ignore': [pattern]})
                self.refused('repo-relative')

    def test_caller_ignore_is_held_to_the_same_rule(self):
        self.refused('repo-relative', ignore=['../escape'])

    # Refusals: source_roots ---------------------------------------------

    def test_source_roots_must_be_auto_or_relative_directories(self):
        for value in ('src', 'AUTO', [''], [1], ['/abs'], ['../up'], ['C:/x'], ['a\\b']):
            with self.subTest(value=value):
                self.write({'source_roots': value})
                self.refused('source_roots must be auto')

    def test_caller_source_roots_are_held_to_the_same_rule(self):
        self.refused('source_roots must be auto', source_roots=['../escape'])


if __name__ == '__main__':
    unittest.main()
