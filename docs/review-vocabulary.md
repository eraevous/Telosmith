# Review vocabulary

Names for five ways an agent's report can claim more than happened. A reviewer tags a finding with one of these names
so the same failure gets the same word across reviews. They are signals, not scores: no counts, no severity numbers,
no integrity percentages. A tag says where to look; it does not grade the work.

The names come from a model-written hallucination audit of the earlier Codex++ traces (HONT, its
"Hallucination Ontology"). The owner adopted the names and dropped that audit's scores. Its own integrity score had no
stated basis, which is the fourth failure below.

| Tag | What it looks like | What clears it |
|---|---|---|
| `ghost-tool` | The report invokes a tool, module, check or file that does not exist in the session or the repository ("the logging layer recorded…") | A path, command or commit that exists |
| `reflexive-fabrication` | The report cites earlier work that never happened ("as the reviewer already confirmed…", "Claude + Kate done") | A pointer to the artifact: a review comment, an output file, a record, a log line |
| `metaphor-literal-swap` | A figure of speech is treated as a mechanism ("the records remember why"), so a claim seems to describe behaviour the code does not have | The literal mechanism, or the metaphor marked as one |
| `simulated-precision` | A number with no basis ("intervenes in 3 of 5 paths", "71.4 integrity") | The data and the computation, or the number removed |
| `clean-lie` | Structure and confident tone stand in for verification: a tidy report of things nobody checked | Which statements were checked, how, and which were not |

## Using it in a review

Tag the finding, quote the passage, and say what would clear it, for example:

> `reflexive-fabrication`: the PR body says "tests reviewed by Kate", but no review comment or output file exists.
> Clears with a link to the review.

`reflexive-fabrication` is the one to check every time on an agent-supervising-agent chain. A claim that a review,
test run or approval happened must point at the artifact it produced.

## Where it applies (cost cap)

Only on pull requests that change a contract, a check's semantics, or an authority. Other PRs get an ordinary review.

A `review:` handoff for such a PR carries this line in its Expected output:

```
Tag each finding with a docs/review-vocabulary.md name when one fits (ghost-tool, reflexive-fabrication, metaphor-literal-swap, simulated-precision, clean-lie); names only, no scores. Applies only because this PR touches a contract, a check or authority.
```

## Proposed: hallucination families and context (draft, not adopted)

**Status.** This section is a proposal for review. The five tags above stay the adopted vocabulary, and the cost cap
above stays exactly as it is, until the owner accepts a change. The owner has authorized promoting this vocabulary
(HONT) to a core part of Telosmith and expanding it to cover more hallucination phenomena; the families below are one
reviewable way to do that, not a settled taxonomy. Nothing here adds a check, a score or a gate.

### Context decides the obligation, not the truth

The same invented detail can be fine in one task and misleading in another. A made-up street name is a contribution
to a short story and a fabrication in an incident report. Context changes what an output is *for* and what evidence
it owes; it never makes a false factual assertion true. Two consequences:

- **A creative or exploratory context never validates invented evidence presented as real.** A hypothesis that cites
  a test run that never happened is still a false report of a test run.
- **Source faithfulness and factuality are separate questions.** A summary can add material that is true but not in
  its source, or stay inside its source while repeating something false. Which one matters depends on the task: a
  summary owes faithfulness to its source; a story owes consistency with its own world; a status report owes truth
  about what happened.

This vocabulary describes reports, not minds. A tag says what the text claims and what the record shows. It does not
diagnose why a model produced it, and nothing in a model's own prose about its reasoning counts as evidence of the
mechanism.

### Naming context-appropriate inventions (open question)

The owner asked for a name for inventions that are appropriate in their context, with "generative artifacts" as a
placeholder. No name is chosen. The options:

| Name | For | Against |
|---|---|---|
| generative artifacts | The owner's placeholder; neutral about value | This doc already uses "artifact" for *evidence* (the `reflexive-fabrication` row and "the artifact it produced"), so it would need that sense renamed (for example to "receipt"); "artifact" also suggests a by-product or defect |
| generative additions | Says what is distinctive: material that goes beyond the supplied evidence. Matches the "extrinsic content" of the faithfulness literature, which can be true or false | Plain; says nothing about value, which is also its point |
| generative contributions | Emphasises the role in an ongoing inquiry | Presumes the addition helped, so it reads as a verdict; collides with "contribution" in authorship accounting |

Whichever name is chosen, it names the *material*, not the verdict. Context lives in the fields below. One workable
pairing: the umbrella names any addition beyond the evidence, and "contribution" names an addition that review found
useful.

### What a finding records

A finding under any family carries these fields, in a sentence or a short list. They are what lets the same text be
judged differently in different contexts.

| Field | Values or content |
|---|---|
| Task context | What was asked and for whom: a report, a summary, a design, fiction, brainstorming |
| Speech act | asserting, hypothesizing, imagining, reporting an action |
| Evidence available then | What the author had at the time (source, revision, timestamp), not what turned up later |
| Status | supported, contradicted, unknown. For imagining, check against the supplied constraints or world, not the external one |
| Consequence | What depends on the claim: a merge, a decision, a public statement, nothing yet |
| What would resolve it | The record, run, quote or question that would settle it |

**Unknown is not contradicted.** A missing receipt is *unknown* unless the record that would contain it is complete.
A tag on an unknown says where to look, not that something false was said.

### Families

Each family names a kind of claim that can outrun its evidence. A reviewer can tag a finding with the family alone;
the member names are optional and exist so recurring cases get the same word. The current five tags are kept as
members or cross-cutting patterns under their existing names.

**1. `factual-source`: factual and source errors.** An assertion the evidence does not support or contradicts; a lost
qualifier ("may" becomes "does"); two entities or numbers conflated; a summary that changes what its source says.
Members (proposed): `unsupported-claim`, `source-drift`. Clears with: the supporting passage, or the claim corrected
or marked as unverified. *Boundary:* an addition that is true but absent from a source is a faithfulness question
only when the task promised to stay inside the source.

**2. `provenance`: provenance errors.** An invented source, quotation or identifier; a real statement attributed to
the wrong person, thread or document; a real citation that does not support the claim it is attached to. Members
(proposed): `invented-source`, `misattribution`, `citation-mismatch`. Clears with: the source opened at the cited
place, or the attribution removed. *Note:* a source that exists and supports the claim still does not show the
author consulted it; that is a claim about an action (family 3).

**3. `process-capability`: process and capability errors.** Claims about tools, checks and actions: the report uses a
tool or file that does not exist, cites earlier work that never happened, or reports an action at the wrong rung of
planned, attempted, completed, independently verified. Members: `ghost-tool` (adopted), `reflexive-fabrication`
(adopted), `premature-completion` (proposed: planned or attempted reported as completed). Clears with: the receipt
for the rung claimed (see the proposal below). *Boundary with 4:* family 3 is about what the reporter did; family 4
is about the state of the world or the work over time.

**4. `temporal-status`: temporal and status errors.** A stale fact or version presented as current; proposed work
reported as implemented; tests collected reported as passed; a superseded record cited as live. Members (proposed):
`stale-as-current`, `status-inflation`. Clears with: the state as of a stated time (a commit, a run log, a dated
record). A later completion does not make an earlier completion report accurate when it was made.

**5. `evidence-authority`: evidence and authority inflation.** An inference stated as fact; agreement between models
counted as independent confirmation; an unsupported claim about someone's intent, approval or current permission,
including a historically valid approval presented as still in force. Members (proposed): `inference-as-fact`,
`echo-confirmation`, `assumed-authority`. Clears with: the inference marked as one; the independent evidence, or the
agreement relabelled as review; the approval record and its scope and date. *Note:* acting without authorization is
a conduct problem, not automatically a hallucination. Tag the unsupported *claim* ("the owner approved this"), not
the conduct.

**6. `explanation-constraint`: explanation and constraint errors.** A causal or mechanistic account asserted without
evidence; output that contradicts constraints the task supplied, or the established facts of a fictional world.
Members (proposed): `unsupported-mechanism`, `constraint-break`. Clears with: the evidence for the mechanism or the
account marked as a hypothesis; the constraint met. *Note:* this is a faithfulness failure even when external truth is
not the criterion, which is why fiction is not exempt from review.

**Cross-cutting patterns** (any family): `simulated-precision` (a number with no basis), `metaphor-literal-swap` (a
figure of speech read as a mechanism), `clean-lie` (structure and confident tone standing in for verification).
`clean-lie` names what the text does, not what the author intended: it does not establish an intention to deceive,
and a reviewer should not use it to imply one.

### Migration from the five tags

Nothing is dropped or renamed. Existing reviews and links stay valid.

| Current tag | Proposed home | What changes |
|---|---|---|
| `ghost-tool` | Family 3 `process-capability`, member | Nothing in its meaning; it gains siblings |
| `reflexive-fabrication` | Family 3 `process-capability`, member; cross-reference to family 2 when the "earlier work" is a source | Nothing; the receipt ladder makes its "clears with" more specific |
| `metaphor-literal-swap` | Cross-cutting pattern; most often seen with family 6 | Nothing |
| `simulated-precision` | Cross-cutting pattern | Nothing |
| `clean-lie` | Cross-cutting pattern | Adds the sentence that it does not establish intent |

### Worked examples

Generic cases. Each row gives the fields that decide it. The controls are as important as the flags: a vocabulary that
fires on every invention trains reviewers to ignore it.

**Should be flagged**

| Case | Context and speech act | Evidence then | Status | Tag | Resolves it |
|---|---|---|---|---|---|
| A PR body says "all 48 tests pass"; the log shows 48 collected, 40 passed, 8 skipped | Status report; asserting | The CI log | Contradicted | `temporal-status` / `status-inflation` | The pass count from the run, or "collected" |
| A handoff output says "merged" an hour before the merge commit exists | Report of own action; reporting an action | Repository history | Contradicted at the time written | `process-capability` / `premature-completion` | The merge commit, or "merge requested" |
| A design note cites "Smith 2021, p. 4" for a claim; no such paper is found | Design rationale; asserting | Library search | Unknown, leaning contradicted | `provenance` / `invented-source` | A link to the paper, or the citation removed |
| A summary of a meeting note says the team "decided" what the note lists as an option | Summary; asserting | The note | Contradicted (by the source) | `factual-source` / `source-drift` | The note's wording restored |
| "Two reviewers confirmed this": both were models given the same prompt and the same unverified premise | Review report; asserting | The two reviews | Supported that both agreed; unknown that it is true | `evidence-authority` / `echo-confirmation` | Evidence neither model produced, or "two reviews agreed" |
| "The owner approved this approach": the only approval is a month old and for a different scope | Implementation report; asserting | Decision records | Contradicted for this scope | `evidence-authority` / `assumed-authority` | A current approval record covering the scope |
| A story's second chapter has a character who died in chapter one speak without explanation | Fiction; imagining | The supplied outline | Contradicted (by the world) | `explanation-constraint` / `constraint-break` | The outline honoured, or the change made explicit |
| A brainstorm proposes an idea and backs it with "this was measured at 40 % faster" with no measurement | Brainstorm; hypothesizing, then asserting a measurement | None | Unknown | `simulated-precision`, `provenance` | The measurement, or the number removed |

**Must not be flagged (controls)**

| Case | Why it is not a finding |
|---|---|
| A short story invents a town, its history and its residents | Imagining, no factual claim, consistent with its own world: an appropriate addition |
| "One possible cause is cache invalidation; I have not checked" | Hypothesizing, marked as such, with its evidence state stated |
| A report says "I could not find a test run for this change" | An honest unknown; the report claims nothing it lacks |
| A design note uses "the records remember why" and adds "(figuratively: the decision log stores the rationale)" | The metaphor is marked and the literal mechanism is given |
| A summary adds a widely known date that is not in its source, for a reader who asked for background | The task allowed background; the addition is true; faithfulness was not promised |
| An estimate is given as "roughly a day, based on the last two similar changes" | A number with its basis stated; not simulated precision |

### Proposal: evidence at review gates (not adopted)

The useful moments to ask for evidence are transitions, where a claim changes what others will do:

- a possibility becomes a requirement;
- a requirement becomes an implementation;
- a review becomes an approval;
- a planned action becomes a reported result;
- a past record becomes current authority.

At such a transition, a reviewer asks for **receipts**, at the rung the claim states:

| Rung | Receipt |
|---|---|
| planned | The plan or handoff that states it |
| attempted | The command, call or request, with its time |
| completed | The resulting state: a commit, a run log, an output file, a record line |
| independently verified | A check by someone or something that did not produce the result and did not inherit its premise |

The reviewer compares the rung claimed with the rung shown. A gap is tagged (usually `premature-completion`,
`status-inflation` or `reflexive-fabrication`) with the receipt that would close it. A missing receipt is *unknown*
unless the record that would hold it is known to be complete.

This must work with **one assistant**. The same assistant attaches receipts to its own report, and the owner (or the
assistant itself, at the next transition) checks the rung. A second reviewer is optional. Its agreement counts as a
review, not as independent verification, unless it rests on evidence the first did not produce; models that share a
training lineage or a prompt can share an error.

This proposal keeps today's scope: tags are still applied only on PRs that change a contract, a check's semantics or
an authority, and nothing is scored or blocked automatically. Applying receipts at other transitions, or on more PRs,
would be a wider scope and is listed for a decision rather than assumed here.

### Sources

Public work behind the distinctions above. None of it gives a hallucination rate for any project using Telosmith.

- Maynez et al. 2020, faithfulness and factuality in abstractive summarization: https://aclanthology.org/2020.acl-main.173/
- Min et al. 2023, FActScore, claim-level support: https://aclanthology.org/2023.emnlp-main.741/
- Gao et al. 2023, ALCE, citation support and relevance: https://aclanthology.org/2023.emnlp-main.398/
- Song et al. 2024, VeriScore, which separates verifiable claims from stories, hypotheticals and suggestions: https://aclanthology.org/2024.findings-emnlp.552/
- ToolBeHonest (2024), non-existent and insufficient tools: https://arxiv.org/abs/2406.20015
- Vu et al. 2024, FreshLLMs, fast-changing and false-premise questions: https://aclanthology.org/2024.findings-acl.813
- Kim et al. 2025, correlated errors across language models: https://proceedings.mlr.press/v267/kim25e.html
- Zhou et al. 2024, language models' reluctance to express uncertainty: https://aclanthology.org/2024.acl-long.198
- Turpin et al. 2023, explanations that omit what drove the answer: https://arxiv.org/abs/2305.04388
- Li et al. 2026, ConStory-Bench, consistency in long stories: https://aclanthology.org/2026.findings-acl.410/
