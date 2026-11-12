# Deriving Spec Kit specs from Telosmith records (design note)

Status: **proposed** (draft PR). Direction: DEC-194 (Zach, 2026-11-10: Spec Kit specs should be "aligned with and derived from Telosmith and the Purpose docs", without "tedious drafting and maintenance"). Handoff HO-AEC-20261110-DW5N. Prototype: `telosmith speckit derive` / `telosmith speckit drift` in a separate draft PR (`aec/speckit-derive-prototype`).

The existing extension ([spec-kit.md](spec-kit.md)) runs one direction only: it reports on specs after they are written. This note adds the other direction, records → spec, while keeping Spec Kit optional and keeping authored text out of reach.

## Blocking question for Zach (answered 2026-11-10: option A, DEC-201; amendment merged in #74)

Derivation conflicts with two committed texts:

- constitution Principle I: "AEC MUST NOT rewrite specs", and specs "reference" records and "do not restate them";
- `AEC-R1@1`: "Never create a competing authority: Spec Kit owns workflow".

DEC-194 is newer and comes from the same authority, but neither text has been amended. Proposed reconciliation, for Zach to accept or reject:

> Telosmith MUST NOT rewrite authored spec text. It MAY regenerate **derived blocks**: fenced regions that restate records as a read-only view, marked as generated and hash-stamped. It does so only when a person or agent runs `speckit derive` explicitly, never from a Spec Kit hook. The records stay the single authority; a derived block is never cited as a source.

If accepted, this becomes a constitution amendment (version bump) and `AEC-R1@2`. Both are Zach's to accept. The prototype is a draft until then.

## Mapping

| Spec Kit artifact / section | Derived from | Prototype |
|---|---|---|
| constitution: purpose and invariants | committed `purpose` records at their baseline; committed `requirement` records that directly `serves` one | yes (`block=constitution`) |
| spec.md: requirements | `requirement` records at their baseline (below), selected by the block's `select=` | yes (`block=requirements`) |
| spec.md: acceptance | `criterion` records, once a criterion → requirement relation exists. The vocabulary has none today (`tests` is evaluation → claim), so this needs its own contract work | no |
| plan.md: constraints | `decision` records (accepted, with `decided_by`) and contracts the requirement `depends_on` | no: designed only |
| tasks.md: links | `implemented_by` edges (`code:` refs) | partial: listed under each requirement in spec.md; tasks.md not touched |
| **Stays authored** | title, why/narrative, user stories, edge cases, assumptions, open questions, out of scope, FR wording until it is recorded | never touched |

Selection (`select=` in the fence): `cited` (default) takes requirements the authored text cites by `id@version`; `ids:A,B` names them; `serves:X` takes every requirement serving any version of X. A block renders each record at its **baseline**: the newest version that is not provisional, or the newest if all are provisional. Newer provisional versions (for example a write-back proposal appended over a committed requirement) are listed under it as *pending*. They do not replace it until promoted, and they don't make a citation of the baseline count as superseded. A citation older than the baseline is reported as drift, not silently rewritten.

## Derived regions

```markdown
<!-- telosmith:derived block=requirements select=cited sha256=eb1fc5a48eeeedb1 -->
_Derived from Telosmith records by `telosmith speckit derive`. Change the records, not this block; …_

- **DG-RA@1** (committed): Separate observations, descriptions, …
<!-- telosmith:end -->
```

- HTML comments, so rendered Markdown shows only the content.
- `sha256` is the first 16 hex digits of the hash of the body as generated. If the body no longer matches, someone edited it: `derive` **leaves that block alone** and says so; `drift` reports `edited-block`. Authored text is therefore never overwritten, including text typed inside a fence.
- Regeneration is idempotent: same records, same bytes. Output order is by record id.
- `--insert` adds an empty block under `## Requirements` (or at the end of the constitution) when none exists. Without it, `derive` only refreshes blocks that are already there, so adopting this per spec is opt-in.
- `--check` writes nothing and exits 1 if anything would change (usable in CI later, report-only for now).

## Drift check (report-only)

| Direction | Finding | Meaning |
|---|---|---|
| spec → records | `unresolved-citation` | an `id@version` in authored text matches no record |
| spec → records | `superseded-citation` | it resolves, but a newer version exists |
| spec → records | `unrecorded-requirement` | an `FR-NNN` line cites no record |
| spec ↔ records | `stale-block` | records changed since the block was generated |
| spec ↔ records | `edited-block` | the block was edited by hand |
| records → spec | `uncovered-record` | a committed requirement that serves something these specs cite, and that no scanned spec cites or derives; `--all` widens this to every committed requirement (for a whole `specs/` tree) |

`--exit-code` makes findings fail the command; the default exit is 0.

## Write-back

When a spec edit implies a new or changed record (an `unrecorded-requirement`, or an `edited-block`), drift prints a **provisional** record as JSON: `epistemic: provisional`, `authored_by` from `RELAYKIT_ACTOR` when set, and a `source_note` naming the spec and FR. Nothing is appended. A person or agent reviews it, then runs `telosmith append`. Promotion to `committed` stays Zach's (AGENTS.md: agents append provisional records only). For an edited block, recovery takes two steps. First, carry the edit into a provisional record, as above. Second, delete the whole fenced block and run `derive --insert`, which writes a fresh block from the records. Changing the records alone is not enough: the hash mismatch keeps the block skipped until it is removed. There is no reverse sync from block text.

## Optional by design

- Spec Kit stays optional. `speckit derive/drift` read and write Markdown files; they never call the `specify` CLI. Nothing else in Telosmith imports the module.
- No other Kairos repository is needed. The trial below used a copy of Fathom's spec and records.
- The extension manifest is unchanged in the prototype (`effect: read-only` still holds), and `derive` stays a CLI command outside the extension. Adding a manual `/speckit-aec-derive` command later is a separate change. It must also update the read-only declarations in `extension/extension.yml` (`effect`, description) and the invariant in `specs/001-ast-bedrock-extension/contracts/extension.yml.md` ("no command writes spec.md…"), with the extension tests. Amending only the constitution and `AEC-R1` would leave those guarantees contradicting it. That command would have no hook. A hook that writes would make Spec Kit runs mutate specs as a side effect, which is the competing-authority failure.

## Trial: a copy of Fathom spec 027 (read-only; nothing committed to Fathom)

Fathom spec 027 (branch `027-bivariate-type-pairs`) and Fathom's `.aec/records.jsonl` were copied to a scratch directory.

- `drift`: 18 findings. 7 `unrecorded-requirement` (FR-001…FR-007 cite no record; the spec cites its records only in the `Serves:` line). 11 `uncovered-record` (committed DG/FT requirements serving the cited `P0@2` that the spec does not cite). No unresolved or superseded citations.
- `derive --insert` would add one block under `## Requirements` with DG-RA@1, DG-RB@1, DG-RC@1, DG-RE@1, DG-RF@1 and FT-R7@3, plus FT-R7@3's seven `implemented_by` symbols. No authored line changes.

What the trial shows: (1) `uncovered-record` is noisy when a spec cites the root purpose, because everything serves it. The default scope probably needs to drop purpose-only coverage or rank by relation distance. (2) Proposals take only the first line of a wrapped FR item; multi-line FR capture is needed before proposals are useful. (3) Fathom's FR lines and records are parallel vocabularies today; derivation makes the gap visible but does not close it. Closing it is a recording task for the Fathom lane, not something a tool does.

Dogfood on Telosmith's own `specs/`: 42 unrecorded FR lines, 7 superseded citations (mostly `AEC-P0@1`, now `@3`) and 5 uncovered committed requirements. Report only; nothing changed.

## Dissent review (AGENTS.md Drift: a new module and a change in responsibility)

1. **Which purpose or assumption might this violate?** Constitution I and `AEC-R1@1` (above); `AEC-R3` (earn adoption against the baseline): generated blocks add files and diff noise to every spec.
2. **Evidence for the concern.** The constitution and R1 text are explicit. Spec 027 shows FR wording and records drifting apart today, so a derived block would sit next to FRs that say the same thing in other words. That is duplication, and a reader may not know which one governs.
3. **Counter-evidence.** DEC-194 is a later, explicit owner direction. Fenced and hash-stamped blocks never touch authored text, and records remain the only authority. Drift without derive already gives value: it found 7 unrecorded FRs in 027 and 7 superseded citations in Telosmith's own specs.
4. **If the concern is right.** People edit derived blocks, get skipped and reported, and stop trusting them, or blocks go stale because nobody runs `derive`. The cost is noise, not corruption: authored text and records are never changed.
5. **What to test, escalate or decide.** Escalate: the amendment wording (Zach). Test: one real feature end to end in a repo that opts in (Fathom's next spec, after a Fathom-lane handoff), with authoring time logged in `docs/speckit-log.md` against the baseline. Decide: whether `drift` runs in CI (report-only) before `derive` is offered at all.

## Stress test (QAT stress-test skill, run on this note and the prototype)

- **Hidden assumption: records hold the wording a feature spec needs.** In the Fathom trial they mostly don't. Records hold product-level requirements and FRs hold feature-level ones, so a derived block fills in the cross-cutting part and the FRs stay authored. *Taken*: the mapping says so. The bigger saving may run the other way: FR → provisional record (write-back) turns drafting into recording.
- **Backfire: the hash guard freezes blocks on harmless changes.** A CRLF checkout (Windows, `core.autocrlf`) or an editor that trims trailing spaces would have made every block look hand-edited, and every block would have stopped regenerating. *Taken and fixed in the prototype*: the hash ignores line endings and trailing whitespace, derive keeps the file's line endings, and there is a test.
- **Backfire: `uncovered-record` noise trains people to ignore drift.** *Taken as an open item* (see the trial): narrow the default scope before drift goes into CI.
- **Pushback (Spec Kit side and constitution I): restating records in specs is the duplication the project exists to prevent.** *Taken*: it is the blocking question above. It is not rejected, because the blocks are views and never sources.
- **Reversal: ship drift and write-back only, and never write to specs.** That keeps the constitution as it is and still finds the gaps (7 FRs in 027). *Offered to Zach as option B* below, not adopted, because DEC-194 explicitly asks for derivation.
- **The uncomfortable tweak**: don't put `derive` in the extension or the docs' happy path until one real feature in an opted-in repo shows lower authoring time than the baseline (`AEC-R3`).

## Options for Zach

- **A (as prototyped).** Amend constitution I and `AEC-R1`; ship `derive` and `drift` as manual commands; no hooks.
- **B (narrower).** Ship `drift` and write-back proposals only. Constitution unchanged. Revisit `derive` after one measured feature.

Both keep Spec Kit optional. Recommendation: B first, then A once one measured feature supports it. This is a proposal; the decision is Zach's.

## Not in this note

plan.md and tasks.md derivation; multi-line FR capture; any change to existing record contracts; automatic triggers. Each needs its own spec.

QAT: stress-test (concerns 1, 2, 4 taken; 3 open; the reversal kept as option B and not adopted, because DEC-194 asks for derivation).
