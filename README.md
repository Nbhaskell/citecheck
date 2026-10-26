# CiteCheck

An evaluation harness for RAG systems. It runs a golden question set against a target system and scores three things:
whether retrieval found the right passage, whether the answer is faithful to what was retrieved, and whether the
citations are valid. Output is a CLI and a readable report.

The metrics are written by hand in plain Python, with no eval framework. Each target system sits behind a small
adapter, so one harness can score different projects.

> **Status: all five steps done.** Retrieval, answer quality and citations are scored, against two targets (rag-project and
> CiteWise), with the local judge model checked against hand labels and known-bad answers, and each scored run has a report.
> Sections marked *planned* describe the intended design.

| Step | What | State |
|---|---|---|
| 0 | Golden set schema, converted question set, `validate` | done |
| 1 | Adapter interface, `run`/`score`, retrieval metrics, rag-project adapter | done |
| 2 | LLM judge (faithfulness, correctness, abstention; `qwen3:8b` through Ollama) and its calibration against hand labels | done |
| 3 | Citation checks, second target (CiteWise) | done |
| 4 | Markdown report per run (no HTML), tests-only CI | done |

## Quick start

Python 3.13+.

```
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.lock
pip install -e . --no-deps
python -m pytest
python -m citecheck validate golden/rag_demo_v1.json
```

## Running it

`run` asks the target every question and saves the raw responses; `score` computes metrics from that file without
contacting the target, so metrics can be changed and re-run for free.

```
# start the target first, e.g. rag-project's `python chat.py` on the corpus the golden set was written for
python -m citecheck run --golden golden/rag_demo_v1.json --target rag-project --label baseline --set RAG_TOP_K=4
python -m citecheck score runs/<run id>.run.json
```

Every answer is written to `runs/<run id>.partial.jsonl` as it arrives, so an interrupted run loses nothing:
`python -m citecheck run --resume runs/<run id>.partial.jsonl` asks only what is missing (add `--retry-errors` to ask
again the questions that timed out). A resumed run must use the same golden set and the same target settings.

`--set KEY=VALUE` records target settings the harness cannot read from the target (rag-project does not report its top-k).
`--repeat N` asks everything N times, since answers vary run to run. `--split tuned,heldout` and `--ids a,b` select
questions. `score` refuses to run against a golden set that differs from the one the run was asked from.

### Retrieval metrics

Defined in [`src/citecheck/metrics/retrieval.py`](src/citecheck/metrics/retrieval.py). A chunk *matches* a fact when it
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

### Check: does it agree with rag-project's own numbers?

Before trusting a new metric implementation, it was run against the system whose results are already published. One pass
of all 131 questions against rag-project on its demo corpus (50 chunks, `RAG_TOP_K=4`, split search on), compared with
that project's saved runs ([`runs/published/`](runs/published/)):

| Set | "Found" published | CiteCheck | Fact in top chunk, published | CiteCheck |
|---|---|---|---|---|
| tuned (59 scored) | 59/59 | 59/59 | 44/59 | 44/59 |
| held-out (46 scored) | 45/46 | 45/46 | 38/46 | 37/46 |
| PDF set (8 scored) | 8/8 | 8/8 | 5/8 | 5/8 |

Per question, 111 of 113 are identical in both found and rank
([`compare-with-rag-project-published.txt`](runs/published/compare-with-rag-project-published.txt)). The two that differ
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

### Answer metrics (judged by a local model)

```
python -m citecheck score runs/<run id>.run.json --judge      # needs Ollama with qwen3:8b pulled
```

A judge model (`qwen3:8b` through Ollama, temperature 0, fixed seed, reasoning on) reads each answer and gives three
verdicts, each from its own call and prompt ([`src/citecheck/judge/prompts.py`](src/citecheck/judge/prompts.py)):

| Verdict | Asked of | Labels |
|---|---|---|
| abstention | every answer | `abstained` (says it does not know, or that the documents do not cover it), `answered`, `partly_answered` |
| faithfulness | every answer that did not abstain, against the passages the target retrieved | `supported`, `partly_supported`, `unsupported`, plus the list of unsupported claims |
| correctness | every answerable question, against its reference answer; a refusal counts as incorrect | `correct`, `partly_correct`, `incorrect` |

Faithfulness and correctness are reported as a mean with supported/correct = 1, partly = 0.5, otherwise 0. Abstention is
reported as how many unanswerable questions were declined (right) and how many answerable ones were (a false refusal).
Follow-ups are judged with their earlier conversation. A failed call is counted as an error and left out of the averages.

Judge replies are cached on disk (`.cache/judge/`) under a hash of the model and its digest, the prompt version, the full
prompt and the sampling options, so re-scoring is free and a changed model or prompt never reuses an old verdict. Each
scores file records the judge's model, digest, prompt version and settings.

**Result on the 131-question baseline** against rag-project (`rag-demo-1.1.0`, `RAG_TOP_K=4`), judge as above:
faithfulness 0.94 (104 of 119 supported, 15 partly, none unsupported), correctness 0.98 (118 of 121 correct, 2 partly, 1
incorrect), all 10 unanswerable questions declined, and 2 answerable ones declined (`meal-packing` and
`sunday-false-premise`). Saved in [`runs/published/`](runs/published/). Read these with the next section in mind: the judge
leans strict on faithfulness, so a faithfulness score of 0.94 is closer to a floor than a ceiling.

### Is the judge right? Calibration

A judge is a model, so two checks measure it instead of assuming it works.

```
python -m citecheck sheet runs/<run id>.run.json --scores <scores A> --scores <scores B> --out labels/sheet.html
python -m citecheck calibrate labels/rag_demo_v1.labels.json --scores <scores A> --scores <scores B>
python -m citecheck known-bad runs/<run id>.run.json --labels labels/rag_demo_v1.labels.json
```

**1. Agreement with hand labels.** 36 answers were labelled by hand without seeing any verdict, using the same three
questions and labels. 23 were chosen because two judge settings (reasoning on and off) disagreed about them and 13 because
they agreed (including unanswerable questions), then shuffled. Sampling and the labelling sheet:
[`src/citecheck/calibration.py`](src/citecheck/calibration.py); labels:
[`labels/rag_demo_v1.labels.json`](labels/rag_demo_v1.labels.json).

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

### Citation metrics

A target cites in one of two ways. Inline: the answer text carries markers such as `[2]` or `[3][6]`, each naming a listed
source with its excerpt (CiteWise). File level: the answer carries no markers and the target only lists the documents it
used (rag-project). The checks in [`src/citecheck/metrics/citations.py`](src/citecheck/metrics/citations.py) apply to the
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

### CiteWise as a second target

[Citewise for Markets](https://github.com/Nbhaskell/citewise-markets) answers from SEC filings, prices, figures and headlines
with inline numbered citations. Start its API (`python -m api` in that project; it uses port 8000 like rag-project, so run
one at a time), then:

```
python -m citecheck run --golden golden/citewise_filings_v1.json --target citewise --label baseline-citewise
python -m citecheck score runs/<run id>.run.json --judge
```

What differs from rag-project, all handled by [`src/citecheck/adapters/citewise.py`](src/citecheck/adapters/citewise.py):

- The API returns only the passages an answer cited, not everything the model was shown, so retrieval cannot be scored for it
  (the run records `reports_retrieved: false`). Faithfulness is then judged against the cited sources, which checks an answer
  against what it points to and is weaker than checking it against everything the model read.
- Prices, headlines and the P/E change every night, so its golden set rests on filing text only.
- A source's title (for example `NVDA 10-K filed 2026-02-25`) is its document id.

**Result on the 44-question baseline**, judge as above: faithfulness 0.91 against cited sources (34 of 38 supported), correctness
0.95, all 6 unanswerable questions declined and no answerable one. Saved in [`runs/published/`](runs/published/).

### Calibration of citation support

The citation verdict is a new use of the judge, so it was calibrated on its own, in the same two ways.

**1. Agreement with hand labels.** 30 cited sentences were labelled by hand: 5 that either judge setting flagged, and 25
that both called supported, shown without any verdict. Each card shows the question, the whole answer, the one statement and
only the sources cited for it. The labels are in
[`labels/citewise_filings_v1.citation-labels.json`](labels/citewise_filings_v1.citation-labels.json).
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
  judge treats it as a minor detail of a statement whose main point is backed.
- An added claim is flagged but usually as `partly_supported` (3 and 4 of 30 as `unsupported`), the intended reading of a minor
  unsupported claim.
- Unlike faithfulness on whole answers, neither setting is clearly better here: reasoning off has fewer false alarms and
  catches more added claims, and reasoning on catches more changed figures. The default stays on.

Known limits: the judge and the labeller saw each excerpt without the title of the filing it came from, so a statement that
names a company cannot be checked against the excerpt's own text; the labels contain no bad citation; and a first version of
the check changed the first number in each sentence, which was usually the day of an "As of" date. Its results
(`citation-known-bad-first-number-*` in [`runs/published/`](runs/published/)) were kept, and the check was split into figures and
dates. The step 2 "first price or number changed" row for whole answers has the same property.

## Reports

```
python -m citecheck report runs/published/<run id>.run.json --scores runs/published/<judged scores>.json --agreement <agreement>.json --known-bad <known-bad>.json --out reports/<name>.md
python -m citecheck report-index reports
```

A report is one Markdown page per scored run, built by [`src/citecheck/report.py`](src/citecheck/report.py) from the run file, a
scores file and, when they exist, the calibration evidence for the judge that produced the scores. Nothing in it is computed by a
model: it arranges numbers already saved in those files, so the same inputs give the same page, and a JSON copy of the data is
saved beside it. Each page has:

- the run's provenance: target settings, question set and its hash, citecheck commit (and whether the tree was uncommitted),
  judge model, digest and settings;
- one table per area (retrieval, answers, citations) with every score beside the evidence and known weaknesses that bear on it:
  agreement with hand labels, the known-bad check, and the method's own limits;
- the same numbers by split and by category;
- a block, **What this cannot tell you**, drawn from the question set's own notes and the run: one pass only, the judge sharing
  the target's model family, a target that reports no retrieval, judged numbers with no calibration, and labels that were all the
  same category;
- **Items to look at**: every question with something unusual in its result, as a reading list and not a failure count, because
  a flag from the judge may be the judge's mistake.

Calibration evidence is used only when it was measured with the same judge configuration (model, reasoning on or off, prompt
version) and, when the file records it, on the same run; otherwise the page says it was not applied and why. There is no
side-by-side comparison of targets: their question sets, corpora and checks differ, and the index page says so.

Committed reports, from the published baselines: [`reports/rag-project-baseline.md`](reports/rag-project-baseline.md),
[`reports/citewise-baseline.md`](reports/citewise-baseline.md) and their [index](reports/index.md). An HTML version is not built.

### Continuous integration

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs the tests on every push to `main` and every pull request: Python 3.13 on
Linux, the pinned packages from `requirements-dev.lock`, and actions pinned to full commits. It runs the code's tests only, with no
Ollama, no target and no judge, so a green check says the code and the published report data hang together. It does not re-measure
any score.

## The golden set

A golden set is one JSON file per target and corpus, checked by [`golden/schema.json`](golden/schema.json) and by the
cross-item rules in [`src/citecheck/golden.py`](src/citecheck/golden.py). Its header names the corpus and records a
SHA-256 for every document, so a score can be tied to the exact text the questions were written against.

Each item has:

- a `question`, a `category` (`factual`, `yes_no`, `multi_topic`, `edge_case`, `follow_up`, `unanswerable`,
  `ambiguous`, `conflicting`) and an `expected_abstain` flag;
- `evidence`: the facts the answer depends on. Each has a short `anchor` phrase and the verbatim passage(s) that state it,
  with document, heading path and page. Retrieval is judged against these, by text rather than by chunk id, so it still
  works when a target changes how it chunks;
- a `split`: `tuned` (the system was adjusted while looking at these), `heldout` (written afterwards, not used to tune) or
  `unlabeled`. Scores are reported per split, because a tuned score flatters the system;
- optional keyword checks (`answer_contains`, `answer_not_contains`), source expectations, a `reference_answer`, notes,
  and `origin` (which file it was converted from).

### `golden/rag_demo_v1.json`

131 questions about a made-up dog daycare, converted from the question files of
[rag-project](https://github.com/Nbhaskell/rag-project) by [`tools/convert_ragproject.py`](tools/convert_ragproject.py)
(re-running it reproduces the file byte for byte).

| Split | Items | Scored for retrieval |
|---|---|---|
| tuned | 67 | 59 |
| heldout | 55 | 46 |
| unlabeled (PDF set) | 9 | 8 |

Known limits:

- **Reference answers were written for this harness.** The source files only had keyword checks, so `answer_contains` is
  carried over as it was. Since `rag-demo-1.1.0` every item has a `reference_answer`, drafted by Claude from the corpus
  documents, then checked by hand before merging; they live in
  [`golden/reference_answers_rag_demo_v1.json`](golden/reference_answers_rag_demo_v1.json) and the converter merges them
  in. For unanswerable items the reference says the documents do not cover the question. Some answers apply a rule or
  do arithmetic (late fees, package savings) rather than quote a line, and the 5-day vaccination grace period is read as
  "may attend within 5 days of expiry", which the documents do not spell out.
- **The published step 1 runs were asked from `rag-demo-1.0.0`** (the same questions without reference answers), so `score`
  refuses them against 1.1.0 and the hash check is doing its job. Their saved scores are unchanged; re-scoring them needs
  the 1.0.0 file from git history or `--ignore-golden-mismatch`.
- **No `ambiguous` or `conflicting` questions.** The categories exist; the source sets had none.
- **The held-out set was written by Claude** from the documents (as rag-project's README states), so it is unseen by the
  prompt but not blind to the corpus.
- **Left out on purpose:** the older samples set (a different corpus) and the prompt-injection set (it tests resistance to
  injected instructions, not retrieval or citations).
- One phrase was tightened (`full-day-price`: `$100.00` also matched the training-session price) and one fact has two
  valid locations (`address`: the hours document and the PDF). Both are recorded in the converter.

### `golden/citewise_filings_v1.json`

44 questions for CiteWise, built by [`tools/build_citewise_golden.py`](tools/build_citewise_golden.py) from
[`golden/citewise_questions_v1.json`](golden/citewise_questions_v1.json) and the filings that project has stored. Each fact in the
question file is an anchor phrase and a company; the builder searches the stored filings through the API, keeps every passage
that contains the phrase, and stops if one matches nothing. A fact worded differently in another passage lists that wording
as an alternate, and the passage carries its own anchor.

| Category | Items |
|---|---|
| factual | 23 |
| multi_topic | 5 |
| edge_case (arithmetic over two filings) | 3 |
| yes_no | 3 |
| unanswerable | 6 |
| follow_up | 4 |

All items are split `heldout`. Known limits:

- **Written by Claude from the stored text**, so unseen by the target but not blind to the corpus. The reference answers were
  drafted from the same text and have not been reviewed by a person.
- **Filing text only.** The 29 filings (10-K and 10-Q of seven companies) are identified by title and by a fingerprint of the
  accession number and URL, which identifies an immutable document but does not hash its text. A new filing adds documents, and a
  changed passage changes the golden set's hash, so saved runs then refuse to be scored against it.
- **Unanswerable means not stated in the filings as far as searched.** One is a near miss: the filings give an acreage for
  Microsoft's campus but not for NVIDIA's.
- **Mostly headcounts, headquarters, segments and buybacks.** Facts of this kind keep the evidence checkable, and say little about
  harder filing questions.

## Design

- **`run` and `score` are separate.** `run` calls the target and saves raw responses to `runs/`; `score` computes metrics from
  that file, so the judge can be re-tuned without re-querying the target.
- **Adapters talk to the target over HTTP**, so the harness does not import the target's code or share its Python version.
- **Reproducibility.** Pinned dependencies (`requirements*.lock`), a saved results file per run recording the golden-set
  version and a content hash, the target's settings, and the citecheck git commit; for judged scores also the judge model,
  its digest, the prompt version and the sampling settings, with a disk cache for judge calls. The targets do not expose a seed, and the harness itself has no
  randomness yet, so run-to-run variation is measured by repeating runs, not removed.
- **The judge is the same model the target answers with** (`qwen3:8b`). That is free and local, but a model grading its
  own kind of answer may be too kind. Its agreement with hand labels and with known-bad answers is measured and reported
  above, not assumed; those checks must be repeated whenever a prompt changes.

## Findings

What running the harness against two targets showed, including where the harness itself was wrong:

- **The judge needs reasoning on.** With it off, `qwen3:8b` called most good answers partly or fully unsupported, even when a
  passage states the claim word for word (21 of 30 labelled-good answers flagged, against 6 with it on). For judging whether a
  cited sentence matches its sources the two settings were about equal.
- **A second target found a harness bug.** CiteWise reports only the passages an answer cited, so faithfulness, checked against
  "retrieved passages", scored 0.00 for every answer. It is now checked against the cited sources for such a target.
- **A prompt told the judge one thing and it did another.** The citation prompt says not to judge completeness, and the model
  still marked half of a two-part answer as less than supported. The hand labels showed this, and the instruction was tightened,
  but the mistake did not go away.
- **A damage test was measuring the wrong thing.** "Change the first number" mostly changed the day in an "As of" date. Splitting
  it into figure changes and date changes showed that with reasoning on the judge catches about two thirds of small figure changes (12 of 18)
  and misses most changed dates (2 of 10).
- **Hand labels of good answers cannot test a judge by themselves.** Every answer and citation labelled by hand was labelled
  supported and correct, so agreement was high and said little. The known-bad checks added what the labels could not.
- **Targets, as measured.** rag-project retrieves the fact for 112 of 113 questions and declines all 10 unanswerable ones; CiteWise
  cites the right passage for 36 of 38 and declines all 6, but 5 of those 6 declines still carry citations, and it once said the
  filings did not state a headcount that they do. These come from one pass each, with the judge calibrated as shown above.

Not done: a measured change to a target (for example `RAG_TOP_K`), which would use repeated runs to separate a real difference
from run-to-run variation. See [`reports/`](reports/) for the two baselines.

## Layout

```
golden/          schema and golden sets
labels/          hand labels for calibrating the judge (the generated sheet is not tracked)
src/citecheck/
  models.py      what an adapter returns (chunks, citations, response)
  adapters/      the adapter interface, a mock for tests, and the rag-project and CiteWise adapters
  metrics/       retrieval.py, answer.py (counts the judge's verdicts), citations.py
  judge/         the judge: prompts, Ollama client, disk cache, per-answer verdicts
  calibration.py, citation_calibration.py, calibration_sheet.py   hand-label sampling, the labelling sheet, judge-vs-human agreement
  known_bad.py, known_bad_citations.py   damage known-good answers or cited sentences on purpose and check the judge flags it
  runner.py      `run`: ask the target, save raw responses
  scoring.py     `score`: metrics from a saved run
  golden.py      load and validate a golden set
  report.py      the Markdown report: scores beside their calibration evidence and caveats
  cli.py
tools/           one-off scripts: the golden-set converter and the CiteWise golden-set builder, a check against rag-project's published runs
tests/
runs/            saved runs (not in git except runs/published/)
reports/         generated report pages and their index
.github/         the CI workflow (tests only)
```
