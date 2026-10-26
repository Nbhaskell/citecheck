"""Known-bad check for citation support: does the judge notice a sentence whose cited sources do not back it?

Starts from cited sentences labelled supported by hand (see citation_calibration.py), damages each in a known way and counts
how often the judge flags it (any verdict other than `supported`). The unchanged sentences are judged too, as a control:
the share flagged is the false-alarm rate.

    claim_changed   the first price or number in the sentence is replaced by one that appears in none of its sources
    source_swapped  the sentence keeps its wording but is shown the sources cited for a different sentence
    claim_added     a plausible clause the sources never state is appended

Each case is judged on the sentence with its markers removed, so the control and the damaged cases read alike.
"""
import re
from collections import Counter

from .known_bad import INVENTED, change_number
from .metrics.citations import MARKER
from .models import TargetResponse

KINDS = ("claim_changed", "source_swapped", "claim_added")


def clean(sentence: str) -> str:
    return re.sub(r"\s+", " ", MARKER.sub("", sentence)).replace(" .", ".").strip()


def candidates_from(run: dict, golden: dict, labels: dict) -> list[dict]:
    """The cited sentences labelled supported, each with its question, history and cited (number, excerpt) pairs."""
    from .citation_calibration import unit_for
    items = {i["id"]: i for i in golden["items"]}
    records = {r["item_id"]: r for r in run["records"] if r["repeat"] == 1}
    found = []
    for key, entry in labels["items"].items():
        if entry.get("citation_support") != "supported":
            continue
        item_id, index = key.rsplit("#", 1)
        record = records[item_id]
        unit = unit_for(TargetResponse.from_dict(record["response"]), int(index))
        found.append({"key": key, "item_id": item_id, "question": items[item_id]["question"],
                      "history": record.get("history", []), "statement": clean(unit["sentence"]), "sources": unit["sources"]})
    return found


def build_cases(candidates: list[dict]) -> list[dict]:
    """Damaged variants of each candidate as {"key", "kind", "statement", "sources"}; a kind that does not apply is skipped."""
    cases = []
    for index, c in enumerate(candidates):
        other = next((o for o in candidates[index + 1:] + candidates[:index]
                      if o["item_id"] != c["item_id"] and o["sources"] != c["sources"]), None)
        texts = [text for _, text in c["sources"]]
        changed = change_number(c["statement"], texts)
        made = {
            "claim_changed": (changed, c["sources"]) if changed else None,
            "source_swapped": (c["statement"], other["sources"]) if other else None,
            "claim_added": (c["statement"].rstrip() + " " + INVENTED[index % len(INVENTED)], c["sources"]),
        }
        cases += [{"key": c["key"], "kind": kind, "statement": value[0], "sources": value[1]}
                  for kind, value in made.items() if value]
    return cases


def judge_cases(judge, candidates: list[dict], cases: list[dict], progress=None) -> list[dict]:
    by_key = {c["key"]: c for c in candidates}
    control = [{"key": c["key"], "kind": "control", "statement": c["statement"], "sources": c["sources"]} for c in candidates]
    results = []
    for number, case in enumerate(control + cases, 1):
        c = by_key[case["key"]]
        out = judge.verdict("citation", question=c["question"], statement=case["statement"], cited=case["sources"],
                            history=c["history"])
        results.append({"key": case["key"], "kind": case["kind"], "statement": case["statement"], "verdict": out["verdict"],
                        "error": out["error"]})
        if progress:
            progress(f"{number}/{len(control) + len(cases)} {case['kind']} {case['key']}")
    return results


def summarize(results: list[dict]) -> dict:
    summary = {}
    for kind in ("control",) + KINDS:
        rows = [r for r in results if r["kind"] == kind]
        verdicts = [r["verdict"] for r in rows if r["error"] is None]
        counts = Counter(verdicts)
        summary[kind] = {"n": len(rows), "judge_errors": len(rows) - len(verdicts),
                         "flagged": sum(v != "supported" for v in verdicts), "flagged_for_certain": counts["unsupported"]}
    return summary


def format_report(summary: dict, judge_config: dict) -> str:
    lines = [f"known-bad check for citation support, judge {judge_config['model']}, thinking "
             f"{'on' if judge_config['think'] else 'off'}, prompt v{judge_config['prompt_version']}",
             "Sentences labelled supported by hand were damaged on purpose; 'flagged' means the verdict was not supported, "
             "'certain' means it was unsupported.", ""]
    control = summary["control"]
    lines.append(f"control: {control['n']} unchanged sentences, flagged {control['flagged']}/{control['n'] - control['judge_errors']}"
                 " (false alarms)")
    lines += ["", f"{'damage':<16}{'n':>4}{'flagged':>9}{'certain':>9}"]
    for kind in KINDS:
        e = summary[kind]
        n = e["n"] - e["judge_errors"]
        lines.append(f"{kind:<16}{e['n']:>4}{str(e['flagged']) + '/' + str(n):>9}{str(e['flagged_for_certain']) + '/' + str(n):>9}")
    errors = sum(e["judge_errors"] for e in summary.values())
    if errors:
        lines.append(f"\n{errors} case(s) had a judge failure and are left out")
    return "\n".join(lines)
