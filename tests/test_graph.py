"""Direct tests for src/aec/graph.py: reach, fan, unresolved and re-export canonicalisation.

The graph queries were only exercised through `test_docs_truth` (an empty snapshot) and indirectly through
code-impact. These tests pin the behaviour reviewers rely on when reading `aec reach` / `aec fan` /
`aec unresolved` output: re-exports are followed only through explicit import bindings, depth is honoured,
unknown symbols and arguments are refused rather than guessed, and the visibility denominators count what the
projection could not see. Each refusal or filter has a clean decoy next to it.

The snapshot below is hand-written (the shape `aec edges` produced for a three-file package on 2026-11-15) so a
change in the extractor does not silently change what these tests assert about graph.py.
"""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from aec.graph import CAVEAT, WHY, canonical_symbol, fan, module_of, projection_edges, reach, unresolved  # noqa: E402

# pkg/__init__.py:  from pkg.core import helper as exported
# pkg/core.py:      helper(); mid() calls helper; top(obj) calls obj.run() (unresolved) and mid
# pkg/user.py:      from pkg import exported; import pkg.core; class Base; class Child(Base): go() calls exported()
SNAP = {
    'header': {
        'modules': {'pkg': 'pkg/__init__.py', 'pkg.core': 'pkg/core.py', 'pkg.user': 'pkg/user.py'},
        'bindings': {
            'pkg': {'exported': 'pkg.core.helper'},
            'pkg.core': {'helper': 'pkg.core.helper', 'mid': 'pkg.core.mid', 'top': 'pkg.core.top'},
            'pkg.user': {'Base': 'pkg.user.Base', 'Child': 'pkg.user.Child', 'exported': 'pkg.exported', 'pkg': 'pkg'},
        },
        'import_modules': [
            {'src': 'pkg', 'dst': 'pkg.core.helper', 'module': 'pkg.core'},
            {'src': 'pkg.user', 'dst': 'pkg.core', 'module': 'pkg.core'},
            {'src': 'pkg.user', 'dst': 'pkg.exported', 'module': 'pkg'},
        ],
        'skipped': [],
    },
    'edges': [
        {'kind': 'defines', 'src': 'pkg.core', 'dst': 'pkg.core.helper', 'resolved': True, 'file': 'pkg/core.py', 'line': 1},
        {'kind': 'defines', 'src': 'pkg.core', 'dst': 'pkg.core.mid', 'resolved': True, 'file': 'pkg/core.py', 'line': 4},
        {'kind': 'defines', 'src': 'pkg.core', 'dst': 'pkg.core.top', 'resolved': True, 'file': 'pkg/core.py', 'line': 7},
        {'kind': 'defines', 'src': 'pkg.user', 'dst': 'pkg.user.Base', 'resolved': True, 'file': 'pkg/user.py', 'line': 4},
        {'kind': 'defines', 'src': 'pkg.user', 'dst': 'pkg.user.Child', 'resolved': True, 'file': 'pkg/user.py', 'line': 7},
        {'kind': 'defines', 'src': 'pkg.user.Child', 'dst': 'pkg.user.Child.go', 'resolved': True, 'file': 'pkg/user.py', 'line': 8},
        {'kind': 'imports', 'src': 'pkg', 'dst': 'pkg.core.helper', 'resolved': True, 'file': 'pkg/__init__.py', 'line': 1},
        {'kind': 'imports', 'src': 'pkg.user', 'dst': 'pkg.core', 'resolved': True, 'file': 'pkg/user.py', 'line': 2},
        {'kind': 'imports', 'src': 'pkg.user', 'dst': 'pkg.exported', 'resolved': True, 'file': 'pkg/user.py', 'line': 1},
        {'kind': 'inherits', 'src': 'pkg.user.Child', 'dst': 'pkg.user.Base', 'resolved': True, 'file': 'pkg/user.py', 'line': 7},
        {'kind': 'calls', 'src': 'pkg.core.mid', 'dst': 'pkg.core.helper', 'resolved': True, 'file': 'pkg/core.py', 'line': 5},
        {'kind': 'calls', 'src': 'pkg.core.top', 'dst': '?obj.run', 'resolved': False, 'file': 'pkg/core.py', 'line': 8,
         'why': 'local_value'},
        {'kind': 'calls', 'src': 'pkg.core.top', 'dst': 'pkg.core.mid', 'resolved': True, 'file': 'pkg/core.py', 'line': 9},
        {'kind': 'calls', 'src': 'pkg.user.Child.go', 'dst': 'pkg.exported', 'resolved': True, 'file': 'pkg/user.py', 'line': 9},
    ],
}


def snap():
    return copy.deepcopy(SNAP)


class TestCanonicalSymbol(unittest.TestCase):
    def test_re_export_resolves_to_its_definition(self):  # violating: the alias is not where the code lives
        self.assertEqual(canonical_symbol(snap(), 'pkg.exported'), 'pkg.core.helper')

    def test_defined_symbol_and_module_are_returned_unchanged(self):  # decoys
        self.assertEqual(canonical_symbol(snap(), 'pkg.core.helper'), 'pkg.core.helper')
        self.assertEqual(canonical_symbol(snap(), 'pkg.core'), 'pkg.core')

    def test_unknown_symbol_is_not_guessed(self):  # no binding: returned as given, not matched by name
        self.assertEqual(canonical_symbol(snap(), 'pkg.helper'), 'pkg.helper')

    def test_attribute_tail_survives_the_re_export(self):
        self.assertEqual(canonical_symbol(snap(), 'pkg.exported.attr'), 'pkg.core.helper.attr')

    def test_binding_cycle_returns_the_original_symbol(self):  # a <-> b re-export loop must terminate
        s = snap()
        s['header']['modules'].update({'a': 'a.py', 'b': 'b.py'})
        s['header']['bindings'].update({'a': {'x': 'b.x'}, 'b': {'x': 'a.x'}})
        self.assertEqual(canonical_symbol(s, 'a.x'), 'a.x')

    def test_module_of_follows_the_re_export(self):
        self.assertEqual(module_of(snap(), 'pkg.exported'), 'pkg.core')
        self.assertIsNone(module_of(snap(), 'elsewhere.thing'))  # decoy: external label has no module


class TestProjectionEdges(unittest.TestCase):
    def test_calls_projection_canonicalises_and_drops_unresolved(self):
        arcs = projection_edges(snap(), 'calls')
        self.assertIn(('pkg.user.Child.go', 'pkg.core.helper'), arcs)  # via the re-export
        self.assertNotIn(('pkg.user.Child.go', 'pkg.exported'), arcs)
        self.assertFalse(any(dst.startswith('?') for _, dst in arcs))  # unresolved call is invisible

    def test_imports_projection_is_module_to_module(self):
        self.assertEqual(projection_edges(snap(), 'imports'),
                         [('pkg', 'pkg.core'), ('pkg.user', 'pkg'), ('pkg.user', 'pkg.core')])

    def test_unknown_projection_is_refused(self):
        with self.assertRaises(ValueError):
            projection_edges(snap(), 'defines')


class TestReach(unittest.TestCase):
    def test_depth_one_callers_are_direct_only(self):
        r = reach(snap(), 'pkg.core.helper')
        self.assertEqual(r['reachable'], ['pkg.core.mid', 'pkg.user.Child.go'])  # top is two hops away

    def test_depth_two_reaches_the_transitive_caller(self):
        self.assertIn('pkg.core.top', reach(snap(), 'pkg.core.helper', depth=2)['reachable'])

    def test_depth_zero_reaches_nothing(self):
        self.assertEqual(reach(snap(), 'pkg.core.helper', depth=0)['reachable'], [])

    def test_callees_direction(self):
        self.assertEqual(reach(snap(), 'pkg.core.top', direction='callees', depth=5)['reachable'],
                         ['pkg.core.helper', 'pkg.core.mid'])

    def test_alias_query_reports_both_names(self):
        r = reach(snap(), 'pkg.exported')
        self.assertEqual((r['symbol'], r['canonical_symbol']), ('pkg.exported', 'pkg.core.helper'))
        self.assertTrue(r['origin_in_projection'])

    def test_defined_symbol_outside_the_projection_is_answered_not_refused(self):
        r = reach(snap(), 'pkg.user.Base')  # defined, but nothing calls it
        self.assertEqual(r['reachable'], [])
        self.assertFalse(r['origin_in_projection'])

    def test_inherits_projection(self):
        self.assertEqual(reach(snap(), 'pkg.user.Base', projection='inherits')['reachable'], ['pkg.user.Child'])

    def test_unknown_symbol_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'not present'):
            reach(snap(), 'pkg.core.nothing')

    def test_bad_direction_and_negative_depth_are_refused(self):
        with self.assertRaises(ValueError):
            reach(snap(), 'pkg.core.helper', direction='sideways')
        with self.assertRaises(ValueError):
            reach(snap(), 'pkg.core.helper', depth=-1)

    def test_visibility_counts_the_unresolved_call_and_keeps_the_caveat(self):
        r = reach(snap(), 'pkg.core.helper', depth=2)
        v = r['visibility']['projection']
        self.assertEqual((v['resolved'], v['total'], v['unresolved_by_why']['local_value']), (3, 4, 1))
        self.assertEqual(r['caveat'], CAVEAT)
        self.assertEqual(r['label'], 'structural')


class TestFan(unittest.TestCase):
    def test_counts_distinct_neighbors_and_orders_by_degree(self):
        rows = fan(snap())['nodes']
        self.assertEqual(rows[0], {'symbol': 'pkg.core.helper', 'fan_in': 2, 'fan_out': 0})
        # mid has in=1 out=1, tied with helper on total degree 2: name order breaks the tie
        self.assertEqual([r['symbol'] for r in rows[:2]], ['pkg.core.helper', 'pkg.core.mid'])

    def test_top_truncates_and_reports_omitted(self):
        r = fan(snap(), top=1)
        self.assertEqual((len(r['nodes']), r['omitted']), (1, 3))
        self.assertEqual(fan(snap(), top=0)['omitted'], 4)

    def test_imports_projection(self):
        rows = {r['symbol']: r for r in fan(snap(), projection='imports')['nodes']}
        self.assertEqual(rows['pkg.core']['fan_in'], 2)

    def test_bad_arguments_are_refused(self):
        with self.assertRaises(ValueError):
            fan(snap(), projection='inherits')
        with self.assertRaises(ValueError):
            fan(snap(), top=-1)


class TestUnresolved(unittest.TestCase):
    def test_lists_only_unresolved_calls(self):
        rows = unresolved(snap())
        self.assertEqual([(r['src'], r['dst'], r['why']) for r in rows], [('pkg.core.top', '?obj.run', 'local_value')])

    def test_why_filter(self):
        self.assertEqual(len(unresolved(snap(), why=['local_value'])), 1)
        self.assertEqual(unresolved(snap(), why=['reflective']), [])  # decoy: a known reason with no rows

    def test_unknown_why_is_refused(self):
        with self.assertRaises(ValueError):
            unresolved(snap(), why=['made_up'])

    def test_scope_by_file_directory_and_symbol(self):
        for scope in ('pkg/core.py', 'pkg', 'pkg/', 'pkg.core', 'pkg.core.top'):
            with self.subTest(scope=scope):
                self.assertEqual(len(unresolved(snap(), scope=scope)), 1)

    def test_scope_prefix_does_not_match_a_sibling_name(self):  # decoys: 'pkg/co' and 'pkg.co' are not parents
        for scope in ('pkg/user.py', 'pkg/co', 'pkg.co', 'pkg.user'):
            with self.subTest(scope=scope):
                self.assertEqual(unresolved(snap(), scope=scope), [])

    def test_rows_are_copies(self):
        s = snap()
        unresolved(s)[0]['dst'] = 'mutated'
        self.assertEqual(s['edges'][11]['dst'], '?obj.run')

    def test_every_why_reason_is_counted(self):
        self.assertEqual(set(reach(snap(), 'pkg.core.mid')['visibility']['projection']['unresolved_by_why']), set(WHY))


if __name__ == '__main__':
    unittest.main()
