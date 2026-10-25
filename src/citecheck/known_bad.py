"""Known-bad check: does the judge notice answers that are wrong on purpose?

Hand labels only show whether the judge agrees on answers that happen to be good. This check starts from answers that
were labelled both supported and correct, damages each in a known way, and counts how often the judge flags the damage:

    number_changed   the first price or number in the answer is replaced by one that appears in none of the passages
    yes_no_flipped   a leading "Yes" becomes "No" (or the reverse), leaving the rest of the sentence as it was
    claim_added      a plausible sentence the documents never state is appended
    wrong_answer     the answer is replaced by the answer to a different question
    declined         the answer is replaced by a bare refusal ("does not know")

The unchanged answers are judged too, as a control: the share of them the judge flags is its false-alarm rate.
Everything here is deterministic, so a run can be repeated.
"""
import dataclasses
import re
from collections import Counter

from .models import TargetResponse

KINDS = ("number_changed", "yes_no_flipped", "claim_added", "wrong_answer", "declined")
# which verdicts each kind of damage should move away from the best label
EXPECTED = {
    "number_changed": ("faithfulness", "correctness"),
    "yes_no_flipped": ("faithfulness", "correctness"),
    "claim_added": ("faithfulness",),
    "wrong_answer": ("faithfulness", "correctness"),
    "declined": ("abstention", "correctness"),
}
BEST = {"abstention": "answered", "faithfulness": "supported", "correctness": "correct"}
# the label that means "caught for certain": declined, unsupported, incorrect
WORST = {"abstention": "abstained", "faithfulness": "unsupported", "correctness": "incorrect"}

INVENTED = (
    "Walk-ins without a reservation are always welcome on weekends.",
    "Every dog receives a free birthday treat on its birthday.",
    "A veterinarian is on site during all opening hours.",
    "Dogs under 1 year old are charged a reduced rate of $40.",
    "Webcams in every play area let owners watch live.",
)
NUMBER = re.compile(r"\$\d[\d,]*(?:\.\d+)?|\b\d+(?:\.\d+)?\b")


def change_number(answer: str, passages: list[str]) -> str | None:
    """Replace the first money amount (else the first number) with one that no passage contains."""
    matches = list(NUMBER.finditer(answer))
    match = next((m for m in matches if m.group(0).startswith("$")), None) or (matches[0] if matches else None)
    if match is None:
        return None
    text, money = match.group(0), match.group(0).startswith("$")
    value = float(text.lstrip("$").replace(",", ""))
    corpus = " ".join(passages)
    for step in (17, 23, 31, 47, 59):
        candidate = value + step if money else float(int(value) + step)
        shown = f"${candidate:,.2f}" if money and "." in text else (f"${candidate:,.0f}" if money else f"{candidate:.0f}")
        if shown.lstrip("$") not in corpus:
            return answer[:match.start()] + shown + answer[match.end():]
    return None


def flip_yes_no(answer: str) -> str | None:
    match = re.match(r"(Yes|No)\b", answer)
    if not match:
        return None
    return ("No" if match.group(1) == "Yes" else "Yes") + answer[match.end():]


def build_cases(candidates: list[dict]) -> list[dict]:
    """candidates: [{"item_id", "answer", "passages"}] for answers known to be good. Returns the damaged variants, each as
    {"item_id", "kind", "answer"}; a kind that does not apply to an answer (no number, no leading yes or no) is skipped."""
    cases = []
    for index, c in enumerate(candidates):
        other = candidates[(index + 1) % len(candidates)]
        made = {
            "number_changed": change_number(c["answer"], c["passages"]),
            "yes_no_flipped": flip_yes_no(c["answer"]),
            "claim_added": c["answer"].rstrip() + " " + INVENTED[index % len(INVENTED)],
            "wrong_answer": other["answer"] if other["item_id"] != c["item_id"] else None,
            "declined": "I don't know.",
        }
        cases += [{"item_id": c["item_id"], "kind": kind, "answer": text} for kind, text in made.items() if text]
    return cases


def judge_cases(judge, items: dict, responses: dict, histories: dict, cases: list[dict], progress=None) -> list[dict]:
    """The judge's verdicts for every case, plus the unchanged answers as a control (kind "control")."""
    originals = [{"item_id": i, "kind": "control", "answer": responses[i].answer} for i in dict.fromkeys(c["item_id"] for c in cases)]
    results = []
    for number, case in enumerate(originals + cases, 1):
        response = dataclasses.replace(responses[case["item_id"]], answer=case["answer"])
        judged = judge.judge_item(items[case["item_id"]], response, history=histories[case["item_id"]])
        results.append({**case, "verdicts": {d: v["verdict"] for d, v in judged.items()},
                        "errors": [v["error"] for v in judged.values() if v["error"]]})
        if progress:
            progress(f"{number}/{len(originals) + len(cases)} {case['kind']} {case['item_id']}")
    return results


def summarize(results: list[dict]) -> dict:
    """Per kind: how many cases, and per dimension how many were flagged (verdict not the best label) and how many were
    flagged for certain (the worst label). Cases the judge failed on are counted apart and left out."""
    summary = {}
    for kind in ("control",) + KINDS:
        rows = [r for r in results if r["kind"] == kind]
        entry = {"n": len(rows), "judge_errors": sum(bool(r["errors"]) for r in rows), "dimensions": {}}
        for dim in (("faithfulness", "correctness") if kind == "control" else EXPECTED[kind]):
            verdicts = [r["verdicts"].get(dim) for r in rows if not r["errors"]]
            if dim == "faithfulness":  # an abstained answer has no faithfulness verdict, which is not a miss
                verdicts = [v for v in verdicts if v is not None]
            counts = Counter(verdicts)
            entry["dimensions"][dim] = {"n": len(verdicts), "flagged": sum(v != BEST[dim] for v in verdicts),
                                        "flagged_for_certain": counts[WORST[dim]]}
        summary[kind] = entry
    return summary


def format_report(summary: dict, judge_config: dict) -> str:
    lines = [f"known-bad check, judge {judge_config['model']}, thinking {'on' if judge_config['think'] else 'off'}, "
             f"prompt v{judge_config['prompt_version']}",
             "Answers labelled supported and correct were damaged on purpose; 'flagged' means the verdict was not the best "
             "one, 'certain' means the worst one (declined / unsupported / incorrect).", ""]
    control = summary["control"]
    lines.append(f"control: {control['n']} unchanged answers (false alarms)  " +
                 ", ".join(f"{d} flagged {v['flagged']}/{v['n']}" for d, v in control["dimensions"].items()))
    lines += ["", f"{'damage':<16}{'n':>4}  {'dimension':<14}{'flagged':>9}{'certain':>9}"]
    for kind in KINDS:
        entry = summary[kind]
        for position, (dim, v) in enumerate(entry["dimensions"].items()):
            flagged = f"{v['flagged']}/{v['n']}"
            certain = f"{v['flagged_for_certain']}/{v['n']}"
            lines.append(f"{kind if position == 0 else '':<16}{entry['n'] if position == 0 else '':>4}  {dim:<14}{flagged:>9}{certain:>9}")
    errors = sum(e["judge_errors"] for e in summary.values())
    if errors:
        lines.append(f"\n{errors} case(s) had a judge failure and are left out")
    return "\n".join(lines)


def candidates_from(run: dict, labels: dict) -> tuple[list[dict], dict, dict]:
    """The answers labelled both supported and correct, with what the judge needs to see them again."""
    records = {r["item_id"]: r for r in run["records"] if r["repeat"] == 1}
    good = [i for i, e in labels["items"].items()
            if e.get("faithfulness") == "supported" and e.get("correctness") == "correct"]
    responses = {i: TargetResponse.from_dict(records[i]["response"]) for i in good}
    histories = {i: records[i].get("history", []) for i in good}
    candidates = [{"item_id": i, "answer": responses[i].answer, "passages": [c.text for c in responses[i].retrieved]}
                  for i in sorted(good)]
    return candidates, responses, histories

