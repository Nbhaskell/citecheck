# The golden set


A golden set is one JSON file per target and corpus, checked by [`golden/schema.json`](../golden/schema.json) and by the
cross-item rules in [`src/citecheck/golden.py`](../src/citecheck/golden.py). Its header names the corpus and records a
SHA-256 for every document, so a score can be tied to the exact text the questions were written against.

Each item has:

- a `question`, a `category` (`factual`, `yes_no`, `multi_topic`, `edge_case`, `follow_up`, `unanswerable`,
  `ambiguous`, `conflicting`, `probe`) and an `expected_abstain` flag. A `probe` is a question asked only to collect
  answers for hand labelling or for checking a judge: it has no evidence or reference answer and is not scored for retrieval or
  correctness;
- `evidence`: the facts the answer depends on. Each has a short `anchor` phrase and the verbatim passage(s) that state it,
  with document, heading path and page. Retrieval is judged against these, by text rather than by chunk id, so it still
  works when a target changes how it chunks;
- a `split`: `tuned` (the system was adjusted while looking at these), `heldout` (written afterwards, not used to tune) or
  `unlabeled`. Scores are reported per split, because a tuned score flatters the system;
- optional keyword checks (`answer_contains`, `answer_not_contains`), source expectations, a `reference_answer`, notes,
  and `origin` (which file it was converted from).

## `golden/rag_demo_v1.json`

131 questions about a made-up dog daycare, converted from the question files of
[rag-project](https://github.com/Nbhaskell/rag-project) by [`tools/convert_ragproject.py`](../tools/convert_ragproject.py)
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
  [`golden/reference_answers_rag_demo_v1.json`](../golden/reference_answers_rag_demo_v1.json) and the converter merges them
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

## `golden/citewise_filings_v1.json`

44 questions for CiteWise, built by [`tools/build_citewise_golden.py`](../tools/build_citewise_golden.py) from
[`golden/citewise_questions_v1.json`](../golden/citewise_questions_v1.json) and the filings that project has stored. Each fact in the
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
  drafted from the same text and then checked by hand against the passages (see below); a check against the same
  passages the drafts came from confirms that the answers match the text, not that the text was the right place to look.
- **Filing text only.** The 29 filings (10-K and 10-Q of seven companies) are identified by title and by a fingerprint of the
  accession number and URL, which identifies an immutable document but does not hash its text. A new filing adds documents, and a
  changed passage changes the golden set's hash, so saved runs then refuse to be scored against it.
- **Unanswerable means not stated in the filings as far as searched.** One is a near miss: the filings give an acreage for
  Microsoft's campus but not for NVIDIA's.
- **Mostly headcounts, headquarters, segments and buybacks.** Facts of this kind keep the evidence checkable, and say little about
  harder filing questions.

### Reviewing the reference answers by hand

```
python -m citecheck review-sheet --golden golden/citewise_filings_v1.json --out labels/reference-review-sheet.html
python -m citecheck apply-review <downloaded file> --golden golden/citewise_filings_v1.json --questions golden/citewise_questions_v1.json
```

`review-sheet` writes one HTML page (not tracked, like the labelling sheets) with a card per item: the question, the draft reference
answer in an editable box, the key phrases and the passages it was built from, and the keywords the answer must contain. Each
item is marked *right as written*, *corrected in the box*, or *unclear*. Nothing is sent anywhere; progress stays in the browser
until the file is downloaded.

`apply-review` refuses, and writes nothing, when an item is unreviewed, marked unclear, inconsistent (marked right but changed, or
marked corrected but unchanged), or was reviewed against another version of the golden set. Otherwise it rewrites the golden set
and the questions file with the corrected answers, moves the version to `citewise-filings-1.1.0`, changes the notes to say the
answers were checked by hand, and writes a record of every decision (with the draft text of each corrected answer) beside the
golden set. `tools/build_citewise_golden.py` reads the review state from the questions file, so rebuilding gives the same notes
and version.

The golden set's hash changes with that, so the published CiteWise run, asked from `citewise-filings-1.0.0`, refuses to be scored
against `1.1.0`. Its answers are unchanged, so `score --ignore-golden-mismatch` re-judges correctness against the reviewed
references; the judge's cache keeps every unchanged reference free. `report` takes the same flag, shows the question set it was
given, and adds a line to the report's limits naming the version the run was asked from.

**Result for CiteWise.** All 44 items were marked *right as written*, so no reference answer changed and the golden set moved
from `citewise-filings-1.0.0` to `1.1.0` with new notes, a `reference_review` entry in the questions file and the record
[`golden/citewise_filings_v1.reference-review.json`](../golden/citewise_filings_v1.reference-review.json). Re-scoring the published run
against `1.1.0` gave the same judged value for every one of the 44 answers, so the published scores file is kept and the
[CiteWise report](../reports/citewise-baseline.md) was regenerated against `1.1.0`; its numbers are unchanged.

The six unanswerable items have no passages to read, so their premise was checked another way: five differently worded searches
of the stored filings for each company, filtered for the terms of the question (chargers, cafeteria, acres, floors, parking, dogs).
None of the stored passages seen states a figure or policy the question asks for. Tesla's filings discuss Superchargers throughout
but give no count at headquarters, and Apple's give only the address "One Apple Park Way". The search returns the nearest 20
passages per query and is not a scan of every stored passage.
