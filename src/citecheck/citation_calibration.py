"""Calibration for citation support: does the judge agree with a person on whether the sources cited for a sentence
support that sentence?

Same method as calibration.py (a sample weighted toward items two judge settings disagree on, labelled blind, then agreement
measured), with one question per cited sentence instead of three per answer. A unit is one sentence of an answer that
carries markers; its key is "<item id>#<n>", n counting such sentences from 1 in the order the judge saw them.
"""
import random
from collections import Counter

from .calibration import AGREE, DISAGREE, LABELS_VERSION, history_block, options_for
from .metrics import citations
from .models import TargetResponse

DIM = "citation_support"
RULES = [
    "You are judging one <b>statement</b> taken from an answer, and the <b>sources the answer cited for it</b>. The system's "
    "own verdicts are not shown, on purpose.",
    "Use only the cited sources shown, not what you know and not any other source. Ignore the bracketed numbers; they only say "
    "which source is meant.",
    "<i>Supported</i>: the cited sources say what the statement says, or it follows directly from them (for example adding two "
    "figures they give). <i>Partly supported</i>: they back the main point but not a detail, or only part of a statement with "
    "several parts. <i>Unsupported</i>: they do not back the main point, or they say something different.",
    "Your answers are saved in this browser as you go. When all are done, press <b>Download labels</b> and send or place the "
    "file where asked. A note is optional but helpful when you were unsure.",
]


def unit_key(item_id: str, index: int) -> str:
    return f"{item_id}#{index}"


def unit_verdicts(scores: dict) -> dict:
    """key -> the judge's support verdict, for every cited sentence a scores file judged (first repeat only)."""
    out, seen = {}, set()
    for row in scores["items"]:
        if row["item_id"] in seen or not row.get("citations") or not row["citations"]["support"]:
            continue
        seen.add(row["item_id"])
        for index, unit in enumerate(row["citations"]["support"], 1):
            if unit["verdict"] is not None:
                out[unit_key(row["item_id"], index)] = unit["verdict"]
    return out


def select_units(scores_list: list[dict], n: int = 30, seed: int = 0, share_disagree: float = 0.65) -> dict:
    """Pick n cited sentences to label: mostly the hard ones (settings disagree, or either found the sentence less than fully
    supported), the rest from sentences every setting called supported. The "disagree" stratum means hard here. Same return
    shape as calibration.select_sample."""
    per_setting = [unit_verdicts(s) for s in scores_list]
    keys = [k for k in per_setting[0] if all(k in v for v in per_setting)]
    # a hard case: the settings disagree, or any of them found the sentence less than fully supported
    strata = {k: DISAGREE if len({v[k] for v in per_setting}) > 1 or any(v[k] != "supported" for v in per_setting) else AGREE
              for k in keys}
    population = Counter(strata.values())
    rng = random.Random(seed)
    disagree = [k for k in keys if strata[k] == DISAGREE]
    agree = [k for k in keys if strata[k] == AGREE]
    n_disagree = min(len(disagree), round(n * share_disagree))
    n_agree = min(len(agree), n - n_disagree)
    n_disagree = min(len(disagree), n - n_agree)
    picks = rng.sample(disagree, n_disagree) + rng.sample(agree, n_agree)
    rng.shuffle(picks)
    return {"picks": picks, "strata": {k: strata[k] for k in picks}, "population": dict(population)}


def unit_for(response: TargetResponse, index: int) -> dict:
    return citations.claim_units(response.answer, response.citations)[index - 1]


def sheet_data(run: dict, golden: dict, sample: dict) -> dict:
    """What a labeller sees for each picked sentence: the question, the whole answer for context, the statement, and the
    excerpts of the sources cited for it. Nothing from the judge."""
    items = {i["id"]: i for i in golden["items"]}
    records = {r["item_id"]: r for r in run["records"] if r["repeat"] == 1}
    cards = []
    for key in sample["picks"]:
        item_id, index = key.rsplit("#", 1)
        record = records[item_id]
        response = TargetResponse.from_dict(record["response"])
        unit = unit_for(response, int(index))
        blocks = history_block(record.get("history", [])) + [
            {"label": "Question", "text": items[item_id]["question"]},
            {"label": "The whole answer (for context)", "text": response.answer},
            {"label": "The statement to check", "text": unit["sentence"], "css": "answer"}]
        cards.append({
            "id": key, "stratum": sample["strata"][key], "blocks": blocks,
            "groups": [{"dim": DIM, "title": "Do the cited sources support this statement?",
                        "hint": "Use only the sources listed below.", "options": options_for("faithfulness")}],
            "details": {"summary": "Sources cited for this statement", "open": True,
                        "items": [{"head": f"[{n}]", "text": text} for n, text in unit["sources"]]}})
    return {"labels_version": LABELS_VERSION, "kind": "citations", "title": "Label the citations", "rules": RULES,
            "run_id": run["run_id"], "golden_version": run["golden"]["golden_version"], "golden_hash": run["golden"]["hash"],
            "population": sample["population"], "cards": cards}
