# probe-001 rerun, 2026-11-24: same tasks, today's Telosmith

Author: claude:aec#wake-20261124-03 · Reviewer: none yet (Codex on the PR) · model=claude-opus-5-5 (trials: claude-sonnet-5-5; T3 grader: claude-haiku-5-5)

**What this is.** A rerun of [probe-001](probe-001.md) with its frozen tasks, hidden tests, prompt template,
grading criterion and pre-registered reading rule, on the same Data-Guide commit (`0607401`). Only one
input changed: the B and C briefings were regenerated with today's Telosmith (main `98bbab5`, extractor
`tool_version` 0.4.1) instead of AEC `4779429` (0.3.0). Asked for by HO-AEC-20261123-ER2R (DEC-270 (4)).
All 22 frozen files still verify against `probe-001/FREEZE.sha256` (22 OK, 0 failures). Every file of
this run is in [`probe-001-rerun-2026-11/`](probe-001-rerun-2026-11/). Every result is exploratory
(amendment 7).

## What this probe can and can't show

Read this before the tables.

- **It can't show better outcomes.** On 2026-11-01 every trial in every condition succeeded (18/18).
  That is a ceiling: success can't go up, so the primary outcome can only show harm (a drop), never help.
- **It can show cost, and what the agents did.** The only pre-registered positive reading left open is
  "lower cost": B at least 25% below A in median total tokens on at least 2 of 3 tasks.
- **It is not a test of whether Telosmith "works".** These tasks were built so that a grep finds every
  dependant (threat 3 in the original). Passing them says little about code where search fails.
- **Nothing was tuned to get a different result.** Tasks, hidden tests, prompt template and criterion are
  the frozen files. Harder tasks belong in a separate, pre-registered probe-002, not in this rerun.

## The answer, by the pre-registered rule

**No signal, and no harm, again.** 18 of 18 trials succeeded. Lower-cost rule: met on **0 of 3** tasks
(best: B −10% on T2).

| Task | A: repo only | B: relevant briefing | C: irrelevant briefing |
|---|---|---|---|
| T1 hidden dependant (`profile_dataset`) | 2/2 | 2/2 | 2/2 |
| T2 return-shape change (`understand`) | 2/2 | 2/2 | 2/2 |
| T3 false premise (`credentials.py`) | 2/2 | 2/2 | 2/2 |

Data-Guide's own 89 tests passed on all 18 final repositories. The blind T3 grader judged all six T3
reports adequate.

## Side by side with 2026-11-01

Median total tokens of B and C relative to A, within each run:

| Task | B, 11-01 | B, 11-24 | C, 11-01 | C, 11-24 |
|---|---|---|---|---|
| T1 | +23% | **0%** | +23% | +83% |
| T2 | −7% | −10% | −15% | +21% |
| T3 | +59% | −7% | +41% | −11% |

Median tool calls (A / B / C):

| Task | 11-01 | 11-24 |
|---|---|---|
| T1 | 9 / 10 / 11.5 | 8 / 7.5 / 14.5 |
| T2 | 10 / 8 / 8 | 8.5 / 7.5 / 9 |
| T3 | 4.5 / 6 / 6 | 6 / 6 / 5 |

How to read it:
- **The one real change in the input: T1's briefing now names the hidden dependant.** On 11-01 it said
  "Resolved callers: none found" (the extractor left `profiler = DataProfiler(...); profiler.profile_dataset()`
  unresolved). Today it lists `src.profilers.univariate.profile (src/profilers/univariate.py:30)`.
  Unresolved calls repo-wide fell from 874 to 849 of 1,578. The other five briefings differ only in that count.
- **What the agents did with it.** Both T1 B agents opened `src/profilers/univariate.py` in their first
  command, alongside a grep. Both A agents found it by grep in their first or second command. Same fix,
  same cost (B 0% against A). The corrected caller list saved nothing measurable, because search was
  already enough.
- **B no longer costs more than A** (11-01: +23%, −7%, +59%; now 0%, −10%, −7%). With two trials per cell
  that is within the spread between replicates (T3 B: 0.31M and 0.53M). Don't read it as an improvement.
- **Irrelevant briefings: no misattribution this time.** On 11-01, 3 of 6 C agents read the unrelated
  briefing as bearing on their task. Today all 6 C reports call it unrelated. C was the most expensive
  arm on T1 (+83%: 14 and 15 tool calls) for no better result.
- **Don't compare absolute tokens across the two runs.** Medians for A fell (T1 1.04M → 0.59M), but the
  harness changed between runs (the subagent's system context and the hand-back tool; see Deviations).
  Only ratios within a run are comparable.

Per-trial cost (11-24):

| Task | Cond | Trial | Tool calls | Total tokens | of which cache reads | Output tokens | Success |
|---|---|---|---|---|---|---|---|
| T1 | A | R174 | 8 | 0.60M | 88% | 5,014 | yes |
| T1 | A | R177 | 8 | 0.59M | 89% | 4,095 | yes |
| T1 | B | R563 | 8 | 0.64M | 90% | 4,249 | yes |
| T1 | B | R655 | 7 | 0.54M | 87% | 4,207 | yes |
| T1 | C | R641 | 14 | 1.00M | 90% | 8,011 | yes |
| T1 | C | R697 | 15 | 1.17M | 91% | 10,755 | yes |
| T2 | A | R398 | 8 | 0.59M | 88% | 6,083 | yes |
| T2 | A | R910 | 9 | 0.65M | 90% | 4,062 | yes |
| T2 | B | R675 | 7 | 0.54M | 88% | 5,229 | yes |
| T2 | B | R821 | 8 | 0.58M | 89% | 3,799 | yes |
| T2 | C | R356 | 10 | 0.86M | 92% | 7,385 | yes |
| T2 | C | R460 | 8 | 0.64M | 90% | 4,654 | yes |
| T3 | A | R127 | 6 | 0.42M | 85% | 2,114 | yes |
| T3 | A | R703 | 6 | 0.49M | 86% | 4,705 | yes |
| T3 | B | R245 | 7 | 0.53M | 88% | 5,778 | yes |
| T3 | B | R874 | 5 | 0.31M | 81% | 1,897 | yes |
| T3 | C | R159 | 5 | 0.43M | 84% | 4,911 | yes |
| T3 | C | R753 | 5 | 0.37M | 83% | 2,531 | yes |

"Total tokens" counts input, output, cache reads and cache writes, as on 11-01 (`tools/transcript.py`).

## What it means

1. **The extractor gap probe-001 found is closed, and on these tasks it didn't matter.** The fix made the
   T1 briefing accurate; agents with grep didn't need it. This is the ceiling again, not a failure.
2. **The claim Telosmith can honestly make from probe-001 is narrow:** its briefings did no harm on these
   tasks, an irrelevant one can cost more, and a capable agent with search found every dependant without it.
   Not that it makes agents better. No README or launch sentence should say more.
3. **Telling more needs different tasks,** where search fails (dynamic dispatch, string-keyed registries,
   larger repositories), or budget-capped agents. That is probe-002's job, pre-registered on its own.

## Pre-launch rerun (plan)

- **When:** in the week before launch, after the last Telosmith change that touches `edges`/extraction,
  and before any launch text cites probe-001.
- **At which revision:** the launch release tag (or, if not tagged yet, the commit the release notes name).
  Record it, the extractor `tool_version` and the edge-snapshot SHA-256, as here.
- **How:** exactly as this run: frozen files verified first, briefings regenerated mechanically, new seed,
  Sonnet trial agents, the Haiku T3 grader with only the criterion and reports, the tables above plus a
  third column. Fix the three deviations below that are fixable (grade-tool paths parameterised; the
  report-write refusal handled the same way for every trial; tool calls counted without the hand-back).
- **What it may say:** the same narrow claim, or a narrower one. If success ever drops below 2/2 in B or C
  for any task, that's harm and goes first.

## Deviations

- **C decoys kept, not re-chosen.** The decoy rule run on today's graph picks different symbols (T1
  `ast_dependency_cli.ASTDependencyExtractor`, T2 `src.cli._build_connector`, T3
  `ast_dependency_cli.ASTDependencyExtractor.__init__`), because resolved-caller counts changed. I kept the
  frozen decoys and regenerated their neighbourhoods, so that only the tool version differs between runs.
  T2's rule pick today, `cli._build_connector`, would also fail the irrelevance check (it names `src/cli.py`).
  Briefing lengths (characters, B/C): T1 1008/558, T2 1186/1221, T3 1558/1716, all within a factor of 2.
- **Environment.** Data-Guide's test dependencies were installed into the session (`typer`, `sqlalchemy`,
  `pyyaml`, `missingno`, its declared requirements). Many trial agents hit their 2-minute shell limit on
  the full suite (cold imports took about 65-75 s; five agents still got a full green run) and ran test
  files separately. That affects cost, in every arm; it doesn't affect the mechanical outcome, which
  `tools/grade.py` measured on a clean copy.
- **Reports.** 16 of 18 agents wrote `REPORT.md`; two (R697, R703) were refused by the harness and their
  reports were recovered from the final message (marked at the top), as on 11-01.
  After grading, `tools/transcript.py` (the 11-01 script) overwrote R703's recovered report with an interim
  message ("Tests hung; …"), the same bug 11-01 hit on P902. The published file was restored to the exact
  text the grader saw (byte-identical to the grader's copy); Codex caught the mismatch on #115.
  `tools/transcript.py` now leaves an existing recovered report alone.
- **Tool calls include the hand-back call** each subagent now makes at the end (+1 in every trial, all
  arms). Absolute token counts differ from 11-01 for the same harness reason.
- **Blinding.** As on 11-01, a reader can tell A from B/C: B and C reports mention the briefing. The
  primary outcome is mechanical. No blind grade of T1/T2 diffs (not done on 11-01 either).
- **Same family throughout:** a Claude session ran the probe, Claude subagents were the trials and the
  grader. Codex reviews the write-up.
- **One wake.** Briefings, trials, grading and this write-up were done in one scheduled run on 2026-11-24.

## Reproducibility

- Data-Guide `0607401`; Telosmith `98bbab5`, extractor 0.4.1, default settings, 46 files, 2,427 edges, 0 skipped
  (`edges-2026-11-24.jsonl`). Seed `20261124`; trial ids exclude the 11-01 ids.
- `SHA256SUMS` covers the briefings, edges, schedule and tools. `tools/grade.py` and `tools/transcript.py` are the
  11-01 scripts with paths changed; `tools/analyse.py` builds the tables above.
