import pytest

from citecheck.metrics import retrieval
from citecheck.models import RetrievedChunk

BATH = {"anchor": "Bath: $50.00", "passages": [{"doc_id": "03-pricing.md", "text": "- Bath: $50.00"}]}
HOURS = {"anchor": "Saturday: 8:00am to 6:00pm", "passages": [{"doc_id": "04-hours.md", "text": "- Saturday: 8:00am to 6:00pm"}]}


def chunk(rank, text="unrelated text", doc="05-routine.md"):
    return RetrievedChunk(doc_id=doc, text=text, rank=rank)


def bath_at(rank):
    return chunk(rank, "Add-ons\n- Bath: $50.00\n- Nail trim: $30.00", "03-pricing.md")


def score(chunks, evidence, ks=(1, 3, 5), **kw):
    return retrieval.score_item(chunks, evidence, ks, **kw)


def test_fact_at_rank_one():
    s = score([bath_at(1), chunk(2), chunk(3), chunk(4)], [BATH])
    assert (s["found"], s["first_hit_rank"], s["worst_hit_rank"], s["reciprocal_rank"]) == (True, 1, 1, 1.0)
    assert s["recall_at"] == {1: 1.0, 3: 1.0, 5: 1.0}
    assert s["precision_at"][1] == 1.0 and s["precision_at"][3] == pytest.approx(1 / 3)


def test_fact_at_rank_three():
    s = score([chunk(1), chunk(2), bath_at(3), chunk(4)], [BATH])
    assert s["fact_ranks"] == [3]
    assert s["reciprocal_rank"] == pytest.approx(1 / 3)
    assert s["recall_at"] == {1: 0.0, 3: 1.0, 5: 1.0}
    assert s["found_at"] == {1: False, 3: True, 5: True}


def test_precision_divides_by_chunks_returned_when_fewer_than_k():
    s = score([bath_at(1), chunk(2), chunk(3), chunk(4)], [BATH])
    assert s["precision_at"][5] == pytest.approx(1 / 4)  # not 1/5: the target only returned 4


def test_not_found():
    s = score([chunk(1), chunk(2)], [BATH])
    assert (s["found"], s["first_hit_rank"], s["worst_hit_rank"], s["reciprocal_rank"]) == (False, None, None, 0.0)
    assert s["recall_at"][5] == 0.0 and s["precision_at"][5] == 0.0


def test_no_chunks_returned():
    s = score([], [BATH])
    assert s["found"] is False and s["precision_at"][3] == 0.0 and s["n_chunks"] == 0


def test_chunk_from_the_wrong_document_is_a_hit_only_when_documents_are_not_required():
    wrong_doc = chunk(1, "Bath: $50.00", doc="99-other.md")
    assert score([wrong_doc], [BATH])["found"] is False
    assert score([wrong_doc], [BATH], require_doc=False)["found"] is True


def test_matching_ignores_case_whitespace_and_curly_apostrophes():
    fact = {"anchor": "Don't bring toys", "passages": [{"doc_id": "d.md", "text": "Don't bring toys"}]}
    messy = RetrievedChunk(doc_id="d.md", text="RULES\n\n  DON’T   bring\ntoys here", rank=1)
    assert score([messy], [fact])["found"] is True


def test_two_facts_found_at_different_ranks():
    s = score([chunk(1), bath_at(2), chunk(3), RetrievedChunk("04-hours.md", "- Saturday: 8:00am to 6:00pm", 4)], [BATH, HOURS])
    assert s["fact_ranks"] == [2, 4]
    assert (s["first_hit_rank"], s["worst_hit_rank"]) == (2, 4)
    assert s["recall_at"] == {1: 0.0, 3: 0.5, 5: 1.0}
    assert s["found_at"] == {1: False, 3: False, 5: True}
    assert s["reciprocal_rank"] == 0.5


def test_one_of_two_facts_missing_is_not_found_and_has_no_worst_rank():
    s = score([bath_at(1)], [BATH, HOURS])
    assert s["found"] is False and s["worst_hit_rank"] is None and s["first_hit_rank"] == 1
    assert s["recall_at"][5] == 0.5


def test_best_rank_wins_when_several_chunks_match_and_all_count_for_precision():
    s = score([chunk(1), bath_at(2), bath_at(3)], [BATH])
    assert s["fact_ranks"] == [2]
    assert s["precision_at"][3] == pytest.approx(2 / 3)


def test_chunks_are_ranked_by_their_rank_not_their_list_position():
    s = score([bath_at(3), chunk(1), chunk(2)], [BATH])
    assert s["fact_ranks"] == [3]


def test_several_documents_may_state_a_fact():
    fact = {"anchor": "123 puppy drive", "passages": [{"doc_id": "04-hours.md", "text": "123 puppy drive"},
                                                      {"doc_id": "07-guide.pdf", "text": "at 123 puppy drive"}]}
    assert score([RetrievedChunk("07-guide.pdf", "Barks is at 123 puppy drive.", 1)], [fact])["found"] is True


def test_empty_evidence_is_refused():
    with pytest.raises(ValueError):
        score([chunk(1)], [])


def test_summarize():
    found_first = score([bath_at(1), chunk(2)], [BATH])
    found_third = score([chunk(1), chunk(2), bath_at(3)], [BATH])
    missed = score([chunk(1)], [BATH])
    s = retrieval.summarize([found_first, found_third, missed], (1, 3))
    assert s["n"] == 3 and s["found"] == 2 and s["top_ranked"] == 1
    assert s["found_at"] == {1: 1, 3: 2}
    assert s["mrr"] == pytest.approx((1 + 1 / 3 + 0) / 3)
    assert s["mean_recall_at"][3] == pytest.approx(2 / 3)
    assert s["mean_worst_rank"] == 2.0  # mean of 1 and 3, over the found items only


def test_summarize_nothing():
    assert retrieval.summarize([], (1,)) == {"n": 0}
