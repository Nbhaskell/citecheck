# citewise on citewise-filings-1.1.0

Run `2026-10-25_135415_baseline-citewise`, made 2026-10-25T13:54:15 with citecheck 1ef79f69fb (uncommitted changes). Question set `citewise-filings-1.1.0` (44 items), hash `99d88263da4c`.

Target: status ok, database True, ai_model ollama:qwen3:latest, ai_model_available True.

Settings the target does not report, recorded by hand: COPILOT_ROUTER=default, COPILOT_LOG=off.

Judge: qwen3:8b, reasoning on, prompt v1, model digest `500a1f067a9f`.

## How to read this

Each score sits beside what is known about how far to trust it. Retrieval and the structure of the citations are counted from the target's own output. Faithfulness, correctness, abstention and claim support are a model's verdicts and are only as good as the calibration shown next to them. Nothing here compares this target with another: the question sets, corpora and checks differ.

## Answers

| Metric | Result | n | Evidence and caveats |
|---|---|---|---|
| Unanswerable questions declined (right) | 6/6 (100%) | 6 | An off-topic answer is usually read as a refusal, so it skips the faithfulness check; correctness still flags it. |
| Answerable questions declined (false refusals) | 0/38 (0%) | 38 | - |
| Faithfulness (supported = 1, partly = 0.5) | 0.908: 34 supported, 1 partly, 3 unsupported | 38 | The judge leans strict: it can call a claim that a passage states outright partly supported. |
| Correctness against the reference answer | 0.947: 35 correct, 2 partly, 1 incorrect | 38 | The judge can penalise extra detail that the reference does not contain, and can miss a contradicted opening. |

## Citations

| Metric | Result | n | Evidence and caveats |
|---|---|---|---|
| Answers with inline markers | 38/38 (100%) | 38 | Applies to targets that cite inline. A target that lists only files has no markers. |
| Answers with a dangling marker / an unused source | 0 / 0 | 38 | - |
| Mean share of sentences that carry a marker | 0.925 | 38 | - |
| Every fact's passage among the cited sources | 36/38 (95%) | 38 | Strict: an answer that cites another passage stating the same fact counts as missing it unless that wording is listed in the golden set as an alternate. |
| Mean share of cited documents that are expected | 1.000 | 38 | Expected documents are the golden set's evidence documents and any listed alternates. |
| Cited sentences supported by their sources (supported = 1, partly = 0.5) | 0.943: 40 supported, 3 partly, 1 unsupported | 44 | The judge saw each excerpt without the title of the filing it came from, and can judge a sentence on whether it answers the question, which it is told not to do. Small figure changes and changed dates are often missed. Matched 26/30 (87%) of hand labels, from a sample chosen to be hard; every hand label was `supported`, so the labels cannot show whether the judge catches a bad one. Flagged 65/88 (74%) of cited sentences damaged on purpose and 3/30 (10%) of unchanged good ones (false alarms). |
| Declined answers that still carry citation markers | 5/6 (83%) | 6 | - |

## By split and category

### By split

| group | asked | errors | faithful | correct | evidence cited | claim support |
|---|---|---|---|---|---|---|
| heldout | 44 | 0 | 0.91 (n=38) | 0.95 (n=38) | 36/38 (95%) | 0.94 (n=44) |

### By category

| group | asked | errors | faithful | correct | evidence cited | claim support |
|---|---|---|---|---|---|---|
| edge_case | 3 | 0 | 0.67 (n=3) | 0.67 (n=3) | 3/3 (100%) | 0.62 (n=4) |
| factual | 23 | 0 | 1.00 (n=23) | 0.98 (n=23) | 23/23 (100%) | 0.98 (n=25) |
| follow_up | 4 | 0 | 1.00 (n=4) | 1.00 (n=4) | 4/4 (100%) | 1.00 (n=4) |
| multi_topic | 5 | 0 | 0.50 (n=5) | 0.90 (n=5) | 3/5 (60%) | 0.94 (n=8) |
| unanswerable | 6 | 0 | - | - | - | - |
| yes_no | 3 | 0 | 1.00 (n=3) | 1.00 (n=3) | 3/3 (100%) | 1.00 (n=3) |

## What this cannot tell you

- About the question set: Questions written by Claude from the SEC filings stored by Citewise for Markets, built by tools/build_citewise_golden.py from golden/citewise_questions_v1.json. Every item is split 'heldout': the target was not tuned on them, but they were written from the stored text, so they are unseen by the target, not blind to the corpus. Only filing text is used, because prices, headlines and the P/E change every night. Reference answers were drafted from the same text and then checked one by one by hand against the passages (none needed a change). A document id is the title Citewise gives its sources; its fingerprint identifies the filing, not its text. Unanswerable items are things the stored filings do not state, as far as searched.
- The run was asked from citewise-filings-1.0.0 (hash bb0103a66617) and is reported against citewise-filings-1.1.0 (hash 99d88263da4c), so the answers are the ones given then and the reference answers are those of the later version.
- The run was made from an uncommitted working tree, so the recorded commit is the previous one, not the exact code.
- This is one pass over the question set. Answers vary from run to run, and a model target gives no seed, so a difference of a few answers is not evidence of a real change.
- This target does not report what it retrieved, so retrieval is not scored; faithfulness is checked against the sources it cited, which is weaker than checking against everything the model read.
- The judge (qwen3:8b) and the target answer with the same model family (ollama:qwen3:latest), so the judge may favour its own kind of answer. The calibration checks measure agreement with a person and with known damage; they do not rule that out.
- No calibration evidence was supplied for the answer verdicts (abstention, faithfulness, correctness) with this judge configuration (qwen3:8b, reasoning on, prompt v1), so they are unvalidated here.
- Where the tables show hand-label agreement, read it as an estimate for hard cases from a small sample, not a measured error rate.
- In the hand labels for citations, every label in each dimension was the same, so they cannot show whether the judge catches a bad one; the known-bad check, where shown, covers that.

## Items to look at (13)

Every question with something unusual in its result. This is a reading list, not a failure count: a flag from the judge may be the judge's mistake.

| Item | Category | Why |
|---|---|---|
| `amzn-employees` | factual | correctness judged partly correct |
| `msft-buyback` | factual | 1 cited sentence(s) judged less than supported |
| `nvda-hq-and-employees` | multi_topic | correctness judged partly correct; the passage stating a fact is not among the cited sources |
| `amd-vs-nvda-employees` | multi_topic | faithfulness judged unsupported; 1 cited sentence(s) judged less than supported |
| `apple-and-msft-hq` | multi_topic | faithfulness judged partly supported |
| `amd-nvda-hq` | multi_topic | faithfulness judged unsupported; the passage stating a fact is not among the cited sources |
| `msft-googl-total` | edge_case | faithfulness judged unsupported; 2 cited sentence(s) judged less than supported |
| `amzn-tsla-gap` | edge_case | correctness judged incorrect |
| `unknown-tsla-chargers` | unanswerable | a declined answer still carries citation markers |
| `unknown-amd-cafeteria` | unanswerable | a declined answer still carries citation markers |
| `unknown-nvda-acres` | unanswerable | a declined answer still carries citation markers |
| `unknown-aapl-floors` | unanswerable | a declined answer still carries citation markers |
| `unknown-googl-dog` | unanswerable | a declined answer still carries citation markers |

## Files

- Run: `runs/published/2026-10-25_135415_baseline-citewise.run.json`
- Scores: `runs/published/2026-10-25_135415_baseline-citewise.judge-think-on.scores.json`
- Question set: `golden/citewise_filings_v1.json`
- Agreement with hand labels 1: `runs/published/2026-10-25_135415_baseline-citewise.citation-agreement.json`
- Known-bad check 1: `runs/published/2026-10-25_135415_baseline-citewise.citation-known-bad-think-on.json`
- Known-bad check 2: `runs/published/2026-10-25_135415_baseline-citewise.citation-known-bad-think-off.json`
