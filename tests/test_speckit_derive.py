"""DEC-194 prototype: `speckit derive` and `speckit drift` on a synthetic repository.

Each check has a violating fixture and a clean decoy. Fixtures are synthetic (no other repo's specs).
"""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from aec import speckit as S
from aec.__main__ import main
from aec.records import Store

RECORDS = "\n".join(json.dumps(r) for r in [
    {"id": "AU-o", "version": 1, "type": "authority", "text": "Owner", "governs": ["p"]},
    {"id": "P0", "version": 1, "type": "purpose", "subject": "p", "epistemic": "committed", "owner": "AU-o",
     "text": "Old purpose"},
    {"id": "P0", "version": 2, "type": "purpose", "subject": "p", "epistemic": "committed", "owner": "AU-o",
     "text": "Keep reports honest"},
    {"id": "R-A", "version": 1, "type": "requirement", "epistemic": "committed", "text": "Label structural checks",
     "relations": [{"rel": "serves", "to": "P0@2"}, {"rel": "implemented_by", "to": "code:pkg.check"}]},
    {"id": "R-B", "version": 1, "type": "requirement", "epistemic": "committed", "text": "Never edit records",
     "relations": [{"rel": "serves", "to": "P0@2"}]},
    {"id": "R-C", "version": 1, "type": "requirement", "epistemic": "provisional", "text": "Draft idea",
     "relations": [{"rel": "serves", "to": "P0@2"}]},
    {"id": "CR-A", "version": 1, "type": "criterion", "text": "Every report says structural",
     "relations": [{"rel": "tests", "to": "R-A@1"}]},
]) + "\n"

SPEC = """# Feature Specification: demo

Serves: P0@2, R-A@1.

## User Scenarios

A person reads the report. This narrative is authored and must survive regeneration.

## Requirements

- **FR-001**: Reports carry a structural label (R-A@1).
- **FR-002**: Something nobody recorded yet.
- **FR-002a**: A suffixed one, also unrecorded.

## Open questions

- Should drift fail CI?
"""


class Repo:
    def __init__(self, spec=SPEC, records=RECORDS):
        self.root = Path(tempfile.mkdtemp(prefix="speckit-derive-"))
        (self.root / ".aec").mkdir()
        (self.root / ".aec" / "records.jsonl").write_text(records, encoding="utf-8")
        self.feature = self.root / "specs" / "001-demo"
        self.feature.mkdir(parents=True)
        self.spec = self.feature / "spec.md"
        self.spec.write_text(spec, encoding="utf-8")

    def run(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(list(argv))
        return code, buf.getvalue()

    def close(self):
        shutil.rmtree(self.root)


class Derive(unittest.TestCase):
    def setUp(self):
        self.r = Repo()

    def tearDown(self):
        self.r.close()

    def test_insert_fills_block_and_keeps_authored_text(self):
        code, out = self.r.run("speckit", "derive", str(self.r.feature), "--insert")
        self.assertEqual(code, 0, out)
        text = self.r.spec.read_text()
        for authored in ("This narrative is authored and must survive regeneration.", "## Open questions",
                         "- **FR-002**: Something nobody recorded yet.", "Serves: P0@2, R-A@1."):
            self.assertIn(authored, text)
        self.assertIn("- **R-A@1** (committed): Label structural checks", text)
        self.assertNotIn("CR-A", text)  # no criterion -> requirement relation exists yet; acceptance is not derived
        self.assertIn("Implemented by: `code:pkg.check`", text)
        self.assertNotIn("R-B@1", text)  # select=cited: R-B is not cited
        # the block sits right under the Requirements heading
        self.assertLess(text.index("## Requirements"), text.index("telosmith:derived"))
        self.assertLess(text.index("telosmith:end"), text.index("FR-001"))

    def test_regeneration_is_idempotent(self):
        self.r.run("speckit", "derive", str(self.r.feature), "--insert")
        once = self.r.spec.read_bytes()
        code, out = self.r.run("speckit", "derive", str(self.r.feature), "--insert")
        self.assertEqual(self.r.spec.read_bytes(), once)
        self.assertIn("up to date", out)
        code, _ = self.r.run("speckit", "derive", str(self.r.feature), "--check")
        self.assertEqual(code, 0)

    def test_record_change_regenerates_only_the_block(self):
        self.r.run("speckit", "derive", str(self.r.feature), "--insert")
        before = self.r.spec.read_text()
        with open(self.r.root / ".aec" / "records.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "R-A", "version": 2, "type": "requirement", "epistemic": "committed",
                                "text": "Label every structural check", "relations": [{"rel": "serves", "to": "P0@2"}]})
                    + "\n")
        code, out = self.r.run("speckit", "derive", str(self.r.feature), "--check")
        self.assertEqual(code, 1, out)
        self.assertEqual(self.r.spec.read_text(), before)  # --check writes nothing
        self.r.run("speckit", "derive", str(self.r.feature))
        after = self.r.spec.read_text()
        self.assertIn("**R-A@2** (committed): Label every structural check", after)
        blocks, _ = S.find_blocks(before)
        self.assertEqual(S.authored_text(after, S.find_blocks(after)[0]), S.authored_text(before, blocks))

    def test_hand_edited_block_is_never_overwritten(self):  # violation
        self.r.run("speckit", "derive", str(self.r.feature), "--insert")
        text = self.r.spec.read_text().replace("Label structural checks", "Label structural checks (my edit)")
        self.r.spec.write_text(text)
        code, out = self.r.run("speckit", "derive", str(self.r.feature))
        self.assertIn("edited by hand", out)
        self.assertEqual(self.r.spec.read_text(), text)

    def test_unedited_block_decoy_regenerates(self):  # decoy for the above
        self.r.run("speckit", "derive", str(self.r.feature), "--insert")
        text = self.r.spec.read_text()
        res = S.derive_text(Store.load(self.r.root / ".aec" / "records.jsonl"), text)
        self.assertEqual(res.skipped, [])
        self.assertEqual(res.text, text)

    def test_provisional_version_does_not_displace_committed_baseline(self):  # violation (Copilot, #72)
        self.r.run("speckit", "derive", str(self.r.feature), "--insert")
        with open(self.r.root / ".aec" / "records.jsonl", "a", encoding="utf-8") as f:
            for rid in ("R-A", "R-B"):
                f.write(json.dumps({"id": rid, "version": 2, "type": "requirement", "epistemic": "provisional",
                                    "text": "Proposed rewording", "relations": [{"rel": "serves", "to": "P0@2"}]})
                        + "\n")
        self.r.run("speckit", "derive", str(self.r.feature))
        text = self.r.spec.read_text()
        self.assertIn("- **R-A@1** (committed): Label structural checks", text)
        self.assertIn("Pending: `R-A@2` (provisional, not accepted): Proposed rewording", text)
        self.assertNotIn("**R-A@2**", text)
        store = Store.load(self.r.root / ".aec" / "records.jsonl")
        kinds = {(f.kind, f.subject) for f in S.drift_text(store, text, "spec.md")}
        self.assertNotIn(("superseded-citation", "R-A@1"), kinds)   # a proposal does not supersede the baseline
        self.assertIn("- **R-B@1**: Never edit records", S.render_constitution(store))
        self.assertEqual({r.ref for r in S.uncovered(store, [text])}, {"R-B@1"})

    def test_edited_block_recovery_by_reinserting(self):  # the documented recovery path
        self.r.run("speckit", "derive", str(self.r.feature), "--insert")
        text = self.r.spec.read_text().replace("Label structural checks", "edited")
        blocks, _ = S.find_blocks(text)
        b = blocks[0]
        self.r.spec.write_text(text[:b.start] + text[b.end:])       # delete the whole fenced block
        code, out = self.r.run("speckit", "derive", str(self.r.feature), "--insert")
        self.assertEqual(code, 0, out)
        self.assertIn("- **R-A@1** (committed): Label structural checks", self.r.spec.read_text())

    def test_marker_in_record_text_does_not_close_the_block(self):  # violation (Codex review on #73)
        with open(self.r.root / ".aec" / "records.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "R-A", "version": 2, "type": "requirement", "epistemic": "committed",
                                "text": "Recognize the marker `<!-- telosmith:end -->` in documents.",
                                "relations": []}) + "\n")
        self.r.run("speckit", "derive", str(self.r.feature), "--insert")
        once = self.r.spec.read_bytes()
        code, out = self.r.run("speckit", "derive", str(self.r.feature))
        self.assertNotIn("edited by hand", out)
        self.assertEqual(self.r.spec.read_bytes(), once)
        store = Store.load(self.r.root / ".aec" / "records.jsonl")
        self.assertFalse([f for f in S.drift_text(store, once.decode(), "spec.md") if f.kind == "edited-block"])

    def test_write_never_touches_an_existing_scratch_file_or_symlink_target(self):  # violation (Copilot, #73)
        victim = self.r.root / "victim.txt"
        victim.write_text("keep me")
        legacy = self.r.feature / "spec.md.telosmith-tmp"
        legacy.symlink_to(victim)
        self.r.spec.chmod(0o640)
        code, out = self.r.run("speckit", "derive", str(self.r.feature), "--insert")
        self.assertEqual(code, 0, out)
        self.assertEqual(victim.read_text(), "keep me")
        self.assertFalse(self.r.spec.is_symlink())
        self.assertEqual(self.r.spec.stat().st_mode & 0o777, 0o640)
        self.assertEqual(sorted(p.name for p in self.r.feature.iterdir()), ["spec.md", "spec.md.telosmith-tmp"])

    def test_unloadable_record_stops_both_commands(self):  # violation (Copilot, #73)
        with open(self.r.root / ".aec" / "records.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "R-X", "version": "1", "type": "requirement", "text": "bad version"}) + "\n")
        before = self.r.spec.read_bytes()
        code, out = self.r.run("speckit", "derive", str(self.r.feature), "--insert")
        self.assertEqual(code, 2)
        self.assertIn("could not be loaded", out)
        self.assertEqual(self.r.spec.read_bytes(), before)
        code, out = self.r.run("speckit", "drift", str(self.r.feature))
        self.assertEqual(code, 2)

    def test_constitution_shows_pending_proposals_and_drift_sees_them(self):  # violation (Copilot, #73)
        con = self.r.root / "constitution.md"
        con.write_text("# Constitution\n")
        self.r.run("speckit", "derive", str(self.r.feature), "--constitution", str(con), "--insert")
        with open(self.r.root / ".aec" / "records.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "P0", "version": 3, "type": "purpose", "epistemic": "provisional",
                                "text": "Proposed purpose"}) + "\n")
            f.write(json.dumps({"id": "R-B", "version": 2, "type": "requirement", "epistemic": "provisional",
                                "text": "Proposed invariant", "relations": [{"rel": "serves", "to": "P0@2"}]}) + "\n")
        store = Store.load(self.r.root / ".aec" / "records.jsonl")
        kinds = {f.kind for f in S.drift_text(store, con.read_text(), "constitution.md")}
        self.assertIn("stale-block", kinds)
        self.r.run("speckit", "derive", str(self.r.feature), "--constitution", str(con))
        text = con.read_text()
        self.assertIn("### P0@2", text)                                   # baseline kept
        self.assertIn("Pending: `P0@3` (provisional, not accepted): Proposed purpose", text)
        self.assertIn("- **R-B@1**: Never edit records", text)
        self.assertIn("Pending: `R-B@2` (provisional, not accepted): Proposed invariant", text)
        self.assertNotIn("**R-B@2**", text)

    def test_conflicting_duplicate_ref_stops_both_commands(self):  # violation (Copilot, #73)
        with open(self.r.root / ".aec" / "records.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "R-A", "version": 1, "type": "requirement", "epistemic": "committed",
                                "text": "A different R-A@1"}) + "\n")
        before = self.r.spec.read_bytes()
        code, out = self.r.run("speckit", "derive", str(self.r.feature), "--insert")
        self.assertEqual(code, 2)
        self.assertIn("R-A@1", out)
        self.assertEqual(self.r.spec.read_bytes(), before)
        code, _ = self.r.run("speckit", "drift", str(self.r.feature))
        self.assertEqual(code, 2)

    def test_identical_duplicate_line_is_accepted(self):  # decoy: the loader coalesces exact copies
        line = (self.r.root / ".aec" / "records.jsonl").read_text().splitlines()[3]
        with open(self.r.root / ".aec" / "records.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
        code, out = self.r.run("speckit", "derive", str(self.r.feature), "--insert")
        self.assertEqual(code, 0, out)

    def test_select_variants(self):
        store = Store.load(self.r.root / ".aec" / "records.jsonl")
        self.assertEqual([r.id for r in S.select(store, {"select": "serves:P0"}, "")], ["R-A", "R-B", "R-C"])
        self.assertEqual([r.id for r in S.select(store, {"select": "ids:R-B"}, "")], ["R-B"])
        with self.assertRaises(ValueError):
            S.select(store, {"select": "everything"}, "")

    def test_constitution_block(self):
        con = self.r.root / "constitution.md"
        con.write_text("# Constitution\n\nAuthored principles stay.\n")
        self.r.run("speckit", "derive", str(self.r.feature), "--constitution", str(con), "--insert")
        text = con.read_text()
        self.assertIn("Authored principles stay.", text)
        self.assertIn("### P0@2", text)
        self.assertNotIn("Old purpose", text)          # latest version only
        self.assertIn("- **R-B@1**: Never edit records", text)
        self.assertNotIn("Draft idea", text)          # provisional requirements are not invariants

    def test_crlf_checkout_is_not_a_hand_edit(self):  # decoy: line endings only
        self.r.run("speckit", "derive", str(self.r.feature), "--insert")
        crlf = self.r.spec.read_bytes().replace(b"\n", b"\r\n")
        self.r.spec.write_bytes(crlf)
        res = S.derive_text(Store.load(self.r.root / ".aec" / "records.jsonl"), crlf.decode())
        self.assertEqual(res.skipped, [])
        self.assertEqual(res.text.encode(), crlf)  # idempotent, and CRLF is kept

    def test_unterminated_fence_is_reported_not_fatal(self):
        text = SPEC + "\n<!-- telosmith:derived block=requirements sha256=x -->\nno end\n"
        res = S.derive_text(Store.load(self.r.root / ".aec" / "records.jsonl"), text)
        self.assertEqual(res.text, text)
        self.assertTrue(any("no `<!-- telosmith:end -->`" in s for s in res.skipped))


class Drift(unittest.TestCase):
    def setUp(self):
        self.r = Repo()

    def tearDown(self):
        self.r.close()

    def kinds(self, *extra):
        code, out = self.r.run("speckit", "drift", str(self.r.feature), "--json", *extra)
        self.assertEqual(code, 0)
        return json.loads(out)

    def test_spec_to_records_direction(self):
        found = self.kinds()
        by = {(f["kind"], f["subject"]) for f in found}
        self.assertIn(("unrecorded-requirement", "FR-002"), by)       # violation
        self.assertIn(("unrecorded-requirement", "FR-002a"), by)      # suffixed ids (Copilot, #73)
        self.assertNotIn(("unrecorded-requirement", "FR-001"), by)    # decoy: FR-001 cites R-A@1
        prop = next(f["proposal"] for f in found if f["subject"] == "FR-002")
        self.assertEqual(prop["epistemic"], "provisional")
        self.assertEqual(prop["text"], "Something nobody recorded yet.")
        self.assertEqual(self.r.spec.read_text(), SPEC)                # drift writes nothing
        self.assertEqual((self.r.root / ".aec" / "records.jsonl").read_text(), RECORDS)

    def test_unresolved_and_superseded_citations(self):
        self.r.spec.write_text(SPEC.replace("Serves: P0@2", "Serves: P0@1, R-Z@1"))
        by = {(f["kind"], f["subject"]) for f in self.kinds()}
        self.assertIn(("superseded-citation", "P0@1"), by)
        self.assertIn(("unresolved-citation", "R-Z@1"), by)
        self.assertNotIn(("superseded-citation", "R-A@1"), by)        # decoy: current version

    def test_records_to_spec_direction(self):
        by = {(f["kind"], f["subject"]) for f in self.kinds()}
        self.assertIn(("uncovered-record", "R-B@1"), by)               # serves cited P0, cited nowhere
        self.assertNotIn(("uncovered-record", "R-A@1"), by)            # decoy: cited
        self.assertNotIn(("uncovered-record", "R-C@1"), by)            # decoy: provisional, not a commitment

    def test_uncovered_scope_needs_a_cited_target_unless_all(self):
        self.r.spec.write_text("# Spec\n\nNo citations.\n")
        self.assertFalse([f for f in self.kinds() if f["kind"] == "uncovered-record"])
        self.assertEqual({f["subject"] for f in self.kinds("--all") if f["kind"] == "uncovered-record"},
                         {"R-A@1", "R-B@1"})

    def test_stale_and_edited_blocks(self):
        self.r.run("speckit", "derive", str(self.r.feature), "--insert")
        self.assertFalse([f for f in self.kinds() if f["kind"] in ("stale-block", "edited-block")])  # decoy
        with open(self.r.root / ".aec" / "records.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "R-A", "version": 2, "type": "requirement", "epistemic": "committed",
                                "text": "Changed", "relations": []}) + "\n")
        kinds = {f["kind"] for f in self.kinds()}
        self.assertIn("stale-block", kinds)
        self.assertIn("superseded-citation", kinds)                    # the authored R-A@1 citations
        self.r.spec.write_text(self.r.spec.read_text().replace("Label structural checks", "edited"))
        self.assertIn("edited-block", {f["kind"] for f in self.kinds()})

    def test_exit_code_flag(self):
        code, _ = self.r.run("speckit", "drift", str(self.r.feature), "--exit-code")
        self.assertEqual(code, 1)

    def test_citation_pattern_decoys(self):
        self.assertEqual(S.citations("mail me at a@1 or x.P0@2; v1.2@3 and P0@2."), ["P0@2"])


if __name__ == "__main__":
    unittest.main()
