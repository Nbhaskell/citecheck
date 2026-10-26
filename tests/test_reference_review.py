import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from citecheck import calibration_sheet, cli, golden, reference_review
from citecheck.reference_review import EDITED, OK, UNCLEAR, ReviewError

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "golden" / "citewise_filings_v1.json"
QUESTIONS = ROOT / "golden" / "citewise_questions_v1.json"


def builder():
    spec = importlib.util.spec_from_file_location("build_citewise_golden", ROOT / "tools" / "build_citewise_golden.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def data():
    return golden.load_json(GOLDEN)


@pytest.fixture
def questions():
    return json.loads(QUESTIONS.read_text(encoding="utf-8"))


def result_for(data, edits=None, unclear=None, skip=None, notes=None):
    """A downloaded review of `data`: every item right as written, except those named."""
    edits, unclear, skip, notes = edits or {}, unclear or (), skip or (), notes or {}
    items = {}
    for item in data["items"]:
        entry = {"review": OK, "reference_answer": item["reference_answer"], "note": notes.get(item["id"], ""),
                 "stratum": item["category"]}
        if item["id"] in edits:
            entry.update(review=EDITED, reference_answer=edits[item["id"]])
        if item["id"] in unclear:
            entry["review"] = UNCLEAR
        if item["id"] in skip:
            entry["review"] = None
        items[item["id"]] = entry
    return {"labels_version": 1, "kind": "reference-review", "run_id": data["golden_version"],
            "golden_version": data["golden_version"], "golden_hash": reference_review.golden_hash(data),
            "population": {"items": len(items)}, "items": items}


# --- the sheet ---------------------------------------------------------------------------------------------------

def test_the_sheet_has_a_card_for_every_item_with_its_draft_and_passages(data):
    sheet = reference_review.sheet_data(data)
    assert sheet["kind"] == "reference-review" and sheet["golden_hash"] == reference_review.golden_hash(data)
    assert [c["id"] for c in sheet["cards"]] == [i["id"] for i in data["items"]]
    card = sheet["cards"][0]
    assert card["edit"]["text"] == data["items"][0]["reference_answer"]
    assert card["details"]["open"] and card["details"]["items"][0]["text"]
    assert [g["dim"] for g in card["groups"]] == ["review"]
    assert [value for value, _ in card["groups"][0]["options"]] == [OK, EDITED, UNCLEAR]


def test_a_follow_up_shows_its_parent_and_an_unanswerable_item_says_it_has_no_passages(data):
    cards = {c["id"]: c for c in reference_review.sheet_data(data)["cards"]}
    follow = next(i for i in data["items"] if i.get("follow_up_to"))
    labels = {b["label"]: b["text"] for b in cards[follow["id"]]["blocks"]}
    assert follow["follow_up_to"] and "→" in labels["Earlier in the conversation"]
    unanswerable = next(i for i in data["items"] if i["category"] == "unanswerable")
    assert cards[unanswerable["id"]]["details"] is None
    assert any(b["label"] == "Passages" and b["text"].startswith("None") for b in cards[unanswerable["id"]]["blocks"])


def test_a_passage_shared_by_two_facts_is_shown_once_with_both_key_phrases():
    item = {"evidence": [
        {"anchor": "alpha", "passages": [{"doc_id": "D", "section": "S", "page": None, "text": "alpha and beta"}]},
        {"anchor": "beta", "passages": [{"doc_id": "D", "section": "S", "page": None, "text": "alpha and beta"},
                                        {"doc_id": "E", "section": "", "page": None, "text": "other", "anchor": "other"}]}]}
    found = reference_review.passages_for(item)
    assert [(p["doc"], p["phrases"]) for p in found] == [("D", ["alpha", "beta"]), ("E", ["other"])]


def test_answer_keywords_read_as_every_group_met_by_any_alternative():
    assert reference_review.keywords_text([["31,000"], ["Santa Clara", "San Jose"]]) == "“31,000”  AND  “Santa Clara” or “San Jose”"


def test_the_rendered_sheet_has_the_edit_box_and_cannot_be_broken_by_passage_text(data):
    sheet = reference_review.sheet_data(data)
    sheet["cards"][0]["details"]["items"][0]["text"] = "a </script><script>alert(1)</script> passage"
    page = calibration_sheet.render(sheet)
    assert "data-edit" in page and "Put the original text back" in page and "Question set citewise-filings-1.0.0" in page
    assert page.count("</script>") == 2  # the data block and the page's own script; the passage cannot close either


# --- checking a result -------------------------------------------------------------------------------------------

def test_a_complete_consistent_review_has_no_problems(data):
    assert reference_review.check_result(result_for(data, edits={"amd-hq": "AMD is headquartered in Santa Clara, California."}), data) == []


def test_unreviewed_unclear_and_inconsistent_items_are_each_reported(data):
    ids = [i["id"] for i in data["items"]]
    result = result_for(data, edits={ids[0]: data["items"][0]["reference_answer"]}, unclear=[ids[1]], skip=[ids[2]],
                        notes={ids[1]: "two readings"})
    result["items"][ids[3]]["reference_answer"] = "something else"  # marked right as written, but changed
    problems = " | ".join(reference_review.check_result(result, data))
    assert f"{ids[0]}: marked corrected, but the box is empty or unchanged" in problems
    assert f"{ids[1]}: marked unclear (two readings); rewrite or drop the question first" in problems
    assert f"{ids[2]}: not reviewed" in problems
    assert f"{ids[3]}: marked right as written, but the text in the box was changed" in problems


def test_a_review_of_another_version_or_kind_is_refused(data):
    stale = result_for(data)
    stale["golden_hash"] = "0" * 64
    assert "made against" in reference_review.check_result(stale, data)[0]
    labels = result_for(data)
    labels["kind"] = "answers"
    assert "not a reference review" in reference_review.check_result(labels, data)[0]


def test_an_item_that_is_not_in_the_question_set_is_reported(data):
    result = result_for(data)
    result["items"]["no-such-item"] = {"review": OK, "reference_answer": "x"}
    assert reference_review.check_result(result, data) == ["no-such-item: not in the question set"]


# --- applying it -------------------------------------------------------------------------------------------------

def test_versions_move_the_minor_number_only():
    assert reference_review.next_version("citewise-filings-1.0.0") == "citewise-filings-1.1.0"
    assert reference_review.next_version("x-2.3.4") == "x-2.4.0"
    with pytest.raises(ReviewError):
        reference_review.next_version("no version here")


def test_applying_corrections_updates_both_files_the_version_the_notes_and_the_record(data, questions):
    new_text = "AMD is headquartered in Santa Clara, California, as its filing states."
    new_golden, new_questions, record = reference_review.apply_review(
        result_for(data, edits={"amd-hq": new_text}), data, questions, "golden/x.reference-review.json")
    assert {i["id"]: i["reference_answer"] for i in new_golden["items"]}["amd-hq"] == new_text
    assert {i["id"]: i["reference_answer"] for i in new_questions["items"]}["amd-hq"] == new_text
    assert new_golden["golden_version"] == new_questions["golden_version"] == "citewise-filings-1.1.0"
    assert "checked one by one by hand against the passages (1 corrected)." in new_golden["notes"]
    assert "have not yet been reviewed" not in new_golden["notes"]
    assert new_questions["reference_review"] == {"reviewed": True, "corrected": 1, "record": "golden/x.reference-review.json"}
    assert reference_review.golden_hash(new_golden) != reference_review.golden_hash(data)
    edited = [e for e in record["items"] if e["review"] == EDITED]
    assert [(e["id"], e["draft"]) for e in edited] == [("amd-hq", next(i for i in data["items"] if i["id"] == "amd-hq")["reference_answer"])]
    assert record["corrected"] == 1 and record["golden_version_before"] == "citewise-filings-1.0.0"
    assert golden.validate(new_golden) == []


def test_a_review_with_no_corrections_still_records_that_it_happened(data, questions):
    new_golden, new_questions, record = reference_review.apply_review(result_for(data), data, questions, "r.json")
    assert "(none needed a change)." in new_golden["notes"] and record["corrected"] == 0
    assert [i["reference_answer"] for i in new_golden["items"]] == [i["reference_answer"] for i in data["items"]]


def test_the_builder_writes_the_same_notes_for_both_review_states(data, questions):
    build = builder()
    assert build.notes(None) == data["notes"]
    new_golden, new_questions, _ = reference_review.apply_review(result_for(data), data, questions, "r.json")
    assert build.notes(new_questions["reference_review"]) == new_golden["notes"]


def test_nothing_is_applied_when_the_review_has_a_problem_or_was_already_applied(data, questions):
    with pytest.raises(ReviewError, match="marked unclear"):
        reference_review.apply_review(result_for(data, unclear=["amd-hq"]), data, questions, "r.json")
    with pytest.raises(ReviewError, match="already records a review"):
        reference_review.apply_review(result_for(data), data, {**questions, "reference_review": {"reviewed": True}}, "r.json")


# --- the commands ------------------------------------------------------------------------------------------------

def copies(tmp_path):
    folder = tmp_path / "golden"
    folder.mkdir()
    for source in (GOLDEN, QUESTIONS):
        shutil.copy(source, folder / source.name)
    return folder / GOLDEN.name, folder / QUESTIONS.name


def test_the_sheet_command_writes_a_page(tmp_path, capsys):
    out = tmp_path / "sheet.html"
    assert cli.main(["review-sheet", "--golden", str(GOLDEN), "--out", str(out)]) == 0
    assert "44 reference answers to review" in capsys.readouterr().out
    assert "Review the reference answers" in out.read_text(encoding="utf-8")


def test_the_apply_command_rewrites_the_files_in_their_own_format_and_refuses_to_apply_twice(tmp_path, capsys):
    golden_path, questions_path = copies(tmp_path)
    data = golden.load_json(golden_path)
    result_path = tmp_path / "labels.json"
    result_path.write_text(json.dumps(result_for(data, edits={"amd-hq": "AMD is headquartered in Santa Clara, California."})), encoding="utf-8")
    args = ["apply-review", str(result_path), "--golden", str(golden_path), "--questions", str(questions_path)]
    assert cli.main(args) == 0
    assert "1 corrected" in capsys.readouterr().out
    for path, indent in ((golden_path, 2), (questions_path, 1)):
        text = path.read_text(encoding="utf-8")
        assert json.dumps(json.loads(text), indent=indent, ensure_ascii=False) + "\n" == text
    record = json.loads((golden_path.parent / "citewise_filings_v1.reference-review.json").read_text(encoding="utf-8"))
    assert record["golden_version_after"] == "citewise-filings-1.1.0"
    assert golden.load_json(golden_path)["golden_version"] == "citewise-filings-1.1.0"
    assert cli.main(args) == 1  # the same result is now against an older version
    assert "made against" in capsys.readouterr().out


def test_the_apply_command_writes_nothing_when_the_review_is_incomplete(tmp_path, capsys):
    golden_path, questions_path = copies(tmp_path)
    before = (golden_path.read_bytes(), questions_path.read_bytes())
    data = golden.load_json(golden_path)
    result_path = tmp_path / "labels.json"
    result_path.write_text(json.dumps(result_for(data, skip=["amd-hq"])), encoding="utf-8")
    assert cli.main(["apply-review", str(result_path), "--golden", str(golden_path), "--questions", str(questions_path)]) == 1
    assert "amd-hq: not reviewed" in capsys.readouterr().out
    assert (golden_path.read_bytes(), questions_path.read_bytes()) == before
    assert not list(golden_path.parent.glob("*.reference-review.json"))
