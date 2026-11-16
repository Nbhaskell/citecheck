# Build status and steps

> **Status: every planned step is built.** Retrieval, answer quality and citations are scored,
> against two targets (rag-project and CiteWise), with the local judge model checked against hand labels and known-bad answers,
> each scored run has a Markdown and an HTML report, one change to a target (`RAG_TOP_K`) has been measured against run-to-run
> variation, and a check that needs no model reads answers for figures and dates the judge tends to miss. The 44 reference
> answers for CiteWise were checked one by one by hand against the passages, and none needed a change (step 7). The answer
> verdicts were calibrated on CiteWise's own answers too (step 10).
> Sections marked *planned* describe the intended design.

| Step | What | State |
|---|---|---|
| 0 | Golden set schema, converted question set, `validate` | done |
| 1 | Adapter interface, `run`/`score`, retrieval metrics, rag-project adapter | done |
| 2 | LLM judge (faithfulness, correctness, abstention; `qwen3:8b` through Ollama) and its calibration against hand labels | done |
| 3 | Citation checks, second target (CiteWise) | done |
| 4 | Markdown report per run, tests-only CI | done |
| 5 | A measured change to a target: repeated passes at different settings, and `compare` | done |
| 6 | Figure and date check that needs no model, measured against the judge's gaps | done |
| 7 | Sheet and command for reviewing reference answers by hand | done; all 44 CiteWise references checked by hand, none corrected |
| 8 | HTML pages for reports and comparisons, rendered from their saved JSON | done |
| 9 | Citation prompt version 2 (no question shown, the previous sentence as context), calibrated again on a held-out sample | done |
| 10 | Answer verdicts calibrated on CiteWise: model labels for all 44 answers, hand labels for 23, and a known-bad check | done |
