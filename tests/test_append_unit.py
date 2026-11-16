"""Direct tests for src/aec/append.py helpers: parse_anchor_spec, make_anchor and append_line.

Until now these were exercised only through the `aec append` CLI (test_adoption_friction.py,
test_append_safety.py). These tests pin the helpers' own contracts so a refactor of the CLI can't
silently change what an anchor spec means, what an anchor records, or how a line is appended.
Tests only; no behaviour change.
"""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aec.append import append_line, make_anchor, parse_anchor_spec
from aec.sources import RECORDS_ENV, SourceContext


class TestParseAnchorSpec(unittest.TestCase):
    def test_plain_path_and_locator(self):
        self.assertEqual(parse_anchor_spec('docs/why.md#L3'), (None, 'docs/why.md', 'L3'))

    def test_alias_prefix(self):
        self.assertEqual(parse_anchor_spec('led=d.md#L1-2'), ('led', 'd.md', 'L1-2'))

    def test_empty_alias_reads_as_no_alias(self):
        self.assertEqual(parse_anchor_spec('=d.md#L1'), (None, 'd.md', 'L1'))

    def test_only_first_equals_splits_alias(self):
        # A path may itself contain '='; only the first one separates the alias.
        self.assertEqual(parse_anchor_spec('led=a=b.md#L1'), ('led', 'a=b.md', 'L1'))

    def test_quote_locator_keeps_later_hashes(self):
        # The path ends at the first '#'; a q: locator may contain '#' and '='.
        self.assertEqual(parse_anchor_spec('README.md#q:see #3 a=b'), (None, 'README.md', 'q:see #3 a=b'))

    def test_missing_hash_is_refused(self):
        with self.assertRaisesRegex(ValueError, r'expected \[ALIAS=\]PATH#LOCATOR'):
            parse_anchor_spec('docs/why.md')

    def test_empty_locator_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'expected'):
            parse_anchor_spec('docs/why.md#')

    def test_locator_syntax_is_not_checked_here(self):
        # Syntax checking belongs to make_anchor (via anchor_errors), not the splitter.
        self.assertEqual(parse_anchor_spec('a.md#nonsense'), (None, 'a.md', 'nonsense'))


class TestMakeAnchor(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(RECORDS_ENV, None)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        (self.repo / '.aec').mkdir()
        (self.repo / 'docs').mkdir()
        self.raw = b'first line\nsecond line\nthird line\n'
        (self.repo / 'docs' / 'why.md').write_bytes(self.raw)

    def config(self, data):
        (self.repo / '.aec' / 'sources.json').write_text(json.dumps(data), encoding='utf-8')

    def test_records_sha_locator_and_field(self):
        anchor = make_anchor(SourceContext(self.repo), 'docs/why.md#L2')
        self.assertEqual(anchor, {'path': 'docs/why.md', 'sha256': hashlib.sha256(self.raw).hexdigest(),
                                  'locator': 'L2', 'for': 'text'})

    def test_field_is_passed_through(self):
        self.assertEqual(make_anchor(SourceContext(self.repo), 'docs/why.md#L1', 'rationale')['for'], 'rationale')

    def test_quote_locator_resolves(self):
        anchor = make_anchor(SourceContext(self.repo), 'docs/why.md#q:second line')
        self.assertEqual(anchor['locator'], 'q:second line')

    def test_no_root_key_without_alias(self):
        self.assertNotIn('root', make_anchor(SourceContext(self.repo), 'docs/why.md#L1'))

    def test_no_prefix_bytes_unless_declared_append_only(self):
        self.assertNotIn('prefix_bytes', make_anchor(SourceContext(self.repo), 'docs/why.md#L1'))

    def test_prefix_bytes_for_append_only_file(self):
        self.config({'roots': {}, 'append_only': {'.': ['docs/why.md']}})
        anchor = make_anchor(SourceContext(self.repo), 'docs/why.md#L1')
        self.assertEqual(anchor['prefix_bytes'], len(self.raw))

    def test_append_only_is_per_root(self):
        # Declaring the file append-only under '.' does not make the same path under an alias append-only.
        other = self.repo / 'other'
        (other / 'docs').mkdir(parents=True)
        (other / 'docs' / 'why.md').write_bytes(self.raw)
        self.config({'roots': {'o': 'other'}, 'append_only': {'.': ['docs/why.md']}})
        anchor = make_anchor(SourceContext(self.repo), 'o=docs/why.md#L1')
        self.assertEqual(anchor['root'], 'o')
        self.assertNotIn('prefix_bytes', anchor)

    def test_alias_root_is_recorded(self):
        other = self.repo / 'ledgers'
        other.mkdir()
        (other / 'd.md').write_bytes(b'decided\n')
        self.config({'roots': {'led': 'ledgers'}})
        anchor = make_anchor(SourceContext(self.repo), 'led=d.md#L1')
        self.assertEqual((anchor['root'], anchor['path']), ('led', 'd.md'))
        self.assertEqual(anchor['sha256'], hashlib.sha256(b'decided\n').hexdigest())

    def test_unconfigured_alias_is_refused(self):
        with self.assertRaisesRegex(ValueError, "root 'nope' is not configured"):
            make_anchor(SourceContext(self.repo), 'nope=d.md#L1')

    def test_missing_file_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'docs/absent.md is missing'):
            make_anchor(SourceContext(self.repo), 'docs/absent.md#L1')

    def test_path_escaping_the_root_is_refused(self):
        with self.assertRaises(ValueError):
            make_anchor(SourceContext(self.repo), '../outside.md#L1')

    def test_bad_locator_syntax_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'locator must be'):
            make_anchor(SourceContext(self.repo), 'docs/why.md#nonsense')

    def test_line_past_end_is_refused(self):
        with self.assertRaisesRegex(ValueError, "locator 'L9' does not resolve"):
            make_anchor(SourceContext(self.repo), 'docs/why.md#L9')

    def test_quote_not_in_file_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'does not resolve'):
            make_anchor(SourceContext(self.repo), 'docs/why.md#q:fourth line')

    def test_path_is_normalised_to_posix(self):
        anchor = make_anchor(SourceContext(self.repo), 'docs/./why.md#L1')
        self.assertEqual(anchor['path'], 'docs/why.md')


class TestAppendLine(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'records.jsonl'

    def test_empty_file_gets_no_leading_newline(self):
        self.path.write_bytes(b'')
        append_line(self.path, '{"a": 1}')
        self.assertEqual(self.path.read_bytes(), b'{"a": 1}\n')

    def test_file_ending_in_newline_is_extended(self):
        self.path.write_bytes(b'{"a": 1}\n')
        append_line(self.path, '{"b": 2}')
        self.assertEqual(self.path.read_bytes(), b'{"a": 1}\n{"b": 2}\n')

    def test_missing_final_newline_is_repaired_not_merged(self):
        self.path.write_bytes(b'{"a": 1}')
        append_line(self.path, '{"b": 2}')
        self.assertEqual(self.path.read_bytes(), b'{"a": 1}\n{"b": 2}\n')

    def test_existing_bytes_are_never_rewritten(self):
        # CRLF and non-ASCII content before the append stay byte-for-byte.
        before = '{"t": "café"}\r\n'.encode()
        self.path.write_bytes(before)
        append_line(self.path, '{"t": "über"}')
        after = self.path.read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertEqual(after[len(before):], '{"t": "über"}\n'.encode())

    def test_missing_file_is_not_created(self):
        with self.assertRaises(FileNotFoundError):
            append_line(self.path, '{"a": 1}')
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
