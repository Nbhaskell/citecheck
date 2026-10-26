"""Review of reference answers by a person: the sheet that is filled in, and applying what it recorded.

A reference answer that was drafted by a model and never read by a person is a weak basis for the correctness score, so each one
is put in front of a person next to the passages it was built from, who marks it right as written, corrects it in place, or
says the question cannot be answered from the passages. Nothing is sent anywhere: the sheet is a local HTML file
(see calibration_sheet.py) and the result is a downloaded JSON file.

Applying a result changes two files that must agree, because the golden set is built from the questions file:

    golden/citewise_questions_v1.json   gets the corrected reference answers, a new version, and a `reference_review` record
    golden/citewise_filings_v1.json     gets the same corrected answers, the new version, and a notes sentence that says the
                                        answers were checked by hand

and writes a review record beside them (one entry per item). The golden set's hash changes, so runs asked from the earlier
version refuse to be scored against it; their answers are unchanged, so scoring them again with --ignore-golden-mismatch
re-judges correctness against the reviewed references. A result is refused, and nothing is written, when it is incomplete,
inconsistent, was made against another version of the golden set, or leaves a question marked unclear.
"""
import copy
import json
import re

from .runner import golden_hash

LABELS_VERSION = 1
KIND = "reference-review"
DIM = "review"
EDIT = "reference_answer"
OK, EDITED, UNCLEAR = "ok", "edited", "unclear"
OPTIONS = [
    (OK, "Right as written: correct and complete for the question, with nothing the passages do not support."),
    (EDITED, "Corrected in the box above: the text there is the answer to keep."),
    (UNCLEAR, "The question is unclear, or the passages do not settle it. Say why in the note."),
]
RULES = [
    "Check each reference answer against the passages shown under it, not against what is remembered. They are the stored "
    "filing text the question was built from.",
    "<b>Right as written</b>: the answer is correct and complete for the question and says nothing the passages do not support. "
    "Read the figures and dates against the passage; for a question that asks for a sum or a comparison, recompute it.",
    "<b>Corrected in the box</b>: edit the text in the box until it is right, then choose this option. The text left in the box "
    "is the one saved. Use full sentences, as the draft does.",
    "<b>Unclear</b>: the question has no single answer in the passages, or editing cannot fix it. The review cannot be applied "
    "until each of these has been rewritten or dropped in the questions file.",
    "A question marked as one the filings do not answer should have a reference that says the filings do not state it. The "
    "sheet shows no passages for it; the notes line says how it was checked.",
    "Progress is kept in this browser while working. Download the file at the end; it records which version of the question "
    "set it was made against.",
]


class ReviewError(Exception):
    pass


def keywords_text(groups: list) -> str:
    """The `answer_contains` groups as a sentence: every group must be met, by any one of its alternatives."""
    return "  AND  ".join(" or ".join(f"“{alternative}”" for alternative in group) for group in groups)


def passages_for(item: dict) -> list[dict]:
    """The evidence passages of an item, each once, with the key phrase(s) that found it."""
    found: dict[tuple, dict] = {}
    for fact in item["evidence"]:
        for passage in fact["passages"]:
            key = (passage["doc_id"], passage["text"])
            entry = found.setdefault(key, {"doc": passage["doc_id"], "section": passage.get("section") or "",
                                           "page": passage.get("page"), "text": passage["text"], "phrases": []})
            phrase = passage.get("anchor", fact["anchor"])
            if phrase not in entry["phrases"]:
                entry["phrases"].append(phrase)
    return list(found.values())


def sheet_data(golden: dict) -> dict:
    """What the sheet shows for every item of a golden set that has reference answers."""
    by_id = {item["id"]: item for item in golden["items"]}
    cards = []
    for item in golden["items"]:
        if "reference_answer" not in item:
            raise ReviewError(f"{item['id']} has no reference answer to review")
        blocks = []
        parent = by_id.get(item.get("follow_up_to"))
        if parent:
            blocks.append({"label": "Earlier in the conversation",
                           "text": f"{parent['question']}\n→ {parent['reference_answer']}"})
        blocks.append({"label": f"Question ({item['category']})", "text": item["question"]})
        if item.get("answer_contains"):
            blocks.append({"label": "The answer must contain", "text": keywords_text(item["answer_contains"])})
        if item.get("notes"):
            blocks.append({"label": "Notes on the question", "text": item["notes"]})
        passages = passages_for(item)
        if not passages:
            blocks.append({"label": "Passages", "text": "None. The stored filings are not expected to state this."})
        details = None
        if passages:
            details = {"summary": "The passages the question was built from", "open": True, "items": [
                {"head": " · ".join(part for part in (p["doc"], p["section"], "key phrase: " + "; ".join(p["phrases"])) if part),
                 "text": p["text"]} for p in passages]}
        cards.append({
            "id": item["id"], "stratum": item["category"], "blocks": blocks, "details": details,
            "edit": {"dim": EDIT, "text": item["reference_answer"],
                     "label": "Draft reference answer (edit it here if it needs a change)"},
            "groups": [{"dim": DIM, "title": "Is the reference answer right?",
                        "hint": "Compare it with the passages, not with memory.", "options": [list(o) for o in OPTIONS]}]})
    return {"labels_version": LABELS_VERSION, "kind": KIND, "run_id": golden["golden_version"],
            "golden_version": golden["golden_version"], "golden_hash": golden_hash(golden),
            "population": {"items": len(cards)}, "title": "Review the reference answers", "rules": RULES, "cards": cards,
            "intro": f"Question set {golden['golden_version']}"}


def check_result(result: dict, golden: dict) -> list[str]:
    """Everything wrong with a downloaded result, as sentences; empty when it can be applied."""
    if result.get("kind") != KIND:
        return [f"this is not a reference review (kind {result.get('kind')!r})"]
    if result.get("golden_hash") != golden_hash(golden):
        return [f"the review was made against {result.get('golden_version')}, not the question set at hand "
                f"({golden['golden_version']}); the reference answers may have changed since"]
    problems = []
    items = result.get("items", {})
    drafts = {item["id"]: item["reference_answer"] for item in golden["items"]}
    for item_id in drafts:
        entry = items.get(item_id)
        if entry is None or entry.get(DIM) is None:
            problems.append(f"{item_id}: not reviewed")
            continue
        text = (entry.get(EDIT) or "").strip()
        verdict = entry[DIM]
        if verdict not in (OK, EDITED, UNCLEAR):
            problems.append(f"{item_id}: unknown choice {verdict!r}")
        elif verdict == UNCLEAR:
            problems.append(f"{item_id}: marked unclear" + (f" ({entry['note']})" if entry.get("note") else "")
                            + "; rewrite or drop the question first")
        elif verdict == OK and text != drafts[item_id].strip():
            problems.append(f"{item_id}: marked right as written, but the text in the box was changed")
        elif verdict == EDITED and (not text or text == drafts[item_id].strip()):
            problems.append(f"{item_id}: marked corrected, but the box is empty or unchanged")
    problems += [f"{item_id}: not in the question set" for item_id in items if item_id not in drafts]
    return problems


def next_version(version: str) -> str:
    """citewise-filings-1.0.0 -> citewise-filings-1.1.0: reference answers changed, questions and evidence did not."""
    match = re.fullmatch(r"(.*-)(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise ReviewError(f"cannot read a version from {version!r}")
    head, major, minor, _ = match.groups()
    return f"{head}{major}.{int(minor) + 1}.0"


def review_clause(review: dict | None) -> str:
    """The notes sentence about reference answers, which the builder and the apply step both write."""
    if not review or not review.get("reviewed"):
        return "and have not yet been reviewed by a person."
    corrected = review["corrected"]
    return ("and then checked one by one by hand against the passages "
            + ("(none needed a change)." if corrected == 0 else f"({corrected} corrected)."))


def apply_review(result: dict, golden: dict, questions: dict, record_path: str) -> tuple[dict, dict, dict]:
    """The golden set, the questions file and the review record after applying a result that passed check_result."""
    problems = check_result(result, golden)
    if problems:
        raise ReviewError("the review cannot be applied:\n  " + "\n  ".join(problems))
    if "reference_review" in questions:
        raise ReviewError("the questions file already records a review; start from the unreviewed version")
    new_golden, new_questions = copy.deepcopy(golden), copy.deepcopy(questions)
    entries = {i: result["items"][i] for i in result["items"]}
    corrected, record_items = 0, []
    spec = {entry["id"]: entry for entry in new_questions["items"]}
    for item in new_golden["items"]:
        entry = entries[item["id"]]
        final = entry[EDIT].strip()
        record = {"id": item["id"], "review": entry[DIM], "reference_answer": final}
        if entry[DIM] == EDITED:
            corrected += 1
            record["draft"] = item["reference_answer"]
            item["reference_answer"] = final
            spec[item["id"]]["reference_answer"] = final
        if entry.get("note"):
            record["note"] = entry["note"].strip()
        record_items.append(record)
    version = next_version(golden["golden_version"])
    review = {"reviewed": True, "corrected": corrected, "record": record_path}
    old_clause, new_clause = review_clause(None), review_clause(review)
    if old_clause not in new_golden["notes"]:
        raise ReviewError("the golden set's notes do not say that the reference answers are unreviewed")
    new_golden["golden_version"] = new_questions["golden_version"] = version
    new_golden["notes"] = new_golden["notes"].replace(old_clause, new_clause)
    new_questions["reference_review"] = review
    record = {"record_version": 1, "golden_version_before": golden["golden_version"], "golden_version_after": version,
              "golden_hash_before": golden_hash(golden), "corrected": corrected, "items": record_items}
    return new_golden, new_questions, record


def dumps(data: dict, indent: int) -> str:
    return json.dumps(data, indent=indent, ensure_ascii=False) + "\n"
