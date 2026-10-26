# rag-project on rag-demo-1.1.0

Run `2026-10-24_145034_baseline-1-1`, made 2026-10-24T14:50:34 with citecheck 79534adc8d. Question set `rag-demo-1.1.0` (131 items), hash `b6dde77c7f12`.

Target: chat_model qwen3:8b, embed_model embeddinggemma, thinking True, split_search True, files 7, chunks 50.

Settings the target does not report, recorded by hand: RAG_TOP_K=4, RAG_SPLIT=1.

Judge: qwen3:8b, reasoning on, prompt v1, model digest `500a1f067a9f`.

## How to read this

Each score sits beside what is known about how far to trust it. Retrieval and the structure of the citations are counted from the target's own output. Faithfulness, correctness, abstention and claim support are a model's verdicts and are only as good as the calibration shown next to them. Nothing here compares this target with another: the question sets, corpora and checks differ.

## Retrieval

| Metric | Result | n | Evidence and caveats |
|---|---|---|---|
| Every fact retrieved (found) | 112/113 (99%) | 113 | Deterministic. It follows the target's own ranking and says nothing about whether retrieval is good. |
| Mean recall at the first 1 / 3 / 5 chunks | 0.847 / 0.972 / 0.993 | 113 | - |
| Mean reciprocal rank | 0.956 | 113 | - |

## Answers

| Metric | Result | n | Evidence and caveats |
|---|---|---|---|
| Unanswerable questions declined (right) | 10/10 (100%) | 10 | An off-topic answer is usually read as a refusal, so it skips the faithfulness check; correctness still flags it. Matched 35/36 (97%) of hand labels, from a sample chosen to be hard. Flagged 30/30 (100%) of answers damaged on purpose. |
| Answerable questions declined (false refusals) | 2/121 (2%) | 121 | - |
| Faithfulness (supported = 1, partly = 0.5) | 0.937: 104 supported, 15 partly, 0 unsupported | 119 | The judge leans strict: it can call a claim that a passage states outright partly supported. Matched 24/30 (80%) of hand labels, from a sample chosen to be hard; every hand label was `supported`, so the labels cannot show whether the judge catches a bad one. Flagged 60/67 (90%) of answers damaged on purpose and 6/30 (20%) of unchanged good ones (false alarms). |
| Correctness against the reference answer | 0.984: 118 correct, 2 partly, 1 incorrect | 121 | The judge can penalise extra detail that the reference does not contain, and can miss a contradicted opening. Matched 28/30 (93%) of hand labels, from a sample chosen to be hard; every hand label was `correct`, so the labels cannot show whether the judge catches a bad one. Flagged 85/95 (89%) of answers damaged on purpose and 2/30 (7%) of unchanged good ones (false alarms). |

## Citations

| Metric | Result | n | Evidence and caveats |
|---|---|---|---|
| Citation style | Lists whole files; no inline markers | 119 | Marker, dangling-marker, unused-source and claim-support checks need inline markers, so they do not apply. |
| Every fact's passage among the cited sources | 110/111 (99%) | 111 | Strict: an answer that cites another passage stating the same fact counts as missing it unless that wording is listed in the golden set as an alternate. No excerpts were available, so this was matched on the document alone. |
| Mean share of cited documents that are expected | 0.924 | 111 | Expected documents are the golden set's evidence documents and any listed alternates. |
| Declined answers that still list a source | 1/12 (8%) | 12 | - |

## By split and category

### By split

| group | asked | errors | found | faithful | correct | evidence cited | claim support |
|---|---|---|---|---|---|---|---|
| heldout | 55 | 0 | 45/46 (98%) | 0.92 (n=48) | 0.99 (n=50) | 44/44 (100%) | - |
| tuned | 67 | 0 | 59/59 (100%) | 0.95 (n=63) | 0.98 (n=63) | 59/59 (100%) | - |
| unlabeled | 9 | 0 | 8/8 (100%) | 0.94 (n=8) | 1.00 (n=8) | 7/8 (88%) | - |

### By category

| group | asked | errors | found | faithful | correct | evidence cited | claim support |
|---|---|---|---|---|---|---|---|
| edge_case | 15 | 0 | 14/15 (93%) | 0.93 (n=14) | 0.97 (n=15) | 13/14 (93%) | - |
| factual | 66 | 0 | 66/66 (100%) | 0.95 (n=65) | 0.98 (n=66) | 65/65 (100%) | - |
| follow_up | 8 | 0 | - | 0.81 (n=8) | 1.00 (n=8) | - | - |
| multi_topic | 22 | 0 | 22/22 (100%) | 1.00 (n=22) | 0.98 (n=22) | 22/22 (100%) | - |
| unanswerable | 10 | 0 | - | - | - | - | - |
| yes_no | 10 | 0 | 10/10 (100%) | 0.85 (n=10) | 1.00 (n=10) | 10/10 (100%) | - |

## What this cannot tell you

- About the question set: Converted from the question files in https://github.com/Nbhaskell/rag-project by tools/convert_ragproject.py. 'tuned' items were used while the prompt and thresholds were adjusted, so scores on them flatter the system. 'heldout' items were written afterwards and not used to tune, but were written by Claude from the documents (per that project's README), so they are unseen by the prompt, not blind to the corpus. Every item has a reference_answer, drafted by Claude from the corpus documents and checked by hand before merging (unanswerable items say the documents do not cover the question). No item is 'ambiguous' or 'conflicting' yet.
- This is one pass over the question set. Answers vary from run to run, and a model target gives no seed, so a difference of a few answers is not evidence of a real change.
- The judge (qwen3:8b) and the target answer with the same model family (qwen3:8b), so the judge may favour its own kind of answer. The calibration checks measure agreement with a person and with known damage; they do not rule that out.
- Where the tables show hand-label agreement, read it as an estimate for hard cases from a small sample, not a measured error rate.

## Items to look at (21)

Every question with something unusual in its result. This is a reading list, not a failure count: a flag from the judge may be the judge's mistake.

| Item | Category | Why |
|---|---|---|
| `discounts` | factual | faithfulness judged partly supported |
| `bring-blanket` | yes_no | faithfulness judged partly supported |
| `late-cancel-fee` | factual | correctness judged incorrect |
| `cancel-boarding-3-days` | edge_case | faithfulness judged partly supported |
| `package-refund` | yes_no | faithfulness judged partly supported |
| `ratio-and-eval-length` | multi_topic | correctness judged partly correct |
| `followup-bordetella` | follow_up | faithfulness judged partly supported |
| `followup-cancel-fee` | follow_up | faithfulness judged partly supported |
| `snow-closure` | factual | faithfulness judged partly supported |
| `how-to-reserve` | factual | faithfulness judged partly supported |
| `holiday-boarding-notice` | factual | faithfulness judged partly supported |
| `meal-packing` | factual | declined a question the documents answer |
| `report-contents` | factual | faithfulness judged partly supported |
| `medication-how` | factual | faithfulness judged partly supported |
| `first-visit` | yes_no | faithfulness judged partly supported |
| `late-7pm` | edge_case | a fact the question depends on was not retrieved |
| `late-cancel-package` | edge_case | correctness judged partly correct |
| `sunday-false-premise` | edge_case | declined a question the documents answer |
| `boarding-night` | factual | faithfulness judged partly supported |
| `followup-late-holiday-cancel` | follow_up | faithfulness judged partly supported |
| `pdf-nap-time-across-documents` | edge_case | faithfulness judged partly supported; the passage stating a fact is not among the cited sources |

## Files

- Run: `runs/published/2026-10-24_145034_baseline-1-1.run.json`
- Scores: `runs/published/2026-10-24_145034_baseline-1-1.citations.scores.json`
- Question set: `golden/rag_demo_v1.json`
- Agreement with hand labels 1: `runs/published/2026-10-24_145034_baseline-1-1.agreement-with-hand-labels.json`
- Known-bad check 1: `runs/published/2026-10-24_145034_baseline-1-1.known-bad-think-on.json`
- Known-bad check 2: `runs/published/2026-10-24_145034_baseline-1-1.known-bad-think-off.json`
