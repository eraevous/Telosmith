"""Append validation must not write or remove unrelated files (tests written first)."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aec.__main__ import main
from aec.append import build
from aec.records import Store, check


class TestAppendSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        (self.repo / '.aec').mkdir()
        self.records = self.repo / '.aec' / 'records.jsonl'
        self.records.write_text('', encoding='utf-8')
        self.sibling = self.records.with_name('records.jsonl.append-check')
        self.record = {'id': 'C-1', 'version': 1, 'type': 'claim', 'text': 'A candidate.', 'tier': 'candidate'}

    def run_append(self, *flags):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(['append', str(self.records), json.dumps(self.record), *flags])
        return rc, out.getvalue(), err.getvalue()

    def test_existing_sibling_file_is_untouched(self):
        self.sibling.write_bytes(b'unrelated data\x00')
        line, problems = build(self.records, self.record, [], [], self.repo)
        self.assertEqual(problems, [])
        self.assertEqual(json.loads(line), self.record)
        self.assertTrue(self.sibling.exists())
        self.assertEqual(self.sibling.read_bytes(), b'unrelated data\x00')
        self.assertEqual(self.records.read_bytes(), b'')

    def test_existing_sibling_symlink_and_target_are_untouched(self):
        target = self.repo / 'harmless-target.txt'
        target.write_bytes(b'keep me')
        self.sibling.symlink_to(target)
        self.assertEqual(self.run_append()[0], 0)
        self.assertEqual(target.read_bytes(), b'keep me')
        self.assertTrue(self.sibling.is_symlink())

    def test_dry_run_preserves_sibling_and_records(self):
        self.sibling.write_bytes(b'keep me')
        rc, out, err = self.run_append('--dry-run')
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out), self.record)
        self.assertEqual(self.records.read_bytes(), b'')
        self.assertTrue(self.sibling.exists())
        self.assertEqual(self.sibling.read_bytes(), b'keep me')

    def test_validation_never_opens_a_file_for_writing(self):
        original = io.open

        def read_only(file, mode='r', *args, **kwargs):
            if any(c in mode for c in 'wax+'):
                raise AssertionError(f'validation opened {file} for writing')
            return original(file, mode, *args, **kwargs)

        with patch('io.open', side_effect=read_only):
            self.assertEqual(self.run_append('--dry-run')[0], 0)

    def test_parse_exception_leaves_no_artifacts_or_collateral_damage(self):
        self.sibling.write_bytes(b'keep me')
        self.record.pop('type')
        with self.assertRaises(KeyError):
            build(self.records, self.record, [], [], self.repo)
        self.assertTrue(self.sibling.exists())
        self.assertEqual(self.sibling.read_bytes(), b'keep me')
        self.assertEqual(sorted(p.name for p in self.records.parent.iterdir()),
                         ['records.jsonl', 'records.jsonl.append-check'])
        self.assertEqual(self.records.read_bytes(), b'')

    def test_check_exception_leaves_no_artifacts(self):
        with patch('aec.append.check', side_effect=RuntimeError('check failed')):
            with self.assertRaisesRegex(RuntimeError, 'check failed'):
                build(self.records, self.record, [], [], self.repo)
        self.assertEqual(list(self.records.parent.iterdir()), [self.records])
        self.assertEqual(self.records.read_bytes(), b'')

    def test_normal_append_keeps_existing_prefix_and_adds_newline(self):
        old = json.dumps({**self.record, 'id': 'C-0'}).encode()
        self.records.write_bytes(old)
        rc, _, err = self.run_append()
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.records.read_bytes(), old + b'\n' + json.dumps(self.record).encode() + b'\n')
        self.assertEqual(len(Store.load(self.records).records), 2)
        self.assertEqual(list(self.records.parent.iterdir()), [self.records])

    def test_new_invalid_relation_rejected_without_writing(self):
        self.record['relations'] = [{'rel': 'depends_on', 'to': 'missing@1'}]
        rc, _, err = self.run_append()
        self.assertEqual(rc, 1)
        self.assertIn('missing@1', err)
        self.assertEqual(self.records.read_bytes(), b'')

    def test_existing_duplicate_format_errors_remain_existing(self):
        # CRLF versus LF is not byte-identical. Validation must not normalize the old prefix.
        old = json.dumps({**self.record, 'id': 'C-0'})
        self.records.write_bytes((old + '\r\n' + old + '\n').encode())
        self.assertTrue(any(f.rule == 'unique' for f in check(Store.load(self.records))))
        line, problems = build(self.records, self.record, [], [], self.repo)
        self.assertEqual(problems, [])
        self.assertEqual(json.loads(line), self.record)
        self.assertEqual(self.records.read_bytes(), (old + '\r\n' + old + '\n').encode())
