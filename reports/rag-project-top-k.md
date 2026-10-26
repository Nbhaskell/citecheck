# RAG_TOP_K 4 compared with 6 and 2 (rag-project, demo corpus)

Settings of one target compared over repeated passes of the same question set. Every number is arranged from saved scores files; no model is called to make this page.

## Provenance

| Arm | Declared settings | Passes | Runs | Passages per answer | Seconds per answer |
|---|---|---|---|---|---|
| RAG_TOP_K=4 | RAG_COMMIT=cb4ebe0, RAG_SPLIT=1, RAG_TOP_K=4 | 5 | `2026-10-26_102237_topk4` | 3.85 (most common 4, 545 of 655) | 4.0 |
| RAG_TOP_K=6 | RAG_COMMIT=cb4ebe0, RAG_SPLIT=1, RAG_TOP_K=6 | 5 | `2026-10-26_122339_topk6` | 5.36 (most common 6, 465 of 655) | 4.6 |
| RAG_TOP_K=2 | RAG_COMMIT=cb4ebe0, RAG_SPLIT=1, RAG_TOP_K=2 | 3 | `2026-10-26_143749_topk2` | 2.37 (most common 2, 303 of 393) | 5.4 |

Question set `rag-demo-1.1.0` (hash `b6dde77c7f`). Judge `qwen3:8b` (digest `500a1f067a9f`, prompt version 1), identical for every pass. Seconds per answer depend on the machine and are descriptive only.

## How a difference is judged

A difference between an arm and the first arm counts as **larger than noise** only when both tests hold:

1. **Spread test.** The difference of the arm means is larger than the 95% t value times its standard error, where the standard error comes from the spread between passes (the two arms pooled).
2. **Question test.** The 95% interval of a paired bootstrap over questions (10000 resamples, seed 0) excludes zero. Each question's value is its mean over an arm's passes.

Meeting one test gives **unclear**, neither gives **within noise**. Where the passes agree exactly there is no spread to measure and the question test alone decides. The four headline measures were chosen before any result was seen; the others are descriptive.

## RAG_TOP_K=6 against RAG_TOP_K=4

Differences recorded between the two targets: RAG_TOP_K: 4 against 6.

### Every pass

| Measure | RAG_TOP_K=4, per pass | RAG_TOP_K=6, per pass |
|---|---|---|
| Every fact retrieved | 112/113, 112/113, 112/113, 112/113, 112/113 | 112/113, 112/113, 112/113, 112/113, 112/113 |
| Faithfulness | 0.946, 0.920, 0.942, 0.947, 0.942 | 0.950, 0.937, 0.933, 0.933, 0.945 |
| Correctness | 0.959, 0.983, 0.983, 0.963, 0.975 | 0.983, 0.975, 0.975, 0.975, 0.988 |
| Answerable questions declined (lower is better) | 1/121, 0/121, 1/121, 1/121, 1/121 | 1/121, 2/121, 2/121, 1/121, 1/121 |
| MRR | 0.956, 0.956, 0.956, 0.956, 0.956 | 0.956, 0.956, 0.956, 0.956, 0.956 |
| Recall@1 | 0.847, 0.847, 0.847, 0.847, 0.847 | 0.847, 0.847, 0.847, 0.847, 0.847 |
| Recall@5 | 0.993, 0.993, 0.993, 0.993, 0.993 | 0.993, 0.993, 0.993, 0.993, 0.993 |

### Result

| Measure | RAG_TOP_K=4 mean (SD) | RAG_TOP_K=6 mean (SD) | Difference | 95% interval over questions | Spread test needs more than | Verdict |
|---|---|---|---|---|---|---|
| Every fact retrieved | 0.991 (0.000) | 0.991 (0.000) | +0.000 | +0.000 to +0.000 | no spread to measure | **within noise** |
| Faithfulness | 0.939 (0.011) | 0.940 (0.008) | +0.000 | -0.017 to +0.021 | ±0.014 | **within noise** |
| Correctness | 0.973 (0.012) | 0.979 (0.006) | +0.007 | -0.006 to +0.019 | ±0.013 | **within noise** |
| Answerable questions declined (lower is better) | 0.007 (0.004) | 0.012 (0.005) | +0.005 | -0.010 to +0.025 | ±0.006 | **within noise** |
| MRR (descriptive) | 0.956 (0.000) | 0.956 (0.000) | +0.000 | +0.000 to +0.000 | no spread to measure | - |
| Recall@1 (descriptive) | 0.847 (0.000) | 0.847 (0.000) | +0.000 | +0.000 to +0.000 | no spread to measure | - |
| Recall@5 (descriptive) | 0.993 (0.000) | 0.993 (0.000) | +0.000 | +0.000 to +0.000 | no spread to measure | - |

The interval is for the question-by-question difference (each question's mean over passes), so its centre can differ slightly from the difference of the pass means when the passes cover different numbers of answers.

### By split (descriptive)

| Group | Questions | Every fact retrieved: RAG_TOP_K=4 / RAG_TOP_K=6 / difference | Faithfulness: RAG_TOP_K=4 / RAG_TOP_K=6 / difference | Correctness: RAG_TOP_K=4 / RAG_TOP_K=6 / difference | Answerable questions declined: RAG_TOP_K=4 / RAG_TOP_K=6 / difference |
|---|---|---|---|---|---|
| heldout | 55 | 0.978 / 0.978 / +0.000 | 0.903 / 0.901 / -0.002 | 0.964 / 0.976 / +0.012 | 0.012 / 0.024 / +0.012 |
| tuned | 67 | 1.000 / 1.000 / +0.000 | 0.965 / 0.965 / -0.000 | 0.976 / 0.979 / +0.003 | 0.003 / 0.003 / +0.000 |
| unlabeled | 9 | 1.000 / 1.000 / +0.000 | 0.963 / 0.975 / +0.012 | 1.000 / 1.000 / +0.000 | 0.000 / 0.000 / +0.000 |

### By category (descriptive)

| Group | Questions | Every fact retrieved: RAG_TOP_K=4 / RAG_TOP_K=6 / difference | Faithfulness: RAG_TOP_K=4 / RAG_TOP_K=6 / difference | Correctness: RAG_TOP_K=4 / RAG_TOP_K=6 / difference | Answerable questions declined: RAG_TOP_K=4 / RAG_TOP_K=6 / difference |
|---|---|---|---|---|---|
| edge_case | 15 | 0.933 / 0.933 / +0.000 | 0.931 / 0.933 / +0.002 | 0.967 / 0.980 / +0.013 | 0.027 / 0.000 / -0.027 |
| factual | 66 | 1.000 / 1.000 / +0.000 | 0.939 / 0.953 / +0.015 | 0.980 / 0.985 / +0.005 | 0.006 / 0.021 / +0.015 |
| follow_up | 8 | - / - / - | 0.775 / 0.725 / -0.050 | 0.850 / 0.887 / +0.037 | 0.000 / 0.000 / +0.000 |
| multi_topic | 22 | 1.000 / 1.000 / +0.000 | 0.986 / 0.995 / +0.009 | 0.995 / 0.991 / -0.005 | 0.000 / 0.000 / +0.000 |
| unanswerable | 10 | - / - / - | 1.000 / 1.000 / +0.000 | - / - / - | - / - / - |
| yes_no | 10 | 1.000 / 1.000 / +0.000 | 0.980 / 0.910 / -0.070 | 0.980 / 0.990 / +0.010 | 0.000 / 0.000 / +0.000 |

### Questions that changed

Questions whose mean for a headline measure differs by 0.8 or more between the arms. A reading list, not a count of failures.

1 listed

| Question | Measure | RAG_TOP_K=4 | RAG_TOP_K=6 |
|---|---|---|---|
| `meal-packing` | Answerable questions declined | 0.00 | 1.00 |

## RAG_TOP_K=2 against RAG_TOP_K=4

Differences recorded between the two targets: RAG_TOP_K: 4 against 2.

### Every pass

| Measure | RAG_TOP_K=4, per pass | RAG_TOP_K=2, per pass |
|---|---|---|
| Every fact retrieved | 112/113, 112/113, 112/113, 112/113, 112/113 | 107/113, 107/113, 107/113 |
| Faithfulness | 0.946, 0.920, 0.942, 0.947, 0.942 | 0.957, 0.923, 0.974 |
| Correctness | 0.959, 0.983, 0.983, 0.963, 0.975 | 0.938, 0.934, 0.942 |
| Answerable questions declined (lower is better) | 1/121, 0/121, 1/121, 1/121, 1/121 | 5/121, 5/121, 6/121 |
| MRR | 0.956, 0.956, 0.956, 0.956, 0.956 | 0.945, 0.945, 0.945 |
| Recall@1 | 0.847, 0.847, 0.847, 0.847, 0.847 | 0.847, 0.847, 0.847 |
| Recall@5 | 0.993, 0.993, 0.993, 0.993, 0.993 | 0.953, 0.953, 0.953 |

### Result

| Measure | RAG_TOP_K=4 mean (SD) | RAG_TOP_K=2 mean (SD) | Difference | 95% interval over questions | Spread test needs more than | Verdict |
|---|---|---|---|---|---|---|
| Every fact retrieved | 0.991 (0.000) | 0.947 (0.000) | -0.044 | -0.088 to -0.009 | no spread to measure | **larger than noise** |
| Faithfulness | 0.939 (0.011) | 0.951 (0.026) | +0.012 | -0.019 to +0.026 | ±0.031 | **within noise** |
| Correctness | 0.973 (0.012) | 0.938 (0.004) | -0.035 | -0.077 to +0.001 | ±0.017 | **unclear** |
| Answerable questions declined (lower is better) | 0.007 (0.004) | 0.044 (0.005) | +0.037 | +0.010 to +0.071 | ±0.007 | **larger than noise** |
| MRR (descriptive) | 0.956 (0.000) | 0.945 (0.000) | -0.011 | -0.023 to -0.002 | no spread to measure | - |
| Recall@1 (descriptive) | 0.847 (0.000) | 0.847 (0.000) | +0.000 | +0.000 to +0.000 | no spread to measure | - |
| Recall@5 (descriptive) | 0.993 (0.000) | 0.953 (0.000) | -0.040 | -0.080 to -0.009 | no spread to measure | - |

The interval is for the question-by-question difference (each question's mean over passes), so its centre can differ slightly from the difference of the pass means when the passes cover different numbers of answers.

### By split (descriptive)

| Group | Questions | Every fact retrieved: RAG_TOP_K=4 / RAG_TOP_K=2 / difference | Faithfulness: RAG_TOP_K=4 / RAG_TOP_K=2 / difference | Correctness: RAG_TOP_K=4 / RAG_TOP_K=2 / difference | Answerable questions declined: RAG_TOP_K=4 / RAG_TOP_K=2 / difference |
|---|---|---|---|---|---|
| heldout | 55 | 0.978 / 0.935 / -0.043 | 0.903 / 0.948 / +0.045 | 0.964 / 0.933 / -0.031 | 0.012 / 0.060 / +0.048 |
| tuned | 67 | 1.000 / 0.983 / -0.017 | 0.965 / 0.955 / -0.011 | 0.976 / 0.963 / -0.013 | 0.003 / 0.016 / +0.013 |
| unlabeled | 9 | 1.000 / 0.750 / -0.250 | 0.963 / 0.952 / -0.010 | 1.000 / 0.771 / -0.229 | 0.000 / 0.167 / +0.167 |

### By category (descriptive)

| Group | Questions | Every fact retrieved: RAG_TOP_K=4 / RAG_TOP_K=2 / difference | Faithfulness: RAG_TOP_K=4 / RAG_TOP_K=2 / difference | Correctness: RAG_TOP_K=4 / RAG_TOP_K=2 / difference | Answerable questions declined: RAG_TOP_K=4 / RAG_TOP_K=2 / difference |
|---|---|---|---|---|---|
| edge_case | 15 | 0.933 / 0.800 / -0.133 | 0.931 / 0.914 / -0.018 | 0.967 / 0.844 / -0.122 | 0.027 / 0.089 / +0.062 |
| factual | 66 | 1.000 / 0.955 / -0.045 | 0.939 / 0.963 / +0.024 | 0.980 / 0.927 / -0.054 | 0.006 / 0.061 / +0.055 |
| follow_up | 8 | - / - / - | 0.775 / 0.875 / +0.100 | 0.850 / 1.000 / +0.150 | 0.000 / 0.000 / +0.000 |
| multi_topic | 22 | 1.000 / 1.000 / +0.000 | 0.986 / 0.985 / -0.002 | 0.995 / 0.985 / -0.011 | 0.000 / 0.000 / +0.000 |
| unanswerable | 10 | - / - / - | 1.000 / 1.000 / +0.000 | - / - / - | - / - / - |
| yes_no | 10 | 1.000 / 1.000 / +0.000 | 0.980 / 0.917 / -0.063 | 0.980 / 1.000 / +0.020 | 0.000 / 0.000 / +0.000 |

### Questions that changed

Questions whose mean for a headline measure differs by 0.8 or more between the arms. A reading list, not a count of failures.

13 listed

| Question | Measure | RAG_TOP_K=4 | RAG_TOP_K=2 |
|---|---|---|---|
| `holiday-boarding-notice` | Every fact retrieved | 1.00 | 0.00 |
| `pdf-drop-off-door` | Every fact retrieved | 1.00 | 0.00 |
| `pdf-nap-time-across-documents` | Every fact retrieved | 1.00 | 0.00 |
| `ten-day-savings` | Every fact retrieved | 1.00 | 0.00 |
| `vaccines-required` | Every fact retrieved | 1.00 | 0.00 |
| `holiday-boarding-notice` | Correctness | 1.00 | 0.00 |
| `pdf-drop-off-door` | Correctness | 1.00 | 0.00 |
| `pdf-nap-time-across-documents` | Correctness | 1.00 | 0.17 |
| `ten-day-savings` | Correctness | 1.00 | 0.00 |
| `vaccines-required` | Correctness | 1.00 | 0.00 |
| `holiday-boarding-notice` | Answerable questions declined | 0.00 | 1.00 |
| `pdf-drop-off-door` | Answerable questions declined | 0.00 | 1.00 |
| `vaccines-required` | Answerable questions declined | 0.00 | 1.00 |

## What this cannot tell you

- Each arm is a block of passes run one after another, not interleaved with the other arms, so a change in the machine over time is not separated from the setting.
- The spread between passes covers variation in the answers (and the judge's reading of them) only. It does not cover other questions, another corpus or another judge.
- Rows for the `tuned` split come from questions the system was adjusted against; `heldout` rows are the fairer read.
- The judge's agreement with hand labels was measured on an earlier run, not on these answers.
- 4 headline measures are compared per pair of arms, so one borderline result in 4 is expected by chance about once in five comparisons; an isolated `unclear` is not a finding.
- The judge is the same model as the one answering (qwen3:8b), which may favour its own style.
- The arms return different numbers of passages, and faithfulness is judged against the passages returned, so a faithfulness difference is not between like-for-like checks.
- Retrieval was identical in every pass within each arm, so for it the only uncertainty is which questions were asked, and the question test alone decides.
