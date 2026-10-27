import json
from pathlib import Path

import pytest

from citecheck import golden
from citecheck.text import contains

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "citewise_filings_v1.json"
QUESTIONS = Path(__file__).resolve().parents[1] / "golden" / "citewise_questions_v1.json"


@pytest.fixture(scope="module")
def data():
    return golden.load_json(GOLDEN)


def test_the_citewise_golden_set_is_valid(data):
    assert golden.validate(data) == []
    assert data["target"] == "citewise" and data["corpus"]["fingerprint"] == "filing-identifier"


def test_every_answerable_item_has_evidence_and_a_reference_answer(data):
    for item in data["items"]:
        assert item["reference_answer"].strip() and item["reference_answer"] != "TODO", item["id"]
        if not item["expected_abstain"]:
            assert item["evidence"], item["id"]
            for fact in item["evidence"]:
                assert fact["passages"], item["id"]


def test_every_evidence_document_is_a_listed_filing_and_every_anchor_is_in_its_passage(data):
    documents = set(data["corpus"]["documents"])
    for item in data["items"]:
        for fact in item["evidence"]:
            for passage in fact["passages"]:
                assert passage["doc_id"] in documents, item["id"]
                assert contains(passage["text"], passage.get("anchor", fact["anchor"])), item["id"]


def test_document_ids_follow_the_title_the_target_gives_its_sources(data):
    for doc_id in data["corpus"]["documents"]:
        symbol, form, filed, date = doc_id.split(" ")
        assert form in ("10-K", "10-Q", "8-K") and filed == "filed" and len(date) == 10


def test_the_question_file_and_the_golden_set_have_the_same_items(data):
    spec = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    assert [e["id"] for e in spec["items"]] == [i["id"] for i in data["items"]]


def test_the_set_mixes_categories_and_every_follow_up_has_its_parent_first(data):
    categories = {i["category"] for i in data["items"]}
    assert {"factual", "yes_no", "multi_topic", "edge_case", "unanswerable", "follow_up"} <= categories
    ids = [i["id"] for i in data["items"]]
    for item in data["items"]:
        if item.get("follow_up_to"):
            assert ids.index(item["follow_up_to"]) < ids.index(item["id"])


def test_the_committed_golden_set_records_the_hand_review_and_the_record_matches_it(data):
    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    review = questions["reference_review"]
    assert review["reviewed"] and questions["golden_version"] == data["golden_version"]
    assert "checked one by one by hand" in data["notes"] and "not yet been reviewed" not in data["notes"]
    record = json.loads((GOLDEN.parents[1] / review["record"]).read_text(encoding="utf-8"))
    assert record["golden_version_after"] == data["golden_version"] and record["corrected"] == review["corrected"]
    assert {e["id"]: e["reference_answer"] for e in record["items"]} == {i["id"]: i["reference_answer"] for i in data["items"]}
