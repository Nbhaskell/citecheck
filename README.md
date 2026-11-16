# CiteCheck

[![CI](https://github.com/Nbhaskell/citecheck/actions/workflows/ci.yml/badge.svg)](https://github.com/Nbhaskell/citecheck/actions/workflows/ci.yml)

**A quality check for AI question-answering systems.** Website chatbots and internal knowledge assistants answer questions from
a set of documents. CiteCheck asks such a system a fixed list of questions with known answers, then reports how often it found
the right source, answered correctly, quoted figures that really are in the source, and said that it did not know when the
documents did not cover the question. Every score comes with the evidence for trusting it and its known weaknesses.

**Read the results first:** [rag-project report](reports/rag-project-baseline.md) · [CiteWise report](reports/citewise-baseline.md) ·
[the `RAG_TOP_K` comparison](reports/rag-project-top-k.md) (each also as an HTML page in the same folder) ·
[how a test found why the AI judge marked correct answers wrong](docs/how-the-judge-was-fixed.md)

**What it has found**

- **Two real systems checked.** [rag-project](https://github.com/Nbhaskell/rag-project) (131 questions) found the right passage
  for 99% of the questions it should answer and declined all 10 it should not. [Citewise for Markets](https://github.com/Nbhaskell/citewise-markets)
  (44 questions about SEC filings) declined all 6 unanswerable questions, and 98% of its cited sentences are backed by their sources.
- **The checker was checked too.** The AI judge that reads the answers was compared with a person's labels and with answers
  damaged on purpose. It marked correct citations wrong when the question asked for more than the sentence gave; after a fix,
  its agreement with fresh hand labels rose from 22 of 30 to 29 of 30.
- **A change was measured fairly.** Reading 6 passages instead of 4 made no difference beyond the normal run-to-run variation.
- **The limits are written down.** The question sets are small (131 and 44), the hand labels come from one labeller, and a single
  local judge model does the reading. Each report says what its numbers cannot show.

**How it is built:** asking a system and scoring its answers are separate steps, so a scoring rule can change without asking
again; the judge runs locally and costs nothing per answer; every number traces to a saved file; the metrics are plain Python
with no evaluation framework; each system sits behind a small adapter, so one harness can score different projects; 288 tests.

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

## Results

One pass of each target, scored by the local judge. The full pages give every score with its evidence and its limits.

| Target | Questions | Right passage | Unanswerable questions declined | Report |
|---|---|---|---|---|
| [rag-project](https://github.com/Nbhaskell/rag-project) | 131 | found for 112 of 113 | 10 of 10 | [Markdown](reports/rag-project-baseline.md), [HTML](reports/rag-project-baseline.html) |
| [Citewise for Markets](https://github.com/Nbhaskell/citewise-markets) | 44 | cited for 36 of 38 | 6 of 6 | [Markdown](reports/citewise-baseline.md), [HTML](reports/citewise-baseline.html) |

The question sets are small, one person wrote the hand labels, and one local model is the judge. See [Findings](#findings).

## More detail

| Page | What it covers |
|---|---|
| [docs/METRICS.md](docs/METRICS.md) | Retrieval, answer and citation metrics, the figure and date check, and each calibration of the judge |
| [docs/REPORTS.md](docs/REPORTS.md) | What a report page holds, and the HTML pages |
| [docs/COMPARING.md](docs/COMPARING.md) | How a change to a target is measured against run-to-run variation, with the `RAG_TOP_K` result |
| [docs/GOLDEN_SET.md](docs/GOLDEN_SET.md) | The question-set format, the two sets, and the hand review of the reference answers |
| [docs/how-the-judge-was-fixed.md](docs/how-the-judge-was-fixed.md) | How a test found why the judge marked correct answers wrong |
| [docs/DECISIONS.md](docs/DECISIONS.md) | The decision log |
| [docs/STATUS.md](docs/STATUS.md) | The build steps and their state |

## Continuous integration

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs the tests on every push to `main` and every pull request: Python 3.13 on
Linux, the pinned packages from `requirements-dev.lock`, and actions pinned to full commits. It runs the code's tests only, with no
Ollama, no target and no judge, so a green check says the code and the published report data hang together. It does not re-measure
any score.

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
  in [docs/METRICS.md](docs/METRICS.md), not assumed; those checks must be repeated whenever a prompt changes.

## Findings

What running the harness against two targets showed, including where the harness itself was wrong:

- **The judge needs reasoning on.** With it off, `qwen3:8b` called most good answers partly or fully unsupported, even when a
  passage states the claim word for word (21 of 30 labelled-good answers flagged, against 6 with it on). For judging whether a
  cited sentence matches its sources the two settings were about equal.
- **A second target found a harness bug.** CiteWise reports only the passages an answer cited, so faithfulness, checked against
  "retrieved passages", scored 0.00 for every answer. It is now checked against the cited sources for such a target.
- **A prompt told the judge one thing and it did another.** The citation prompt said not to judge completeness, and the model
  still marked half of a two-part answer as less than supported. Tightening the instruction did not remove the mistake; not
  showing the judge the question did (see [citation prompt version 2](docs/METRICS.md#citation-prompt-version-2)).
- **A damage test was measuring the wrong thing.** "Change the first number" mostly changed the day in an "As of" date. Splitting
  it into figure changes and date changes showed that with reasoning on the judge catches about two thirds of small figure changes (12 of 18)
  and misses most changed dates (2 of 10).
- **Hand labels of good answers cannot test a judge by themselves.** Every answer and citation labelled by hand was labelled
  supported and correct, so agreement was high and said little. The known-bad checks added what the labels could not.
- **Targets, as measured.** rag-project retrieves the fact for 112 of 113 questions and declines all 10 unanswerable ones; CiteWise
  cites the right passage for 36 of 38 and declines all 6, but 5 of those 6 declines still carry citations, and it once said the
  filings did not state a headcount that they do. These come from one pass each, with the judge calibrated as shown in [docs/METRICS.md](docs/METRICS.md);
  rag-project's was later repeated (next bullets).
- **One pass is a noisy reading.** Five passes of rag-project at the same setting gave faithfulness 0.920 to 0.947, correctness
  0.959 to 0.983 and 8 to 10 of 10 unanswerable questions declined, against 0.94, 0.98 and 10 of 10 in the one published pass.
  The spread between passes is about 0.01 on faithfulness and correctness, so differences of that size between two single
  passes mean nothing.
- **A change that does nothing is a result too.** Raising `RAG_TOP_K` from 4 to 6 moved no headline measure beyond noise, and
  retrieval was identical for every question. Lowering it to 2 was visible in retrieval and in declined answers, but the drop
  in correctness stayed *unclear* under the two-test rule, which is conservative by design.
- **A setting that is only recorded can be recorded wrongly.** `--set` writes a value the harness cannot check, so `compare`
  checks the passages per answer against it.
- **Two different checks cover different mistakes.** The judge flagged a figure swapped for another from the same passage in 39
  of 40 cases but missed 6 of 18 small invented changes and 8 of 10 changed days; the check that needs no model found all of
  those and none of the swaps. Neither is enough alone, and the table that shows it rests on damage that is partly circular for the
  check (see [the figure and date check](docs/METRICS.md#figure-and-date-check-no-model)).
- **A check developed on the data it is measured on looks better than it is.** The rules for figures were shaped by reading false
  alarms on the runs used to measure them, so the low false-alarm rate needs repeating on a new target before it is trusted.

Not done: a test of whether showing the judge each source's filing title removes the strict faithfulness misses on CiteWise,
and a fix for small figure and date changes in the judge's verdicts. With citation prompt version 2 they are mostly
flagged as partly supported and rarely as unsupported; the separate figure check catches those where the new figure is in no
source. With reasoning on, the citation verdict can also accept a sentence with two claims when only one is in the sources. See [`reports/`](reports/) for the two baselines and
the `RAG_TOP_K` comparison.

## Layout

```
golden/          schema and golden sets
labels/          hand labels for calibrating the judge (the generated sheet is not tracked)
src/citecheck/
  models.py      what an adapter returns (chunks, citations, response)
  adapters/      the adapter interface, a mock for tests, and the rag-project and CiteWise adapters
  metrics/       retrieval.py, answer.py (counts the judge's verdicts), citations.py, figures.py (figures and dates, no model)
  judge/         the judge: prompts, Ollama client, disk cache, per-answer verdicts
  calibration.py, citation_calibration.py, calibration_sheet.py   hand-label sampling, the labelling sheet, judge-vs-human agreement
  known_bad.py, known_bad_citations.py   damage known-good answers or cited sentences on purpose and check the judge flags it
  known_bad_figures.py   the same damage, checked against the figure and date check, with the judge's results beside it
  reference_review.py    the reference-answer review: the sheet's data, checking a downloaded review, applying it to the golden set
  runner.py      `run`: ask the target, save raw responses
  scoring.py     `score`: metrics from a saved run
  golden.py      load and validate a golden set
  report.py      the Markdown report: scores beside their calibration evidence and caveats
  report_html.py the HTML pages for reports and comparisons, rendered from their saved JSON
  compare.py     `compare`: settings of one target over repeated judged passes, against the spread between passes
  cli.py
tools/           one-off scripts: the golden-set converter and the CiteWise golden-set builder, a check against rag-project's published runs
tests/
runs/            saved runs (not in git except runs/published/)
reports/         generated report pages and their index
docs/            metrics and calibration, reports, comparing settings, the golden set, how the citation judge was fixed, and the decision log
SECURITY.md      how to report a vulnerability
.github/         the CI workflow (tests only)
```

## Security

See [`SECURITY.md`](SECURITY.md) for what counts as a vulnerability and how to report one privately.

## License

MIT. See the `LICENSE` file. The CiteWise golden set quotes short excerpts of public SEC filings, and the rag-project golden set
quotes that project's made-up demo documents, which are included under the same license there.
