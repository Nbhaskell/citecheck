# CiteCheck

An evaluation harness for RAG systems. It runs a golden question set against a target system and scores three things:
whether retrieval found the right passage, whether the answer is faithful to what was retrieved, and whether the
citations are valid. Output is a CLI and a readable report.

The metrics are written by hand in plain Python, with no eval framework. Each target system sits behind a small
adapter, so one harness can score different projects.

> **Status: step 1 of 5.** Retrieval is scored; answer quality and citations are not yet. Sections marked *planned*
> describe the intended design.

| Step | What | State |
|---|---|---|
| 0 | Golden set schema, converted question set, `validate` | done |
| 1 | Adapter interface, `run`/`score`, retrieval metrics, rag-project adapter | done |
| 2 | LLM judge (faithfulness, correctness, abstention; `qwen3:8b` through Ollama) and its calibration against hand labels | planned |
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

- **No reference answers yet.** The source files only had keyword checks, so `answer_contains` is carried over as it was
  and `reference_answer` is empty. The judge step needs them.
- **No `ambiguous` or `conflicting` questions.** The categories exist; the source sets had none.
- **The held-out set was written by Claude** from the documents (as rag-project's README states), so it is unseen by the
  prompt but not blind to the corpus.
- **Left out on purpose:** the older samples set (a different corpus) and the prompt-injection set (it tests resistance to
  injected instructions, not retrieval or citations).
- One phrase was tightened (`full-day-price`: `$100.00` also matched the training-session price) and one fact has two
  valid locations (`address`: the hours document and the PDF). Both are recorded in the converter.

## Design (planned)

- **`run` and `score` are separate.** `run` calls the target and saves raw responses to `runs/`; `score` computes metrics from
  that file, so the judge can be re-tuned without re-querying the target.
- **Adapters talk to the target over HTTP**, so the harness does not import the target's code or share its Python version.
- **Reproducibility.** Pinned dependencies (`requirements*.lock`), a saved results file per run recording the golden-set
  version and a content hash, the target's settings, and the citecheck git commit; once the judge exists, also the judge
  model and prompt, with a disk cache for judge calls. The targets do not expose a seed, and the harness itself has no
  randomness yet, so run-to-run variation is measured by repeating runs, not removed.
- **The judge is the same model the target answers with** (`qwen3:8b`). That is free and local, but a model grading its
  own kind of answer may be too kind. Its agreement with hand labels will be measured and reported, not assumed.

## Findings

*Not written yet. The plan is a baseline, one measured change, and at least one case where a metric or the judge was wrong.*

## Layout

```
golden/          schema and golden sets
src/citecheck/
  models.py      what an adapter returns (chunks, citations, response)
  adapters/      the adapter interface, a mock for tests, and rag-project's
  metrics/       retrieval.py (more to come)
  runner.py      `run`: ask the target, save raw responses
  scoring.py     `score`: metrics from a saved run
  golden.py      load and validate a golden set
  cli.py
tools/           one-off scripts: the golden-set converter, a check against rag-project's published runs
tests/
runs/            saved runs (not in git except runs/published/)
```
