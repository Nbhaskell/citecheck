# Metrics and calibration

How each score is computed, and the evidence that the judge behind it can be trusted. This page was part of the README.

## Retrieval metrics

Defined in [`src/citecheck/metrics/retrieval.py`](../src/citecheck/metrics/retrieval.py). A chunk *matches* a fact when it
contains the fact's anchor phrase and comes from a document that states the fact (`--any-document` drops the second
condition). Matching on text, not chunk ids, is what lets one golden set score targets that chunk differently.

| Metric | Meaning |
|---|---|
| found | every fact the question depends on is among the chunks the target returned |
| recall@k | share of the question's facts within the first k chunks |
| MRR | mean of 1 / (rank of the first matching chunk), 0 when none |
| worst rank | rank of the lowest-placed fact, when all are found |
| precision@k | share of the first k chunks that match some fact (a chunk can help without containing the anchor, so this understates) |

Only questions with evidence and no error are scored; unanswerable questions and follow-ups have nothing to retrieve, and
errors are counted separately and shown.

## Check: does it agree with rag-project's own numbers?

Before trusting a new metric implementation, it was run against the system whose results are already published. One pass
of all 131 questions against rag-project on its demo corpus (50 chunks, `RAG_TOP_K=4`, split search on), compared with
that project's saved runs ([`runs/published/`](../runs/published/)):

| Set | "Found" published | CiteCheck | Fact in top chunk, published | CiteCheck |
|---|---|---|---|---|
| tuned (59 scored) | 59/59 | 59/59 | 44/59 | 44/59 |
| held-out (46 scored) | 45/46 | 45/46 | 38/46 | 37/46 |
| PDF set (8 scored) | 8/8 | 8/8 | 5/8 | 5/8 |

Per question, 111 of 113 are identical in both found and rank
([`compare-with-rag-project-published.txt`](../runs/published/compare-with-rag-project-published.txt)). The two that differ
are off by one rank position, and in both the neighbouring chunks are near-ties in the target's own distance
(`boarding-3-nights`: 0.391 and 0.391; `deposit-and-checkin`: 0.457 and 0.459). The published runs agree with each other on
these questions, so it is not run-to-run noise; likely causes are a different machine (this pass ran on CPU) or a different
commit, but that was not isolated. The metric itself follows the target's ordering, so a flipped near-tie moves a rank.

How to read this: it shows the retrieval metrics compute what rag-project's `run_eval.py` computes, on the same questions.
It says nothing about whether retrieval is *good*, and it is one pass. One question (`dispute-charge`) hit the target's
180-second model timeout on CPU and was asked again on its own (`--ids`); its second answer is the one counted. One
deliberate difference from the source files: `full-day-price` uses a tighter anchor, which did not change any result.
The pass was made from an uncommitted working tree, so its run files record the previous commit with `"dirty": true`; a
run made from a committed tree records the exact code.

## Answer metrics (judged by a local model)

```
python -m citecheck score runs/<run id>.run.json --judge      # needs Ollama with qwen3:8b pulled
```

A judge model (`qwen3:8b` through Ollama, temperature 0, fixed seed, reasoning on) reads each answer and gives three
verdicts, each from its own call and prompt ([`src/citecheck/judge/prompts.py`](../src/citecheck/judge/prompts.py)):

| Verdict | Asked of | Labels |
|---|---|---|
| abstention | every answer | `abstained` (says it does not know, or that the documents do not cover it), `answered`, `partly_answered` |
| faithfulness | every answer that did not abstain, against the passages the target retrieved | `supported`, `partly_supported`, `unsupported`, plus the list of unsupported claims |
| correctness | every answerable question, against its reference answer; a refusal counts as incorrect | `correct`, `partly_correct`, `incorrect` |

Faithfulness and correctness are reported as a mean with supported/correct = 1, partly = 0.5, otherwise 0. Abstention is
reported as how many unanswerable questions were declined (right) and how many answerable ones were (a false refusal).
Follow-ups are judged with their earlier conversation. A failed call is counted as an error and left out of the averages.

Judge replies are cached on disk (`.cache/judge/`) under a hash of the model and its digest, the verdict's prompt version, the full
prompt and the sampling options, so re-scoring is free and a changed model or prompt never reuses an old verdict. Each
scores file records the judge's model, digest, prompt version and settings.

**Result on the 131-question baseline** against rag-project (`rag-demo-1.1.0`, `RAG_TOP_K=4`), judge as above:
faithfulness 0.94 (104 of 119 supported, 15 partly, none unsupported), correctness 0.98 (118 of 121 correct, 2 partly, 1
incorrect), all 10 unanswerable questions declined, and 2 answerable ones declined (`meal-packing` and
`sunday-false-premise`). Saved in [`runs/published/`](../runs/published/). Read these with the next section in mind: the judge
leans strict on faithfulness, so a faithfulness score of 0.94 is closer to a floor than a ceiling.

## Is the judge right? Calibration

A judge is a model, so two checks measure it instead of assuming it works.

```
python -m citecheck sheet runs/<run id>.run.json --scores <scores A> --scores <scores B> --out labels/sheet.html
python -m citecheck calibrate labels/rag_demo_v1.labels.json --scores <scores A> --scores <scores B>
python -m citecheck known-bad runs/<run id>.run.json --labels labels/rag_demo_v1.labels.json
```

**1. Agreement with hand labels.** 36 answers were labelled by hand without seeing any verdict, using the same three
questions and labels. 23 were chosen because two judge settings (reasoning on and off) disagreed about them and 13 because
they agreed (including unanswerable questions), then shuffled. Sampling and the labelling sheet:
[`src/citecheck/calibration.py`](../src/citecheck/calibration.py); labels:
[`labels/rag_demo_v1.labels.json`](../labels/rag_demo_v1.labels.json).

| Label compared | n | Reasoning off | Reasoning on |
|---|---|---|---|
| abstention | 36 | 35 (97%) | 35 (97%) |
| faithfulness | 30 | 9 (30%) | 24 (80%) |
| correctness | 30 | 22 (73%) | 28 (93%) |

Re-weighting the two groups to their size in the full run estimates 0.54 and 0.87 for faithfulness and 0.83 and 0.96 for
correctness, a rough figure from a small sample. With reasoning off the judge called most good answers partly or fully
unsupported even when a passage states the claim word for word, so reasoning is on by default. Cohen's kappa is printed by
`citecheck calibrate` but comes out as 0 for faithfulness and correctness here: every answered item was labelled supported
and correct, and kappa cannot reward agreement when one side uses a single label.

**2. A known-bad check.** The hand labels contain no bad answers, so they cannot show whether the judge notices one.
`citecheck known-bad` takes the 30 answers labelled supported and correct, damages each in a known way, and counts how often
the judge flags it (any verdict other than the best one). The unchanged answers are judged too, as a control.

| Damage | n | Reasoning off | Reasoning on |
|---|---|---|---|
| none (control): good answers flagged for faithfulness / correctness | 30 | 21 / 8 | 6 / 2 |
| first price or number changed (usually the day of an "As of" date): flagged for faithfulness / correctness | 26 | 26 / 23 | 24 / 23 |
| a sentence the documents never state added: flagged for faithfulness | 30 | 30 | 30 |
| answer replaced by another question's answer: flagged for correctness | 30 | 29 | 29 |
| answer replaced by a bare refusal: flagged as declined / as incorrect | 30 | 30 / 30 | 30 / 30 |
| leading Yes/No flipped: flagged for correctness | 9 | 4 | 3 |

Two reasoning-on calls timed out in the first pass and were asked again with the longer default wait, so every case is
counted. With reasoning off the
judge flags nearly everything, good or bad, so its faithfulness verdicts carry little information. With reasoning on it
flags 88% or more of the damaged answers in four of the five kinds of damage, and 20% of the good ones for faithfulness
(7% for correctness). The flagged good answers are borderline inferences, such as a dog's owner being called responsible for
bringing items the passage only calls allowed.

Known weaknesses, all measured on a small sample:

- **A contradicted opening is missed.** When the first word is flipped but the rest of the sentence still states the right
  facts ("No, there is an extra charge for boarding on holidays..."), the judge reads the whole answer and often calls it
  correct (3 of 9 caught). A real answer that contradicts itself would be missed in the same way.
- **An off-topic answer is usually read as a refusal.** 26 of 30 answers replaced by another question's answer were
  labelled `abstained`, which skips the faithfulness check for them; correctness still catches them.
- **Added claims are mostly rated `partly_supported`**, not `unsupported`, which is the intended reading of a minor
  unsupported claim.
- **The judge is the same model the target answers with.** The checks above measure agreement with a person and with
  known damage; they do not rule out that it favours its own style.
- **One labeller, one pass, 36 answers, prompt version 1 untouched.** The prompts were not tuned against these labels, so
  the numbers are a fair read of version 1, and a changed prompt needs the calibration repeated.

## Figure and date check (no model)

The judge often lets a small change to a figure or a date pass (see the known weaknesses above), so a second check reads an
answer for its figures alone. [`src/citecheck/metrics/figures.py`](../src/citecheck/metrics/figures.py) finds every money amount,
number, date and time of day in an answer and asks whether the same value appears in the sources, the question or the earlier
turns. It needs no model and no judge, runs with every `score`, and is reported beside the judged scores.

```
python -m citecheck score runs/<run id>.run.json
python -m citecheck figure-check runs/<run id>.run.json --labels labels/<labels>.json --judge-results <known-bad file> [--judge]
```

- **What is compared.** Amounts and numbers by value (`$100` matches `100.00`, `44.0 billion` matches `44,000 million`); a date
  as a whole year, month and day however it is written; a time on a 12-hour clock, so am and pm are not told apart. Citation
  markers, list numbering, form names such as 10-K and codes such as H100 are not figures. A number word in a source or question
  (`three`) counts as its value; a number word in an answer is not checked.
- **Two counts.** *Not found* is a figure that appears in none of those texts. *Underived* is a number that is also not the sum,
  difference, product or quotient of two numbers that do appear (0 and 1 are not used as operands, since they would put every
  number one step from another). Dates and times are never derived.
- **Sources.** The passages the target returned, or for a target that reports only what an answer cited, the cited excerpts. An
  answer that cites nothing has every figure not found. Declined answers are not checked.

**On the answers already judged good** (no damage; scored without the judge, so a declined answer is one the target declined):

| Run | Answers with a figure | Every figure found | Figures not found | Every figure derivable | Figures underived |
|---|---|---|---|---|---|
| rag-project baseline, 1 pass | 95 | 89 | 8 | 95 | 0 |
| rag-project `RAG_TOP_K=4`, 5 passes | 467 | 441 | 37 | 467 | 0 |
| CiteWise baseline | 23 | 23 | 0 | 23 | 0 |

Every unfound figure in the five passes is a total, product or saving computed from the passages (`$100 + $50`, `$125 x 3`) or a
count taken from two times (`late-7pm`). The strict count therefore flags correct arithmetic in about 6% of the answers that state a figure (6 of 95, 26 of 467); the lenient
count flags none. Scores: `runs/published/*.figures.scores.json`.

**Does it notice damage?** The same damage the judge was tested with (30 sentences and 30 answers labelled good by hand), plus
`figure_swapped`: the first figure replaced by the nearest different figure that the sources do state. Judge results are from
the published known-bad files (reasoning on, prompt version 1); the swapped cases were judged with the same settings.

| Damage | Texts | Not found | Underived | Judge | Either (judge or underived) |
|---|---|---|---|---|---|
| **Cited sentences** | | | | | |
| none (control): flagged | 30 | 0 | 0 | 3 | 3 |
| a figure changed by 17 to 59 | 18 | 18 | 16 | 12 | 18 |
| the day of a date changed | 10 | 10 | 10 | 2 | 10 |
| a figure swapped for another in the sources | 15 | 0 | 0 | 15 | 15 |
| **Whole answers** | | | | | |
| none (control): flagged | 30 | 1 | 0 | 8 | 8 |
| first price or number changed | 26 | 25 | 22 | 25 | 25 |
| a figure swapped for another in the sources | 25 | 1 | 0 | 24 | 24 |

How to read it:

- **It covers the judge's gap on invented figures and dates.** For cited sentences, a figure or date that appears in no source is
  found every time, where the judge missed 6 of 18 changed figures and 8 of 10 changed days; together they catch all 28.
  Two of the 18 changed figures happened to equal a sum or product of source numbers, which is what the lenient count costs.
- **It adds little for whole answers**, where the judge already flagged 25 of 26 changed numbers.
- **It cannot see a wrong figure that the sources also state**, by design (0 of 15 and 1 of 25 swapped). The judge flagged 15 of
  15 and 24 of 25, so the two checks are complementary: the judge notices a figure that is plainly the wrong one, and the check
  notices a small invented change the judge reads past.
- **False alarms are low where it matters**: none of the 30 good sentences, one strict and none lenient of the 30 good answers.

Limits:

- **The damage tests for invented figures are close to circular.** The damage is defined as a figure that is in no source, which
  is what the check detects; the informative rows are the false alarms and the cost of the lenient count.
- **The swap is not subtle.** The nearest different figure in a long passage is often far from the original, which is easy for a
  judge to notice. A near miss such as the previous year's headcount was not tested, and the check cannot see it either.
- **Small samples**: 30 texts per set, 10 date cases, one set of hand labels per target.
- **The rules were shaped by reading false alarms on these same runs** (marker and list stripping, whole dates, number words,
  the arithmetic count). The false-alarm rates are therefore measured on data the rules were developed against, and a new target
  or corpus needs them checked again.
- **Figures only.** A number word in an answer, a date without a year, and any claim that is not a figure are not checked.
  A figure the target used but did not cite is flagged for a target scored against cited excerpts.

## Citation metrics

A target cites in one of two ways. Inline: the answer text carries markers such as `[2]` or `[3][6]`, each naming a listed
source with its excerpt (CiteWise). File level: the answer carries no markers and the target only lists the documents it
used (rag-project). The checks in [`src/citecheck/metrics/citations.py`](../src/citecheck/metrics/citations.py) apply to the
answers that should carry citations, meaning answerable questions the target did not decline, and need no judge unless
noted.

| Check | Meaning |
|---|---|
| dangling marker | a marker in the answer that matches no listed source (inline targets) |
| unused source | a listed source whose marker the answer never uses (inline targets) |
| cited sentence share | the share of an answer's sentences that carry a marker (inline targets) |
| evidence cited | a fact the question depends on counts as cited when a listed source comes from a document that states it and, when the target gives the excerpt, the excerpt contains the fact's anchor phrase; a fact may list passages that word it differently, each with its own anchor |
| source precision | the share of distinct cited documents that are expected (the evidence documents plus any `expected_sources` and `acceptable_sources`) |
| claim support | the judge's verdict on whether the sources cited for one sentence support that sentence (`--judge`), counted per sentence |
| declined, with markers | declined answers that still carry citations |

**rag-project** (file level, 119 answers): the document that states every fact was listed for 110 of 111 answers with
evidence, and 92% of the documents it listed were expected. It has no markers, so the marker and claim checks do not apply.
Only 1 of its 12 declined answers lists a source.

**CiteWise** (inline, 38 answerable questions): every answer carries markers, none dangles, and 92.5% of sentences are
cited. The passage that states every fact is among the cited sources for 36 of 38 answers, and every cited document is an
expected one. The judge calls 40 of 44 cited sentences supported, 3 partly and 1 unsupported (mean 0.94), and 5 of the 6
declined answers still carry markers, such as "the sources do not mention parking [1][2][3]". "Unused source" cannot occur
here, because CiteWise's API returns only the sources an answer cited. The two answers without the key passage are
`nvda-hq-and-employees`, where CiteWise says the filings do not give NVIDIA's headcount although they do, and `amd-nvda-hq`,
where the AMD source cited is a different passage of the right filing that may also name Santa Clara. The evidence check is
strict, so an answer that cites another passage stating the same fact is counted as missing it unless that wording was added
to the golden set as an alternate (as was done for NVIDIA's headquarters).

## CiteWise as a second target

[Citewise for Markets](https://github.com/Nbhaskell/citewise-markets) answers from SEC filings, prices, figures and headlines
with inline numbered citations. Start its API (`python -m api` in that project; it uses port 8000 like rag-project, so run
one at a time), then:

```
python -m citecheck run --golden golden/citewise_filings_v1.json --target citewise --label baseline-citewise
python -m citecheck score runs/<run id>.run.json --judge
```

What differs from rag-project, all handled by [`src/citecheck/adapters/citewise.py`](../src/citecheck/adapters/citewise.py):

- The API returns only the passages an answer cited, not everything the model was shown, so retrieval cannot be scored for it
  (the run records `reports_retrieved: false`). Faithfulness is then judged against the cited sources, which checks an answer
  against what it points to and is weaker than checking it against everything the model read.
- Prices, headlines and the P/E change every night, so its golden set rests on filing text only.
- A source's title (for example `NVDA 10-K filed 2026-02-25`) is its document id.

**Result on the 44-question baseline**, judge as above: faithfulness 0.91 against cited sources (34 of 38 supported), correctness
0.95, all 6 unanswerable questions declined and no answerable one. Saved in [`runs/published/`](../runs/published/).

## Calibration of citation support

The citation verdict is a new use of the judge, so it was calibrated on its own, in the same two ways. The numbers in this
section are for citation prompt version 1; version 2 and its results are in [Citation prompt version 2](#citation-prompt-version-2).

**1. Agreement with hand labels.** 30 cited sentences were labelled by hand: 5 that either judge setting flagged, and 25
that both called supported, shown without any verdict. Each card shows the question, the whole answer, the one statement and
only the sources cited for it. The labels are in
[`labels/citewise_filings_v1.citation-labels.json`](../labels/citewise_filings_v1.citation-labels.json).
All 30 were labelled supported, and the judge matched 26 (87%) with reasoning on and 26 with it off. Every disagreement is
the judge being too strict, mostly on a sentence that gives only half of a two-part question (the combined headcount of two
companies, answered in two sentences): it judged the sentence on whether it answered the question, which the prompt tells it
not to do. Kappa comes out as 0 because every label is the same, which is undefined agreement, not no agreement.

**2. A known-bad check.** Because every label is "supported", the labels cannot show whether the judge notices a bad citation.
`citecheck known-bad` damages the 30 sentences in four ways and counts how often the judge flags them (any verdict but
supported), with the unchanged sentences as a control.

| Damage | n | Reasoning off | Reasoning on |
|---|---|---|---|
| none (control): good sentences flagged | 30 | 1 | 3 |
| a figure changed by 17 to 59 (not part of a date) | 18 | 8 | 12 |
| the day of a date changed to another valid day | 10 | 2 | 2 |
| shown the sources cited for a different sentence | 30 | 28 | 28 |
| a clause the sources never state added | 30 | 27 | 23 |

- Swapped sources are caught almost every time, so a citation that points at the wrong place is noticed.
- Small changes to a figure are caught about half to two thirds of the time, and a changed date day is mostly missed: the
  judge treats it as a minor detail of a statement whose main point is backed. The [figure and date check](#figure-and-date-check-no-model)
  covers the case where the new figure or date appears in no source.
- An added claim is flagged but usually as `partly_supported` (3 and 4 of 30 as `unsupported`), the intended reading of a minor
  unsupported claim.
- Unlike faithfulness on whole answers, neither setting is clearly better here: reasoning off has fewer false alarms and
  catches more added claims, and reasoning on catches more changed figures. The default stays on.

Known limits: the judge and the labeller saw each excerpt without the title of the filing it came from, so a statement that
names a company cannot be checked against the excerpt's own text; the labels contain no bad citation; and a first version of
the check changed the first number in each sentence, which was usually the day of an "As of" date. Its results
(`citation-known-bad-first-number-*` in [`runs/published/`](../runs/published/)) were kept, and the check was split into figures and
dates. The step 2 "first price or number changed" row for whole answers has the same property.

## Citation prompt version 2

**What was wrong.** On the 30 hand-labelled cited sentences the judge flagged 4 that were labelled supported, all in two answers
(the combined headcount of two companies, and which of two companies has more employees). Its reasons said the sources were
fine and then marked the sentence down because it did not cover the whole question. A probe isolated the cause: the same 30
sentences with the same sources, with the question extended by a demand no single sentence could meet ("Also say how this
compares with the same figure for another company."), were flagged 17 of 30 times with reasoning on and 12 of 30 with it off. The
labels cannot change when only the question does, so the question was pulling the verdict.

**What changed.** Citation prompt version 2 differs from version 1 in three ways:

- the question is not shown to the citation judge, only the statement, its cited sources and any earlier conversation;
- the sentence before the statement is shown as context only, marked as not evidence, so that "Of this, 1.4 million is owned"
  or "This is stated in source [2]." can be read;
- the wording says to check what the statement itself says, not to lower the verdict for what it leaves out, and gives an
  invented example (the ovens of a bakery, not from the corpus). A number or date the sources do not state makes a statement
  partly supported.

The prompt version is now kept per verdict, so only the citation verdict changed: the answer verdicts keep version 1, their
cached replies and their calibration evidence, and a report matches evidence to a judge by the versions of the verdicts the
evidence is about. The version 1 files are kept unchanged beside the new ones.

**How it was chosen, and what that does to the evidence.** Four prompts were tried on the 30 labelled sentences, with reasoning
on and off: the current one, new wording alone, the question left out alone, and both. A fifth added the previous sentence.
Leaving the question out removed the probe's effect by construction; new wording alone cut it but did not remove it (8 and 5 of
30 flagged; a judge call timed out in the first, so it may be 9). The choice between the last two was fixed before their known-bad results were seen: adopt the one with context
unless it was worse than the other by more than 2 on the control or on any damage kind. **The prompt was designed while looking
at those 30 labelled sentences and their disagreements, so agreement and the known-bad check on that sample show that the
problem is fixed there, not that the prompt works elsewhere.** The held-out sample below is the independent check.

**Known-bad check, same 30 sentences** (flagged / total; the unchanged control is a false-alarm count):

| Damage | Old, reasoning on | New, reasoning on | Old, reasoning off | New, reasoning off |
|---|---|---|---|---|
| none (control): good sentences flagged | 3 / 30 | 1 / 30 | 1 / 30 | 1 / 30 |
| a figure changed | 12 / 18 | 12 / 18 | 8 / 18 | 17 / 18 |
| the day of a date changed | 2 / 10 | 5 / 10 | 2 / 10 | 9 / 10 |
| shown the sources of a different sentence | 28 / 30 | 28 / 30 | 28 / 30 | 28 / 30 |
| a clause the sources never state added | 23 / 30 | 30 / 30 | 27 / 30 | 30 / 30 |

Detection did not fall anywhere, and false alarms did not rise. Most flags are `partly_supported`: the changed dates are
flagged as `unsupported` in 0 of 10 cases in either setting, and the changed figures in 7 of 18. A changed date or figure is
therefore noticed, but counts as a partial failure, not a failed citation.

**Held-out agreement.** 30 new questions (`golden/citewise_citation_holdout_v1.json`, category `probe`; most ask for two facts,
a total or a difference) were asked of CiteWise, giving 46 cited sentences, 44 of them not seen before. Forty were judged by
all four settings (old and new prompt, reasoning on and off). The 30 shown for labelling were the 12 that any setting flagged or
the settings disagreed on, and 18 chosen at random from the rest, so neither prompt was favoured by the choice. They were
labelled without any verdict in view
([`labels/citewise_citation_holdout_v1.citation-labels.json`](../labels/citewise_citation_holdout_v1.citation-labels.json)): 27
supported, 1 partly supported, 2 unsupported.

| Judge setting | Matched | Agreement | Weighted to the full run | Kappa |
|---|---|---|---|---|
| Old prompt, reasoning on | 22 / 30 | 0.733 | 0.800 | 0.310 |
| Old prompt, reasoning off | 26 / 30 | 0.867 | 0.900 | 0.447 |
| New prompt, reasoning on | 29 / 30 | 0.967 | 0.975 | 0.786 |
| New prompt, reasoning off | 29 / 30 | 0.967 | 0.975 | 0.818 |

Seven of the old prompt's 8 errors with reasoning on, and 3 of its 4 with reasoning off, were sentences labelled supported
that it marked down. The new prompt's single miss in both settings is a sentence with two claims, one of them (Amazon's
headquarters) absent from its cited source: labelled partly supported, called supported with reasoning on and unsupported with
reasoning off. Two cards carried a note (a sentence whose lead-in is "the source information indicates", and one where the figure
was right but the comparison was not in the source); without them the counts are 27 / 28 for the new prompt in both settings and
22 / 28 and 24 / 28 for the old one.

**Effect on CiteWise's published scores.** Citation support moves from 0.943 to 0.977 with reasoning on (43 of 44 sentences
supported) and from 0.921 to 1.000 with reasoning off. The answer scores (faithfulness, correctness, abstention) are
unchanged, because their prompts and cached replies are. The baseline report is rebuilt from the new scores and now cites the
held-out agreement and the version 2 known-bad runs; the version 1 files stay in [`runs/published/`](../runs/published/).

**Limits.**

- Only 3 of the 30 held-out labels are not supported, so the sample shows little about strictness. With reasoning on the new
  prompt matched 2 of those 3 and with reasoning off 2 of 3. How well it catches bad citations rests mainly on the known-bad
  check, whose sentences were used to design it.
- The sample was chosen using the judge verdicts, so the plain agreement figures lean toward hard cases; the weighted column
  re-weights to the full run and is an estimate from a small sample.
- One labeller, one pass. The labels were made with written guidance on the definitions, including that a statement is not
  marked down for leaving out part of the question: the principle the new prompt states. Part of the agreement is therefore
  agreement on a shared definition.
- The 30 questions are of one kind (two companies, one or two facts), so the result says little about longer answers or other
  filings.

## Calibration of the answer verdicts on CiteWise

The answer verdicts (abstention, faithfulness, correctness) had been calibrated only on rag-project's answers, so the CiteWise
report called them unvalidated. They were calibrated on CiteWise's own 44 answers in two steps, and **only the second step is a
person's reading**.

1. **A model labelled all 44 answers, blind.** A fresh Claude Opus session was given only the cards (the question, the answer,
   the reference answer where there is one, the cited excerpts) and the same definitions as the hand-labelling sheet. It was told
   to read nothing else and reported that it had not. Its labels are in
   [`labels/citewise_filings_v1.answer-labels.model.json`](../labels/citewise_filings_v1.answer-labels.model.json): 6 abstained, 1
   partly answered, 38 supported, no partly supported or unsupported, 34 correct and 4 partly correct.
2. **A person labelled 23 of them.** The 13 answers where the judge differed from the model labeller on any question under either
   reasoning setting, and 10 chosen at random from the other 31, shuffled, with no verdict from the judge or the model shown
   ([`labels/citewise_filings_v1.answer-labels.json`](../labels/citewise_filings_v1.answer-labels.json)): 20 answered, 3 abstained;
   19 supported and 1 partly supported; 19 correct and 1 partly correct.

CiteWise reports no retrieved passages, so the passages a labeller sees, like the ones the judge sees, are the excerpts the answer
cited. The labelling sheet used to show only retrieved passages, which would have left a CiteWise card with nothing to check
against; it now shows the cited excerpts, with a rule saying so.

**Judge against the hand labels** (23 answers; weighted re-weights the two groups to their size in the full run, an estimate from
a small sample):

| Question | Reasoning on: matched | weighted | Reasoning off: matched | weighted |
|---|---|---|---|---|
| Abstention | 21 / 23 | 0.955 | 22 / 23 | 0.977 |
| Faithfulness | 15 / 20 | 0.856 | 11 / 20 | 0.741 |
| Correctness | 18 / 20 | 0.942 | 17 / 20 | 0.914 |

**Judge against the model's labels** (all 44): reasoning on matched 43 / 44 abstention, 34 / 38 faithfulness and 34 / 38
correctness; reasoning off matched 44 / 44, 28 / 38 and 34 / 38.

**The model's labels against the hand labels:** 22 / 23 abstention, 19 / 20 faithfulness and 17 / 20 correctness, and all of the
10 random cards (24 of 24 labels). The three correctness differences are the same kind: the model marked partly correct an
answer that gives the right figures but never states the final total, difference or percentage the question asks for, where the
hand label was correct. As a stand-in for a person the model's labels are close on abstention and faithfulness and stricter on
correctness for an answer that stops short of the calculation.

**Known-bad check.** The 19 answers the hand labels call both supported and correct were damaged in five ways and judged again
(flagged / total; the unchanged control counts false alarms):

| Damage | Question | Reasoning on | Reasoning off |
|---|---|---|---|
| none (control): good answers flagged | faithfulness | 4 / 19 | 9 / 19 |
| | correctness | 2 / 19 | 3 / 19 |
| the first number changed | faithfulness | 11 / 19 | 16 / 19 |
| | correctness | 9 / 19 | 8 / 19 |
| a leading yes or no flipped (2 answers) | faithfulness | 1 / 2 | 2 / 2 |
| | correctness | 2 / 2 | 2 / 2 |
| a sentence the sources never state added | faithfulness | 19 / 19 | 19 / 19 |
| replaced by another question's answer | correctness | 17 / 18 | 18 / 19 |
| replaced by a refusal | abstention | 19 / 19 | 19 / 19 |
| | correctness | 19 / 19 | 19 / 19 |

(One case with reasoning on had a judge failure and is left out.) "The first number" is often the day of an "As of" date, as for
whole answers on rag-project, so the row mixes changed figures and changed dates.

**What this shows**

- **Faithfulness is the weakest verdict, and it is too strict.** Against the hand labels, 4 of the 5 misses with reasoning on and
  all 9 with it off are the judge calling a claim unsupported or partly supported that the hand label found backed, and it flags
  4 of 19 (reasoning on) and 9 of 19 (reasoning off) of the unchanged answers that the hand labels call supported. The CiteWise faithfulness score of
  0.908 probably understates the target. In four of the five misses with reasoning on, the claim names a company ("NVIDIA is
  headquartered in Santa Clara, California") while the cited excerpt states the fact in the filer's own voice without naming the
  company, and the judge sees the excerpt text without the title of the filing it came from. The labeller's sheet shows that title in each source's heading, so
  the two did not read the same thing. This is a likely cause, not a tested one.
- **Correctness misses are all on the strict side** (2 with reasoning on, 3 with it off: partly correct or incorrect where the hand
  label was correct), and damage that changes the answer's substance (a wrong answer, a refusal, a flipped yes or no) is
  flagged almost every time.
- **Abstention is reliable** on this run: 21 and 22 of 23 matched, and every declined answer made up for the check was flagged.

**Limits.**

- 23 hand labels from one labeller. They contain one partly supported and one partly correct label and no unsupported or incorrect
  one, so they cannot show whether the judge catches a bad answer; the known-bad check covers that, on 19 answers.
- Which cards were hand-labelled was chosen using the judge's verdicts and the model's labels. The weighted columns assume the 31
  unlabelled agreeing answers behave like the 10 random ones, on which the model's labels and the hand labels agreed completely.
- The model's labels are not a person's reading, shared blind spots are possible, and agreement with them says how close the judge
  is to a stronger model, not to a careful reader. The report cites only the hand labels.
- The answer prompts are unchanged (version 1) and were not tuned on these labels.
