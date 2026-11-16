# Comparing settings


A target's score moves from pass to pass even when nothing changes, because the answers vary. To tell a change in a setting
from that variation, each setting (an *arm*) is run for several passes over the same questions, every pass is judged, and
`compare` sets the difference between arms against the spread between passes.

```
# start the target with the setting, e.g. RAG_TOP_K=6 in rag-project's environment, then:
python -m citecheck run --golden golden/rag_demo_v1.json --target rag-project --label topk6 --repeat 5 --set RAG_TOP_K=6 --set RAG_SPLIT=1
python -m citecheck score runs/<run id>.run.json --judge --out runs/<run id>.judge-think-on.scores.json
python -m citecheck compare --arm RAG_TOP_K=4=<scores A> --arm RAG_TOP_K=6=<scores B> --out reports/<name>.md
```

`--set` only records a setting; the target has to be started with it. `compare` prints the number of passages per answer
beside each declared `RAG_TOP_K` and warns when they disagree. The first `--arm` is the baseline. It refuses scores made from
different question sets or judge settings, and reads each scores file's run file from the same folder. The code is in
[`src/citecheck/compare.py`](../src/citecheck/compare.py).

**What counts as a real difference.** Four headline measures were fixed before any result was seen: every fact retrieved,
faithfulness, correctness, and answerable questions declined. Everything else (MRR, recall, latency, the breakdowns) is
descriptive. A difference counts as *larger than noise* only when both tests hold:

1. **Spread test.** The difference of the arm means exceeds the two-sided 95% t value times its standard error, where the
   standard error comes from the spread between passes (the two arms pooled).
2. **Question test.** A paired bootstrap over questions (10,000 resamples, fixed seed; each question's value is its mean over an
   arm's passes) gives a 95% interval that excludes zero.

Meeting one test is reported as *unclear*, neither as *within noise*. Retrieval does not depend on how an answer is worded, so
its numbers were identical in every pass of an arm; with no spread to measure, the question test alone decides for them. With
four measures per comparison, one borderline result is expected by chance about once in five comparisons.

## Result: `RAG_TOP_K` 4, 6 and 2 on rag-project

All 131 questions of `rag-demo-1.1.0`, the same index, rag-project commit and judge (settings as above, prompts unchanged).
Arms: `RAG_TOP_K=4` and `6`, 5 passes each; `RAG_TOP_K=2`, 3 passes, as a control that should be visibly worse. The server was
restarted between arms, and the passages per answer confirm the setting was applied (most common count 4, 6 and 2). Full page:
[`reports/rag-project-top-k.md`](../reports/rag-project-top-k.md); data in [`runs/published/`](../runs/published/)
(`2026-10-26_*_topk*`).

| Measure | k=4 mean (SD) | k=6 mean (SD) | k=6 against k=4 | k=2 mean (SD) | k=2 against k=4 |
|---|---|---|---|---|---|
| Every fact retrieved | 0.991 (0) | 0.991 (0) | within noise | 0.947 (0) | larger than noise |
| Faithfulness | 0.939 (0.011) | 0.940 (0.008) | within noise | 0.951 (0.026) | within noise |
| Correctness | 0.973 (0.012) | 0.979 (0.006) | within noise | 0.938 (0.004) | unclear |
| Answerable questions declined | 0.007 (0.004) | 0.012 (0.005) | within noise | 0.044 (0.005) | larger than noise |
| Seconds per answer | 4.0 | 4.6 | | 5.4 | |

What it shows:

- **Raising `RAG_TOP_K` from 4 to 6 changed nothing that could be told from noise.** Retrieval was identical for every
  question: the facts found at 4 were already in the first 4, and the one question where the fact is not retrieved (112 of 113
  found) is not rescued by 6. Answer scores moved by less than their pass-to-pass spread. The 95% intervals over questions are
  wide enough to hide a change of about 0.02 either way (faithfulness -0.017 to +0.021, correctness -0.006 to +0.019, declined
  -0.010 to +0.025), and the smallest difference the spread test could flag was about 0.013 to 0.014 for correctness and
  faithfulness. So
  the result is "no effect larger than about 0.02 on these questions", not "no effect".
- **The extra passages cost time:** about 0.6 seconds more per answer (4.0 to 4.6) in this setup.
- **One question moved consistently, and it is a reading item, not a result.** `meal-packing` was declined in all 5 passes at 6
  and in none at 4; it accounts for the whole of the small rise in declined answerable questions (without it the arm at 6
  declined fewer than the arm at 4). One question out of 131 is not an effect of the setting.
- **The control shows the harness can see a worse setting.** At 2, 5 more facts go unretrieved (107 against 112 of 113), and
  answerable questions declined rise from 0 to 1 per pass to 5 or 6 of 121; both are *larger than noise*. The correctness drop
  (-0.035) is *unclear*: the spread test passes, but the interval over questions (-0.077 to +0.001) only just includes zero,
  which shows the rule is conservative. Faithfulness did not fall at 2; that is not evidence of better answers, because
  faithfulness skips declined answers, is judged against fewer passages, and rests on 3 passes with a wide spread.
- **A single pass is a noisy reading.** Five passes at the same setting gave faithfulness 0.920 to 0.947, correctness 0.959 to
  0.983, and 8 to 10 of the 10 unanswerable questions declined (the published baseline pass declined all 10).

Limits, all of which also appear on the page:

- **Arms were run as blocks, not interleaved**, so a drift in the machine over time is not separated from the setting. Seconds
  per answer were not monotone in the setting (5.4 at `RAG_TOP_K=2`, 4.0 at 4), so latency differences between arms cannot be
  attributed to the setting; whether the cause is a block effect or the model reasoning for longer on thin context was not
  isolated. Latency is descriptive only.
- **One small corpus** (7 documents, 50 chunks) and a set whose `tuned` questions were adjusted at `RAG_TOP_K=4`. The `heldout`
  split (55 questions) is the fairer read and is shown separately on the page.
- **Only some questions use `RAG_TOP_K` as their passage count:** 109 of 131 returned exactly 4 passages at 4, and 93 returned
  exactly 6 at 6. Split questions use a fixed 2 passages per part and follow-ups use half of `RAG_TOP_K` per search, which
  dilutes the effect in the totals.
- **Faithfulness is judged against whatever was retrieved**, so across arms of different size it is not a like-for-like check.
  The judge is the model that answers, and its calibration was measured on an earlier run at `RAG_TOP_K=4`, not on these answers.
- **The spread covers variation in the answers only.** It says nothing about other questions, another corpus or another judge.
