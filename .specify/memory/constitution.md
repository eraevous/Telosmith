<!--
Sync Impact Report
- Version change: 1.0.0 → 2.0.0 (MAJOR: Principles I and V redefined)
- I. Purpose Lives in Telosmith Records: "MUST NOT rewrite specs" replaced by the derived-block rule
  (DEC-194, DEC-201; AEC-R1@2). Spec Kit still owns the workflow; authored text is never touched.
- IV. Claim honesty: unchanged rule; adds that an asserted benefit is not a claim (DEC-200).
- V. Earn It: baseline per setup (AEC-R3@3, replacing the Spec-Kit-only baseline left stale since
  AEC-P0@2); adds the asserted-benefit gate and first-class exploration (DEC-200).
- Record references re-pinned to current versions (AEC-P0@3, AEC-R1@2, AEC-R3@3).
- Templates requiring updates: none (plan/spec/tasks templates read this file at runtime)
- Previous Sync Impact Report (1.0.0, 2026-10-26): initial ratification, Principles I–VI.
-->
# Telosmith (AEC) Constitution

## Core Principles

### I. Purpose Lives in Telosmith Records (no competing authority)
Purpose, authority by subject, evidence status and criteria versions live in `.aec/records.jsonl`,
in Telosmith's own record format. This constitution **references** them and does not restate them:
`AEC-P0@3` (purpose), `AEC-R1@2`…`AEC-R4@1` (requirements, `AEC-R3@3`), `AU-zach@1` (design and
acceptance authority), `AU-speckit@1` (workflow authority). Spec Kit owns the workflow: specs, plans,
tasks, analyze, converge. Telosmith findings go back into that workflow as review items, and Telosmith
never overrules the owner.
Specs MAY carry **derived blocks**: fenced, hash-stamped regions (`<!-- telosmith:derived … -->` …
`<!-- telosmith:end -->`) that Telosmith regenerates from records by an explicit command, never from a
hook. Telosmith MUST NOT edit authored text outside those fences; a derived block edited by hand is
reported and skipped, not overwritten. Drift between specs and records is reported, and proposed record
changes stay provisional until accepted. A feature spec MUST cite the Telosmith purpose or requirement
it serves by `id@version`.
Rationale: two documents that both claim authority over purpose is the failure Telosmith exists to
prevent. Derived blocks are views of the records, so they add no second authority, and they spare
people the tedious drafting and upkeep of specs (DEC-194, DEC-201).

### II. Standard Library, Deterministic, Inspectable
Runtime code MUST use only the Python standard library (3.10+). Every command MUST produce the same
output for the same input; ordering MUST be stable so outputs diff cleanly. Records are append-only
JSON lines with `id@version` references. No graph database or service is introduced unless plain
records are shown to be insufficient, and that has to be recorded as a decision.
Rationale: AEC has to run anywhere the code it governs runs, including CI and other people's repos.

### III. Checks Are Tested by the Violations They Exist to Catch (NON-NEGOTIABLE)
Every check or classifier ships with at least one fixture that **violates** it and fails, and at
least one clean decoy that MUST NOT be flagged. Tests come before implementation for each check.
A check without a failing fixture is described as "planned", never as "enforced".
Rationale: over-flagging is a failure too, and an untested enforcement claim is a false claim.

### IV. Structural ≠ Purpose (claim honesty)
Outputs and docs MUST label deterministic results as structural. No document, README or report may
claim that Telosmith preserves purpose, reduces failures, or beats its baseline unless that is backed
by a recorded comparison (`AEC-R2@1`). An asserted benefit (Principle V) is a reason to build, not a
claim: it is not stated as an outcome until it is measured. Decisions are never declared invalid by a
tool. They are flagged for the governing authority.
Rationale: plausible intermediate results presented as justified conclusions are the problem class itself.

### V. Assert the Benefit; Earn It Against the Baseline
Nothing is built without an **asserted benefit**: a plausible, explainable improvement with its
mechanism stated, recorded with the work (in the PR or its records). The benefit may be expected to
show up only much later and be hard to test; it still has to be stated. Work without one is allowed
only as a labelled `experiment` or exploration, and exploration and discovery are first-class
(DEC-200). Shipping live to learn is allowed before the benefit is demonstrated.
Value is *judged* against a well-configured baseline for the setup in use, with authoring and
maintenance cost counted (`AEC-R3@3`): a well-configured Spec Kit, another agentic coding system
without Telosmith, or the same work done standalone without it. Where the baseline performs as well,
the outcome is to simplify Telosmith. Such comparisons run on live use and do not block shipping.
Rationale: you can't iterate on something kept in a glass box, but nothing pointless should be built;
the gate is a stated reason, the judgement is a measured one.

### VI. Bedrock Facts Come From the Code
Structural facts about a codebase (what defines, calls, imports and refers to what) MUST come from
deterministic static analysis of the code itself, never from model summaries. They are cheap enough
to regenerate on every change. Records and contracts *reference* these facts; they do not copy them.
Rationale: the AST edge graph is the one layer that cannot drift from the code, so everything else anchors to it.

## Additional Constraints

- Spec Kit is optional (`AEC-P0@3`). Where it is used it is pinned (v1.2.3); integration happens through Spec Kit's extension and hook mechanism
  (`.specify/extensions.yml`), never by editing Spec Kit's core templates or scripts.
- AEC must be installable into another repository (first target: Data-Guide), not copied by hand (`AEC-R4@1`).
- The 2025 Codex++ conventions (`.purpose.md`, `.intent.md`, `AGENTS.md`) remain supported. New
  machinery must not break them.

## Development Workflow

- Spec Kit sequence per feature: `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` →
  `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement` → `/speckit-converge`.
- Alongside each stage, AEC records are appended (purpose links, assumptions, decisions), and
  `python -m aec check` MUST pass before implementation and after convergence.
- Every PR runs the unit tests, `aec check` on `.aec/records.jsonl` and on the examples, and the AEC drift
  checks once they exist. A PR that adds a subsystem includes a dissent review: what it might violate,
  the evidence for and against, what follows if the concern is right, and what to test.

## Governance

This constitution supersedes ad-hoc practice for this repository. Amendments require a recorded
decision event approved by `AU-zach@1`, with a semantic version bump: MAJOR when a principle is removed
or redefined, MINOR when one is added or materially expanded, PATCH for wording. Purpose changes are
made in `.aec/records.jsonl` as new record versions with a `supersedes` relation. Earlier versions are
never edited. Every PR review verifies compliance with Principles I–VI. Unjustified complexity is a
review finding.

**Version**: 2.0.0 | **Ratified**: 2026-10-26 | **Last Amended**: 2026-11-10 (DEC-200, DEC-201)
