# Braided Dual-Channel Coding: the development method, and how Telosmith changes reach every repo

Author: claude:aec#wake-20261117-19 · Reviewer: Kate (API instance, gpt-6.1-sol, 2026-11-17T19:19Z; reviewed the summary, not this text; her conditions are applied below and marked "Kate") · model=claude-opus-5-5

Status: **proposed** (`AEC-D-braided-dcc@1`, `epistemic: provisional`). Nothing here is adopted until Zach accepts it.
Rollout was approved live on 2026-11-17 ("Review it, then roll it. We'll figure it out, live, and learn from the
ordeal", Zach, quoted by the coordinator in the handoff); this page is what the rollout follows and what it learns against.

## 1. What the method is

Dual-Channel Coding keeps two coupled representations of a change: the **code channel** (what runs) and the
**semantic channel** (purpose, requirement and decision records that say why it runs and what it must do).
The **Braided** version (owner decision in the private ledger, DEC-099 item 3) splits the work across three actors
so no one actor writes both channels and then grades them:

| Role | Default actor | Inputs | Outputs |
|---|---|---|---|
| **Implementer** | the repo's lane (`claude:<lane>`) | the handoff, the semantic records as they stand | code, tests, `implemented_by`/`evidence` links, a PR |
| **Semantic maintainer** | the lane's paired Kate (`chatgpt:kate…`), a different model family; fallback Research or a fresh-context Claude session | the handoff's intent, the PR diff, the current `.aec/` records | new or versioned purpose / requirement / decision records with `authored_by` + `author_role: independent`; a drift note (below) |
| **Reviewer** | Codex (Copilot findings still get a Codex re-review, lane-rules §2) | the PR, both channels | review findings on the code **and** on whether the records match it |

The owner (Zach) stays the only actor who accepts a decision (`author_role: owner` when he writes a record himself).

### What the semantic maintainer checks (drift between code and records)

For each PR, before it is marked ready:

1. **Coverage, both ways:** every changed requirement has code and tests that `implemented_by` points at, **and** every
   new or changed behaviour in the diff is served by a requirement, so undocumented behaviour can't escape. (`aec check
   --edges` already finds dangling code references; the second direction is read by a person.)
2. **Direction:** the code does what the record says, not something adjacent. The implementer's PR text is evidence of
   intent, not of behaviour; the maintainer reads the diff and tests.
3. **Upstream ownership:** a downstream module is not quietly deriving what an upstream one owns (the October 2026
   simulator-parsing case in MtG is the reference example).
4. **Scope:** the change stays inside the purpose (`serves` chain to the repo's P0). Anything outside is a proposal
   for the owner, not a record edit.
5. **Evidence and open disagreement** (added on Kate's review): what supports each claimed requirement-to-code match,
   what is still unverified, and which objections are still open.

A maintainer who was not given the diff, the applicable records and the test evidence reports the PR as **not
assessed**, never as clean (Kate: a blocking condition).

The maintainer writes what it finds as records (a new version, or a `claim` with `epistemic: provisional`) or, when
it disagrees with the implementer and cannot settle it, as a challenge for the owner. It never edits code.

### How authorship is recorded

`AEC-R-authorship@1` already gives every record two optional fields, checked for shape only:

- `authored_by`: an actor id (`zach`, `claude:crank`, `chatgpt:kate#<session>`);
- `author_role`: `owner`, `independent` or `implementer`, said of the author's relation **to the code the record describes**.

A record written by the semantic maintainer carries `author_role: independent`; a record the lane writes for its own
code carries `implementer`. When Kate's text reaches the repo through another actor (the API Kate reply is committed by
a lane), `authored_by` names Kate and the commit names the transcriber: authorship is who wrote the words.

`author_role: independent` is a **declaration, not a test** (Kate). A different model family does not by itself make
the author independent, and nothing may claim verified independence from the field alone. Drift can hide in the
transcription step (selective copying, dropped dissent, edited links, stale code context, or a brief the implementer
curated). So a transcribed record keeps:
- a `source` reference to the maintainer's reply (for API Kate, the `kate-replies` file and its hash);
- the authored text exactly as written;
- the code revision the maintainer was shown;
- the committer, separate from `authored_by` (the git commit already gives this).

A mechanical change to transcribed text (reformatting, a fixed link) is stated in the commit. A change in meaning goes
back to the maintainer for review.

### What `aec check` should report (fields first, enforcement later)

Proposed, not built in this PR:

- **Summary line** in `aec check` output: `semantic channel: N independent, M implementer, K unattributed` over
  purpose, requirement and decision records that have an `implemented_by` relation. Information only; exit code unchanged.
- **Self-maintained record (info):** a requirement with `author_role: implementer` and an `implemented_by` relation is
  listed as `self-maintained`, so the rollout can count it. Not a warning: during rollout most records will be this.
- **Contradiction (warning):** a record that says `author_role: independent` while its `authored_by` is the same actor
  prefix as a new optional `implementer` field on the same record (e.g. both `claude:crank`). This is the one case where
  the fields contradict themselves, so it is worth a warning. `check` cannot know who wrote the code otherwise, and
  should not guess from git.

Why fields first: Zach asked that Telosmith checks not become blocking before he has seen a week of results (handoff
limits). Counting is enough to measure the pilot. A blocking rule would also punish lanes that have no working Kate
route yet.

### What the separate semantic channel adds beyond writer-plus-reviewer pairs

The coordinator's outside reading (2026-11-17) found that writer-plus-reviewer pairs outlast swarms and that review is
now the bottleneck. A reviewer reads one PR against the code; it does not own the records, so the reasons for a change
are re-derived on every review and forgotten after it. The asserted benefit (DEC-200: plausible and explainable, not yet
demonstrated) is:

- **review gets shorter**, because the reviewer checks code against records someone else wrote, instead of
  reconstructing intent from the PR text (this is the measure "review-response commits per feature");
- **drift is caught by someone with no stake in the code** (a different model family by default), which is the measure
  "drift caught by independent vs implementer records";
- **the reasons survive the PR**, so the next change in the same area starts from them.

Counter-reading, recorded so the pilot can test it: the extra actor adds a round-trip, and if Kate's records arrive
after the PR is ready they add commits rather than remove them. The wall-clock measure is there to catch that.

## 2. Propagation: one Telosmith change, every repo, no hand-made commit per repo

**Cost today (coordinator's measurement, 12–17 Nov):** 21 of about 258 product-repo commits were the same Telosmith
hook re-roll copied into about 12 repos. The reason is visible in any consumer's `.claude/settings.json`: the
project-level hook from `aec init` inlines about 1,500 characters of shell (PYTHONPATH scrubbing, symlink refusal,
the edges/check/code-impact sequence). Every fix to that logic is a text change in every repo.

| Mechanism | What propagates without a per-repo commit | What still needs one | Fit |
|---|---|---|---|
| **A. Pinned release + bot bump** (MtG's `tools/aec_upstream.json` and weekly `aec-upstream.yml` already do this) | nothing by itself; the bot writes the commit | one bot PR per repo per release, each for Zach to merge | good for CLI behaviour; does not move inlined hook text |
| **B. Reusable workflow** (Lydian's `kairos-checks`, called by ref) | CI logic, if repos call a moving ref | nothing for CI; but CI cannot change an agent's local hook | good for CI; misses the hook, which is where the 21 commits were |
| **C. `aec sync` into each repo's `.aec/`** | nothing; it writes files into each repo | one commit per repo, made by a tool instead of a person | cheaper than today, same count |
| **D. Package-owned hook body** (`aec hook run`, the user-level hook drafted for DEC-223, `src/aec/userhook.py`) | the hook's logic: it lives in the installed package; settings hold one stable line | a version bump (A) when Telosmith changes | removes the cause: the per-repo text stops changing |

**Recommendation: D + A + B, each owning one layer.**

- **Telosmith owns** the hook body (`aec hook run`) and the records format. Repos stop inlining hook logic: the
  per-repo snippet from `aec init` becomes one line that calls the installed `aec` (or the user-level hook, once
  DEC-223 is decided). After that, a hook fix is a Telosmith release, not 12 commits.
- **Lydian owns** the CI that installs a pinned Telosmith and runs `aec check` (B), and the bot that proposes pin bumps
  (A), generalising MtG's `aec-upstream.yml` into one reusable workflow. One pin file per repo; one bot PR per release
  per repo, batched on the daily decision sheet.
- **Not recommended:** C, because it moves the commit from a person to a tool without removing it.

What D does not remove (Kate): per-repo pin bumps, and the gap between the version CI pins and the version a lane's
local hook resolves. Its risks are a hook that picks up an unintended global `aec`, a missing install, changed exit
semantics, and a larger blast radius for a bad release. **Before any repo's existing hook is replaced** (Kate: a
blocking condition):
- the one-line hook resolves the pinned version locally;
- a missing install or a version mismatch gets an explicit diagnostic;
- compatibility tests show the same exit behaviour as today's hook;
- a rollback path is written down.

The enforcement policy stays advisory.

Until D lands (it changes `aec init` output and is its own PR), the handoff's interim applies: propagate the method via
the lane-rules change and one Telosmith release pin.

## 3. Pilot: the crank-mem rebase (HO-CRK-20261117-CFKR part B)

- **Implementer:** the Crank lane (`claude:crank`), on its own branch from Chris Liva's v0.16.0.
- **Semantic maintainer:** Crank's paired Kate, through `## For Kate` in the Crank lane's output: for each "keep" change
  from part A, she writes the requirement record (`authored_by: chatgpt:kate`, `author_role: independent`); the lane
  commits it verbatim. Fallback if no reply within one wake: a fresh-context Claude session, labelled same-family.
- **Reviewer:** Codex on the PR, as today.

**Measures**, reported weekly in the AEC output for HO-AEC-20261117-DBN5, against the baseline the coordinator measured
for 12–17 Nov:

| Measure | Baseline | How counted |
|---|---|---|
| Review-response commits per feature | 48% of product-repo commits | commits on the PR after the first review, ÷ features ("keep" items) |
| Copied cross-repo commits | 21 (12–17 Nov) | commits with the same Telosmith change in more than one repo |
| Drift caught, independent vs implementer records | none recorded | review or maintainer findings that cite a record, split by the record's `author_role` |
| Wall-clock to a ready PR | per PR, from the GitHub timeline | first commit to `ready_for_review` |

The pilot is one PR, so it shows whether the method runs and what it costs, not whether it works in general. The next
two or three lanes (handoff order of work) give the comparison.
