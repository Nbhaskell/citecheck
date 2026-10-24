"""Calibration: how often the judge agrees with hand labels.

The judge is a model, so its verdicts are only as good as its agreement with a person reading the same answer. This module
draws a sample of answers for hand labelling, reads the labels back, and measures agreement.

Sampling is not random. Answers where two judge settings disagree are the most informative to label, so the sample takes
most of them and fills the rest from answers where the settings agree. Each labelled item records its stratum and the size
of that stratum in the full run, so agreement can also be reported weighted back to the whole run (an estimate, not a
measurement: the sample is small). Labels never show the judge's verdicts, so the labeller is not anchored by them.

Labels use the judge's own vocabulary (judge/prompts.py), so a label and a verdict are directly comparable:
    abstention    abstained / answered / partly_answered
    faithfulness  supported / partly_supported / unsupported   (not labelled when the answer abstained)
    correctness   correct / partly_correct / incorrect         (only for questions the corpus answers)
"""
import json
import random
from collections import Counter
from pathlib import Path

from .judge import prompts
from .models import TargetResponse

LABELS_VERSION = 1
DIMENSIONS = ("abstention", "faithfulness", "correctness")
VOCAB = {"abstention": prompts.ABSTENTION, "faithfulness": prompts.FAITHFULNESS, "correctness": prompts.CORRECTNESS}
AGREE, DISAGREE = "agree", "disagree"


class LabelsError(Exception):
    pass


def verdicts_by_item(scores: dict) -> dict:
    """item_id -> {dimension: verdict} for the judged answers of a scores file (first repeat only)."""
    out = {}
    for row in scores["items"]:
        if row["judged"] is None or row["item_id"] in out:
            continue
        out[row["item_id"]] = {d: v["verdict"] for d, v in row["judged"].items()}
    return out


def settings_disagree(per_setting: list[dict], item_id: str) -> bool:
    """True when any dimension has different verdicts under the given judge settings."""
    return any(len({v.get(item_id, {}).get(d) for v in per_setting}) > 1 for d in DIMENSIONS)


def select_sample(scores_list: list[dict], items: dict, n: int = 36, seed: int = 0, share_disagree: float = 0.65) -> dict:
    """Pick n answers to label. Returns {"picks": [item ids in shuffled order], "strata": {id: stratum},
    "population": {stratum: count}}."""
    per_setting = [verdicts_by_item(s) for s in scores_list]
    ids = [i for i in items if all(i in v for v in per_setting)]
    strata = {i: DISAGREE if settings_disagree(per_setting, i) else AGREE for i in ids}
    population = Counter(strata.values())
    rng = random.Random(seed)

    disagree = [i for i in ids if strata[i] == DISAGREE]
    agree = [i for i in ids if strata[i] == AGREE]
    n_disagree = min(len(disagree), round(n * share_disagree))
    n_agree = min(len(agree), n - n_disagree)
    n_disagree = min(len(disagree), n - n_agree)  # hand back the slack if the agreeing stratum is small
    picks = rng.sample(disagree, n_disagree)
    # answers the corpus cannot answer are rare; make sure some of the agreeing ones are in the sample
    unanswerable = [i for i in agree if items[i]["expected_abstain"]]
    keep = rng.sample(unanswerable, min(len(unanswerable), max(2, n_agree // 6), n_agree))
    rest = [i for i in agree if i not in keep]
    picks += keep + rng.sample(rest, n_agree - len(keep))
    rng.shuffle(picks)
    return {"picks": picks, "strata": {i: strata[i] for i in picks}, "population": dict(population)}


def sheet_data(run: dict, golden: dict, sample: dict) -> dict:
    """Everything a labeller needs to see about each picked answer, and nothing from the judge."""
    items = {i["id"]: i for i in golden["items"]}
    records = {r["item_id"]: r for r in run["records"] if r["repeat"] == 1}
    cards = []
    for item_id in sample["picks"]:
        item, record = items[item_id], records[item_id]
        response = TargetResponse.from_dict(record["response"])
        cards.append({
            "id": item_id, "question": item["question"], "history": record.get("history", []),
            "reference_answer": item.get("reference_answer", ""), "answerable": not item["expected_abstain"],
            "answer": response.answer,
            "passages": [{"rank": c.rank, "doc": c.doc_id, "section": c.section, "text": c.text} for c in response.retrieved],
            "stratum": sample["strata"][item_id]})
    return {"labels_version": LABELS_VERSION, "run_id": run["run_id"],
            "golden_version": run["golden"]["golden_version"], "golden_hash": run["golden"]["hash"],
            "population": sample["population"], "cards": cards}


def load_labels(path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = []
    if data.get("labels_version") != LABELS_VERSION:
        problems.append(f"labels_version is {data.get('labels_version')!r}, expected {LABELS_VERSION}")
    for item_id, entry in data.get("items", {}).items():
        for dim in DIMENSIONS:
            value = entry.get(dim)
            if value is not None and value not in VOCAB[dim]:
                problems.append(f"{item_id}: {dim} label {value!r} is not one of {list(VOCAB[dim])}")
        if entry.get("stratum") not in (AGREE, DISAGREE):
            problems.append(f"{item_id}: stratum must be {AGREE!r} or {DISAGREE!r}")
    if problems:
        raise LabelsError("; ".join(problems))
    return data


def cohens_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Agreement beyond chance between two raters. None when chance agreement is already perfect (one label only)."""
    n = len(pairs)
    if n == 0:
        return None
    observed = sum(a == b for a, b in pairs) / n
    first, second = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(first[label] * second[label] for label in first) / (n * n)
    return None if expected == 1 else round((observed - expected) / (1 - expected), 3)


def agreement(labels: dict, scores: dict) -> dict:
    """Judge vs human, per dimension, for one scores file."""
    verdicts = verdicts_by_item(scores)
    if scores["run_id"] != labels["run_id"]:
        raise LabelsError(f"labels are for run {labels['run_id']}, scores are for run {scores['run_id']}")
    entries = labels["items"]
    sampled = Counter(e["stratum"] for e in entries.values())
    weight = {s: labels["population"].get(s, 0) / sampled[s] for s in sampled}

    result = {"judge": scores["config"]["judge"], "dimensions": {}}
    for dim in DIMENSIONS:
        rows = [(item_id, e[dim], verdicts.get(item_id, {}).get(dim), weight[e["stratum"]])
                for item_id, e in entries.items() if e.get(dim) is not None]
        both = [(i, human, judge, w) for i, human, judge, w in rows if judge is not None]
        pairs = [(human, judge) for _, human, judge, _ in both]
        top = VOCAB[dim][0]  # supported / correct / abstained
        total_w = sum(w for *_, w in both)
        result["dimensions"][dim] = {
            "n": len(both),
            "missing_judge_verdict": len(rows) - len(both),
            "agree": sum(h == j for h, j in pairs),
            "agreement": None if not both else round(sum(h == j for h, j in pairs) / len(both), 3),
            "weighted_agreement": None if not both else round(sum(w for _, h, j, w in both if h == j) / total_w, 3),
            "kappa": cohens_kappa(pairs),
            "top_label_agreement": None if not both else round(sum((h == top) == (j == top) for h, j in pairs) / len(both), 3),
            "confusion": {f"{h} -> {j}": c for (h, j), c in sorted(Counter(pairs).items())},
            "disagreements": [{"item_id": i, "human": h, "judge": j} for i, h, j, _ in both if h != j],
        }
    return result


def format_agreement(label_data: dict, results: list[dict]) -> str:
    sampled = Counter(e["stratum"] for e in label_data["items"].values())
    lines = [f"run {label_data['run_id']}  |  golden {label_data['golden_version']}  |  {len(label_data['items'])} labelled "
             f"answers ({sampled.get(DISAGREE, 0)} where judge settings disagreed, {sampled.get(AGREE, 0)} where they agreed)",
             "The sample leans toward hard cases. 'weighted' re-weights the two groups to their size in the full run; "
             "it is an estimate from a small sample."]
    for result in results:
        judge = result["judge"]
        lines += ["", f"judge: {judge['model']}, thinking {'on' if judge['think'] else 'off'}, prompt v{judge['prompt_version']}",
                  f"{'':<14}{'n':>4}{'agree':>7}{'agreement':>11}{'weighted':>10}{'kappa':>8}{'top label':>11}"]
        for dim, d in result["dimensions"].items():
            fmt = lambda x: "-" if x is None else f"{x:.3f}"
            lines.append(f"{dim:<14}{d['n']:>4}{d['agree']:>7}{fmt(d['agreement']):>11}{fmt(d['weighted_agreement']):>10}"
                         f"{fmt(d['kappa']):>8}{fmt(d['top_label_agreement']):>11}")
        for dim, d in result["dimensions"].items():
            if d["disagreements"]:
                lines.append(f"  {dim} disagreements (human -> judge): " +
                             ", ".join(f"{x['item_id']} ({x['human']} -> {x['judge']})" for x in d["disagreements"]))
    lines += ["", "agreement = share of labels the judge matched exactly; kappa = agreement beyond chance (1 = perfect, "
                  "0 = no better than chance); top label = agreement on supported / correct / abstained versus anything else."]
    return "\n".join(lines)
