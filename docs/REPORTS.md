# Reports


```
python -m citecheck report runs/published/<run id>.run.json --scores runs/published/<judged scores>.json --agreement <agreement>.json --known-bad <known-bad>.json --out reports/<name>.md
python -m citecheck report-index reports
```

A report is one Markdown page per scored run, built by [`src/citecheck/report.py`](../src/citecheck/report.py) from the run file, a
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

Committed reports, from the published baselines: [`reports/rag-project-baseline.md`](../reports/rag-project-baseline.md),
[`reports/citewise-baseline.md`](../reports/citewise-baseline.md) and their [index](../reports/index.md).
The `RAG_TOP_K` comparison page, [`reports/rag-project-top-k.md`](../reports/rag-project-top-k.md), is made by `compare` (see
[Comparing settings](COMPARING.md#comparing-settings)) and is not part of the index.

## HTML pages

```
python -m citecheck html reports                                  # every page and an index.html for a folder
python -m citecheck html reports/rag-project-baseline.report.json   # one page, beside its JSON
```

Each Markdown report and comparison has an HTML page: [`reports/index.html`](../reports/index.html),
[`reports/rag-project-baseline.html`](../reports/rag-project-baseline.html), [`reports/citewise-baseline.html`](../reports/citewise-baseline.html)
and [`reports/rag-project-top-k.html`](../reports/rag-project-top-k.html). They are built by
[`src/citecheck/report_html.py`](../src/citecheck/report_html.py) from the JSON copies saved beside the Markdown pages
(`*.report.json`, `*.compare.json`), not from a new scoring, so a page holds the numbers its Markdown page holds. Each page is one
self-contained file: no script, no outside resources, and every text escaped. It follows the reader's light or dark setting and
fits a phone's width; a wide table scrolls inside its own box. What the HTML adds over the Markdown is a contents line, each
metric's caveats as a list beside it, a collapsible reading list when it is long, and the comparison verdicts as labelled badges
(the words are always shown; colour is never the only signal).

The Markdown pages stay the record. A test rebuilds every committed HTML page from its JSON and requires an exact match, so a page
cannot drift from its data, and another checks the text and background colours of both themes against a 4.5:1 contrast ratio.
Limits: the dark theme was checked by that contrast test and not by eye, the pages were looked at in one browser at desktop and
phone widths, and the index lists the reports only, as the Markdown index does.
