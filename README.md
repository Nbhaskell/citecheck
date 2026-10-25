# CiteCheck

An evaluation harness for RAG systems. It runs a golden question set against a target system and scores three things:
whether retrieval found the right passage, whether the answer is faithful to what was retrieved, and whether the
citations are valid. Output is a CLI and a readable report.

The metrics are written by hand in plain Python, with no eval framework. Each target system sits behind a small
adapter, so one harness can score different projects.

> **Status: step 2 of 5.** Retrieval and answer quality (a local judge model, checked against hand labels and known-bad
> answers) are scored; citations are not yet. Sections marked *planned* describe the intended design.

| Step | What | State |
|---|---|---|
| 0 | Golden set schema, converted question set, `validate` | done |
| 1 | Adapter interface, `run`/`score`, retrieval metrics, rag-project adapter | done |
| 2 | LLM judge (faithfulness, correctness, abstention; `qwen3:8b` through Ollama) and its calibration against hand labels | done |
| 3 | Citation checks, second target (CiteWise) | planned |
| 4 | Markdown/HTML report, optional CI | planned |

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
| first price or number changed: flagged for faithfulness / correctness | 26 | 26 / 23 | 24 / 23 |
| a sentence the documents never state added: flagged for faithfulness | 30 | 30 | 29 |
| answer replaced by another question's answer: flagged for correctness | 30 | 29 | 28 |
| answer replaced by a bare refusal: flagged as declined / as incorrect | 30 | 30 / 30 | 30 / 30 |
| leading Yes/No flipped: flagged for correctness | 9 | 4 | 3 |

Counts exclude calls that failed (2 timeouts with reasoning on, which now has a longer default wait). With reasoning off the
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

*Not written yet. The plan is a baseline, one measured change, and at least one case where a metric or the judge was wrong.*

## Layout

```
golden/          schema and golden sets
labels/          hand labels for calibrating the judge (the generated sheet is not tracked)
src/citecheck/
  models.py      what an adapter returns (chunks, citations, response)
  adapters/      the adapter interface, a mock for tests, and rag-project's
  metrics/       retrieval.py, answer.py (counts the judge's verdicts); citations to come
  judge/         the judge: prompts, Ollama client, disk cache, per-answer verdicts
  calibration.py, calibration_sheet.py   hand-label sampling, the labelling sheet, judge-vs-human agreement
  known_bad.py   damage known-good answers on purpose and check the judge flags it
  runner.py      `run`: ask the target, save raw responses
  scoring.py     `score`: metrics from a saved run
  golden.py      load and validate a golden set
  cli.py
tools/           one-off scripts: the golden-set converter, a check against rag-project's published runs
tests/
runs/            saved runs (not in git except runs/published/)
```
