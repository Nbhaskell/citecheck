# CiteCheck

An evaluation harness for RAG systems. It runs a golden question set against a target system and scores three things:
whether retrieval found the right passage, whether the answer is faithful to what was retrieved, and whether the
citations are valid. Output is a CLI and a readable report.

The metrics are written by hand in plain Python, with no eval framework. Each target system sits behind a small
adapter, so one harness can score different projects.

> **Status: step 0 of 5.** Only the golden set and its validator exist. Nothing here scores a system yet; sections
> marked *planned* describe the intended design.

| Step | What | State |
|---|---|---|
| 0 | Golden set schema, converted question set, `validate` | done |
| 1 | Adapter interface, `run`/`score`, retrieval metrics | planned |
| 2 | LLM judge (faithfulness, correctness, abstention) and its calibration against hand labels | planned |
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
- **The held-out set was written by Claude** from the documents, so it is unseen by the prompt but not blind to the corpus.
- **Left out on purpose:** the older samples set (a different corpus) and the prompt-injection set (it tests resistance to
  injected instructions, not retrieval or citations).
- One phrase was tightened (`full-day-price`: `$100.00` also matched the training-session price) and one fact has two
  valid locations (`address`: the hours document and the PDF). Both are recorded in the converter.

## Design (planned)

- **`run` and `score` are separate.** `run` calls the target and saves raw responses to `runs/`; `score` computes metrics from
  that file, so the judge can be re-tuned without re-querying the target.
- **Adapters talk to the target over HTTP**, so the harness does not import the target's code or share its Python version.
- **Reproducibility.** Pinned dependencies (`requirements*.lock`), a saved results file per run recording the golden-set
  version, the target's settings, the judge model and prompt, and the git commit, and a disk cache for judge calls.
  The targets do not expose a seed, so run-to-run variation is measured by repeating runs, not removed.

## Findings

*Not written yet. The plan is a baseline, one measured change, and at least one case where a metric or the judge was wrong.*

## Layout

```
golden/      schema and golden sets
src/citecheck/   golden.py (load + validate), text.py (comparison rules), cli.py
tools/       one-off converters
tests/
runs/        saved runs (not in git except runs/published/)
```
