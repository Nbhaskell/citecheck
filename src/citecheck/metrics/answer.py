"""Answer metrics, summarised from the judge's verdicts.

The judge model decides each verdict (see judge/prompts.py); this module only counts them, so it is deterministic given
the verdicts.

    abstention    how often the target declined. Reported separately for questions the corpus cannot answer
                  (declining is right) and questions it can (declining is a false refusal).
    faithfulness  of the answers that are not pure abstentions, how many claim only what the retrieved passages support.
    correctness   of the answerable questions with a reference answer, how many match it.

faithfulness and correctness each have a score: supported/correct = 1, partly = 0.5, otherwise 0, averaged over the
answers judged. A verdict of None (the judge failed on that call) is counted as an error and left out of the averages.
"""
from collections.abc import Sequence

from ..judge import prompts

WEIGHTS = {"supported": 1.0, "partly_supported": 0.5, "unsupported": 0.0,
           "correct": 1.0, "partly_correct": 0.5, "incorrect": 0.0}


def _tally(verdicts: Sequence[str | None], labels: Sequence[str]) -> dict:
    counts = {label: sum(v == label for v in verdicts) for label in labels}
    judged = sum(counts.values())
    score = None if judged == 0 else round(sum(WEIGHTS[label] * n for label, n in counts.items()) / judged, 4)
    return {"n": judged, **counts, "score": score}


def summarize(entries: Sequence[dict]) -> dict:
    """entries: one per answer that was judged, as {"expected_abstain": bool, "judged": <Judge.judge_item result>}."""
    judged = [e["judged"] for e in entries]
    errors = sum(v["error"] is not None for j in judged for v in j.values())

    def abstention(wanted: bool) -> dict:
        verdicts = [e["judged"]["abstention"]["verdict"] for e in entries if e["expected_abstain"] is wanted]
        return {"n": sum(v is not None for v in verdicts), **{label: verdicts.count(label) for label in prompts.ABSTENTION}}

    return {
        "judged": len(entries),
        "judge_errors": errors,
        "abstention": {"unanswerable": abstention(True), "answerable": abstention(False)},
        "faithfulness": _tally([j["faithfulness"]["verdict"] for j in judged if "faithfulness" in j], prompts.FAITHFULNESS),
        "correctness": _tally([j["correctness"]["verdict"] for j in judged if "correctness" in j], prompts.CORRECTNESS),
    }
