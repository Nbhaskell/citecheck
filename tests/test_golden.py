import copy
from pathlib import Path

import pytest

from citecheck import golden

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "rag_demo_v1.json"


@pytest.fixture
def data():
    return copy.deepcopy(golden.load_json(GOLDEN))


def item(data, item_id):
    return next(i for i in data["items"] if i["id"] == item_id)


def test_shipped_golden_set_is_valid():
    assert golden.validate(golden.load_json(GOLDEN)) == []


def test_counts_match_the_source_project_readme(data):
    # rag-project's README reports retrieval on 59 of the 67 tuned and 46 of the 55 held-out questions
    scored = {s: sum(bool(i["evidence"]) for i in data["items"] if i["split"] == s) for s in ("tuned", "heldout")}
    totals = {s: sum(i["split"] == s for i in data["items"]) for s in ("tuned", "heldout")}
    assert (scored, totals) == ({"tuned": 59, "heldout": 46}, {"tuned": 67, "heldout": 55})


def test_duplicate_id_is_reported(data):
    data["items"].append(copy.deepcopy(data["items"][0]))
    assert any("more than once" in p for p in golden.validate(data))


def test_follow_up_must_point_at_an_earlier_item(data):
    item(data, "followup-half-day")["follow_up_to"] = "no-such-item"
    assert any("is not an item" in p for p in golden.validate(data))


def test_follow_up_category_requires_follow_up_to(data):
    del item(data, "followup-half-day")["follow_up_to"]
    assert golden.validate(data)


def test_unanswerable_must_abstain_and_have_no_evidence(data):
    unans = item(data, "unknown-cats")
    unans["expected_abstain"] = False
    assert golden.validate(data)
    unans["expected_abstain"] = True
    unans["evidence"] = item(data, "full-day-price")["evidence"]
    assert golden.validate(data)


def test_answerable_item_needs_evidence(data):
    item(data, "full-day-price")["evidence"] = []
    assert golden.validate(data)


def test_anchor_must_occur_in_its_passage(data):
    item(data, "full-day-price")["evidence"][0]["anchor"] = "a phrase that is not there"
    assert any("does not occur" in p for p in golden.validate(data))


def test_passage_document_must_be_in_the_corpus(data):
    item(data, "full-day-price")["evidence"][0]["passages"][0]["doc_id"] = "missing.md"
    assert any("not in corpus.documents" in p for p in golden.validate(data))


def test_unknown_field_is_rejected(data):
    item(data, "full-day-price")["answer_keywords"] = ["typo"]
    assert golden.validate(data)


def test_a_probe_needs_no_evidence_but_cannot_claim_any_or_expect_a_refusal(data):
    probe = item(data, "full-day-price")
    probe["category"], probe["evidence"] = "probe", []
    assert golden.validate(data) == []
    probe["evidence"] = next(i["evidence"] for i in data["items"] if i is not probe and i["evidence"])
    assert golden.validate(data)
    probe["evidence"], probe["expected_abstain"] = [], True
    assert golden.validate(data)


def test_a_question_that_is_not_a_probe_still_needs_evidence_when_it_is_answerable(data):
    answerable = item(data, "full-day-price")
    answerable["evidence"] = []
    assert golden.validate(data)
    answerable["category"] = "probe"
    assert golden.validate(data) == []
