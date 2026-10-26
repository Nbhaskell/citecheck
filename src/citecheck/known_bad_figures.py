"""Known-bad check for the figure-grounding check: does it notice a figure or a date that was changed on purpose?

The same damage the judge was tested with is applied again and the grounding check (metrics/figures.py) is run on each
damaged text. Two kinds of text are used, matching the two judge checks:

    answers   whole answers labelled supported and correct by hand (see known_bad.py), checked against the passages the
              target returned
    sentences cited sentences labelled supported by hand (see known_bad_citations.py), checked against their cited sources

Damage that makes a figure or a date appear in no source is what the check is for, and it is close to detecting its own
definition, so those rows say little by themselves; they show the false-alarm rate and what the lenient tier gives away.
`figure_swapped` is the damage the check cannot see by design: the first figure is replaced by a different figure that does
appear in the sources, as when an answer reads off the wrong number of a passage. The judge is the only check that can notice
it, so it is run on those cases (`--judge`). The other kinds are included so the table shows what the check does not see (a
flipped yes or no, a bare refusal) and what it sees by accident (an invented sentence that carries a figure).

The unchanged texts are checked too, as a control: the share flagged is the false-alarm rate. When the judge's results for the
same cases are given, each case also carries whether the judge flagged it (any verdict but the best one), which gives the cases
the check alone, the judge alone, and either of them catches.
"""
import json
import re

from . import known_bad, known_bad_citations
from .metrics import figures

ANSWER_KINDS = ("number_changed", "figure_changed", "date_changed", "figure_swapped", "claim_added", "wrong_answer",
                "yes_no_flipped", "declined")
SENTENCE_KINDS = ("figure_changed", "date_changed", "figure_swapped", "source_swapped", "claim_added")
# the verdicts the judge should move for each kind of whole-answer damage
EXPECTED = {**known_bad.EXPECTED, "figure_changed": ("faithfulness", "correctness"), "date_changed": ("faithfulness", "correctness"),
            "figure_swapped": ("faithfulness", "correctness")}


def swap_figure(text: str, sources: list[str]) -> str | None:
    """Replace the first money amount or figure that is not part of a date with the nearest different figure that the
    sources do contain and the text does not; None when the text has no such figure or the sources offer no other."""
    own = {k for f in figures.extract(text) for k in f["keys"]}
    offered = sorted({f["keys"][0] for s in sources for f in figures.extract(s) if f["kind"] == "number"} - own - {0.0, 1.0})
    days = {m.start(1) for m in known_bad_citations.DATE.finditer(text)}
    for match in known_bad_citations.FIGURE.finditer(text):
        shown = match.group(0)
        digits = shown.lstrip("$").replace(",", "")
        if match.start() in days or re.fullmatch(r"(19|20)\d\d", digits) or not offered:
            continue
        value = float(digits)
        nearest = min(offered, key=lambda v: (abs(v - value), v))
        places = len(digits.split(".")[1]) if "." in digits else 0
        number = f"{nearest:,.{places}f}" if "," in shown or shown.startswith("$") else f"{nearest:.{places}f}"
        return text[:match.start()] + ("$" if shown.startswith("$") else "") + number + text[match.end():]
    return None


def swapped_answers(candidates: list[dict]) -> list[dict]:
    cases = []
    for c in candidates:
        text = swap_figure(c["answer"], c["passages"])
        if text:
            cases.append({"item_id": c["item_id"], "kind": "figure_swapped", "answer": text})
    return cases


def swapped_sentences(candidates: list[dict]) -> list[dict]:
    cases = []
    for c in candidates:
        text = swap_figure(c["statement"], [t for _, t in c["sources"]])
        if text:
            cases.append({"key": c["key"], "kind": "figure_swapped", "statement": text, "sources": c["sources"]})
    return cases


def evaluate_answers(run: dict, golden: dict, labels: dict) -> list[dict]:
    """The check on every damaged variant of the answers labelled supported and correct, and on the unchanged answers."""
    items = {i["id"]: i for i in golden["items"]}
    candidates, responses, histories = known_bad.candidates_from(run, labels)
    by_id = {c["item_id"]: c for c in candidates}
    texts = [{"item_id": c["item_id"], "kind": "control", "text": c["answer"]} for c in candidates]
    texts += [{"item_id": c["item_id"], "kind": c["kind"], "text": c["answer"]}
              for c in known_bad.build_cases(candidates) + swapped_answers(candidates)]
    for c in candidates:
        for kind, text in (("figure_changed", known_bad_citations.change_figure(c["answer"], c["passages"])),
                           ("date_changed", known_bad_citations.change_date(c["answer"]))):
            if text:
                texts.append({"item_id": c["item_id"], "kind": kind, "text": text})
    results = []
    for case in texts:
        context = [items[case["item_id"]]["question"]] + [turn["content"] for turn in histories[case["item_id"]]]
        results.append({"item_id": case["item_id"], "kind": case["kind"], "text": case["text"],
                        **figures.check(case["text"], by_id[case["item_id"]]["passages"], context)})
    return results


def evaluate_sentences(run: dict, golden: dict, labels: dict) -> list[dict]:
    """The check on every damaged variant of the cited sentences labelled supported, and on the unchanged sentences."""
    candidates = known_bad_citations.candidates_from(run, golden, labels)
    by_key = {c["key"]: c for c in candidates}
    texts = [{"key": c["key"], "kind": "control", "text": c["statement"], "sources": c["sources"]} for c in candidates]
    texts += [{"key": c["key"], "kind": c["kind"], "text": c["statement"], "sources": c["sources"]}
              for c in known_bad_citations.build_cases(candidates) + swapped_sentences(candidates)]
    results = []
    for case in texts:
        c = by_key[case["key"]]
        context = [c["question"]] + [turn["content"] for turn in c["history"]]
        results.append({"key": case["key"], "kind": case["kind"], "text": case["text"],
                        **figures.check(case["text"], [text for _, text in case["sources"]], context)})
    return results


def judge_swapped_answers(judge, run: dict, golden: dict, labels: dict, progress=None) -> dict:
    """The judge's flags for the figure_swapped answers, in the form judge_flags() returns."""
    candidates, responses, histories = known_bad.candidates_from(run, labels)
    results = known_bad.judge_cases(judge, {i["id"]: i for i in golden["items"]}, responses, histories,
                                    swapped_answers(candidates), progress)
    return judge_flags({"cases": [r for r in results if r["kind"] == "figure_swapped"]})


def judge_swapped_sentences(judge, run: dict, golden: dict, labels: dict, progress=None) -> dict:
    candidates = known_bad_citations.candidates_from(run, golden, labels)
    results = known_bad_citations.judge_cases(judge, candidates, swapped_sentences(candidates), progress)
    return judge_flags({"cases": [r for r in results if r["kind"] == "figure_swapped"]})


def judge_flags(data: dict) -> dict:
    """{(case id, kind): the judge flagged it} from a saved `known-bad` result file; cases the judge failed on are left out."""
    flags = {}
    for case in data["cases"]:
        if "verdicts" in case:  # whole answers: any dimension the damage should move
            if case["errors"]:
                continue
            dims = ("faithfulness", "correctness") if case["kind"] == "control" else EXPECTED[case["kind"]]
            flags[(case["item_id"], case["kind"])] = any(
                case["verdicts"].get(d) not in (None, known_bad.BEST[d]) for d in dims)
        elif case["error"] is None:  # cited sentences
            flags[(case["key"], case["kind"])] = case["verdict"] != "supported"
    return flags


def summarize(results: list[dict], kinds: tuple, flags: dict | None = None) -> dict:
    summary = {}
    for kind in ("control",) + kinds:
        rows = [r for r in results if r["kind"] == kind]
        entry = {"n": len(rows), "with_figures": sum(bool(r["n"]) for r in rows),
                 "not_found": sum(bool(r["ungrounded"]) for r in rows), "underived": sum(bool(r["underived"]) for r in rows),
                 "judge": None}
        if flags:
            paired = [(flags[(r.get("item_id") or r["key"], kind)], r) for r in rows if (r.get("item_id") or r["key"], kind) in flags]
            if paired:
                entry["judge"] = {"n": len(paired), "flagged": sum(j for j, _ in paired),
                                  "check_flagged": sum(bool(r["underived"]) for _, r in paired),
                                  "either": sum(j or bool(r["underived"]) for j, r in paired)}
        summary[kind] = entry
    return summary


def format_report(summary: dict, label: str) -> str:
    lines = [f"known-bad check of figure grounding, {label}",
             "Texts labelled good by hand were damaged on purpose. 'not found' counts texts with a figure that appears in no "
             "source, question or earlier turn; 'underived' also allows a sum, difference, product or quotient of two "
             "numbers that appear. 'judge' is how many the judge flagged (cases it was run on); 'either' is the judge or the "
             "underived count.", ""]
    lines.append(f"{'damage':<24}{'n':>4}{'with fig.':>10}{'not found':>11}{'underived':>11}{'judge':>9}{'either':>8}")
    for kind, e in summary.items():
        judge = "-" if e["judge"] is None else f"{e['judge']['flagged']}/{e['judge']['n']}"
        either = "-" if e["judge"] is None else f"{e['judge']['either']}/{e['judge']['n']}"
        name = "control (false alarms)" if kind == "control" else kind
        lines.append(f"{name:<24}{e['n']:>4}{e['with_figures']:>10}{e['not_found']:>11}{e['underived']:>11}{judge:>9}{either:>8}")
    return "\n".join(lines)


def save(path, results: list[dict], summary: dict, run_id: str, scope: str, judge_file: str | None,
         judge_config: dict | None = None) -> None:
    """judge_config is the judge that was run on the figure_swapped cases, when one was."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"scope": scope, "run_id": run_id, "judge_results": judge_file, "judge": judge_config,
                            "summary": summary, "cases": results}, indent=1, ensure_ascii=False) + "\n")
