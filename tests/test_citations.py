import json

import pytest

from citecheck import runner, scoring
from citecheck.judge import Judge, NoCache
from citecheck.metrics import citations
from citecheck.models import Citation, TargetResponse

from test_judge import FakeClient
from test_runner import DOC, make_golden, mock, response


def cite(number, doc="A 10-K filed 2026-01-01", text="The company had 31,000 employees."):
    return Citation(doc_id=doc, marker=str(number), text=text)


# --- reading markers and sentences -------------------------------------------------------------------------------

def test_markers_are_read_in_order_including_repeats_and_comma_lists():
    assert citations.markers_in("One [1]. Two [3][6]. Again [1]. Both [2, 4].") == [1, 3, 6, 1, 2, 4]
    assert citations.markers_in("No markers, a [note], or [x].") == []


def test_sentences_keep_their_markers_and_drop_fragments():
    text = "AMD had 31,000 employees [1]. It is based in Santa Clara [2]. Yes.\n- Short [3]\nA last claim without a marker."
    found = citations.sentences(text)
    assert found == ["AMD had 31,000 employees [1].", "It is based in Santa Clara [2].", "A last claim without a marker."]


def test_structure_finds_dangling_markers_unused_sources_and_uncited_sentences():
    answer = "AMD had 31,000 employees [1]. It is based in Santa Clara [4]. Founded in 1969 as a start-up."
    s = citations.structure(answer, [cite(1), cite(2)])
    assert (s["dangling"], s["unused"]) == ([4], [2])
    assert (s["sentences"], s["cited_sentences"]) == (3, 2)
    assert s["uncited"] == ["Founded in 1969 as a start-up."]


# --- evidence and precision --------------------------------------------------------------------------------------

EVIDENCE = [{"anchor": "31,000 employees", "passages": [{"doc_id": "A 10-K filed 2026-01-01", "text": "we had 31,000 employees"}]},
            {"anchor": "Santa Clara", "passages": [{"doc_id": "B 10-K filed 2026-01-02", "text": "based in Santa Clara"}]}]


def test_a_fact_is_cited_when_a_source_from_its_document_contains_the_anchor():
    result = citations.evidence_cited([cite(1)], EVIDENCE)
    assert (result["facts"], result["cited"], result["all_cited"], result["text_checked"]) == (2, 1, False, True)
    both = citations.evidence_cited([cite(1), cite(2, "B 10-K filed 2026-01-02", "HQ: based in Santa Clara, CA")], EVIDENCE)
    assert both["all_cited"] is True


def test_a_cited_document_without_the_anchor_text_does_not_count_when_the_excerpt_is_known():
    wrong_text = Citation(doc_id="B 10-K filed 2026-01-02", marker="1", text="Something else entirely.")
    assert citations.evidence_cited([wrong_text], EVIDENCE[1:])["cited"] == 0


def test_a_target_that_gives_no_excerpt_is_matched_on_the_document_alone():
    file_level = [Citation(doc_id="B 10-K filed 2026-01-02")]
    result = citations.evidence_cited(file_level, EVIDENCE[1:])
    assert result["all_cited"] is True and result["text_checked"] is False


def test_source_precision_counts_cited_documents_that_are_expected():
    item = {"evidence": EVIDENCE, "acceptable_sources": ["C 10-K filed 2026-01-03"]}
    cited = [cite(1), cite(2, "C 10-K filed 2026-01-03"), cite(3, "Z 10-K filed 2026-01-09")]
    assert citations.source_precision(cited, item) == {"documents": 3, "expected": 2, "precision": 0.6667}
    assert citations.source_precision([], item)["precision"] is None


# --- claims for the judge ----------------------------------------------------------------------------------------

def test_claim_units_pair_each_cited_sentence_with_its_source_excerpts():
    answer = "AMD had 31,000 employees [1]. It is based in Santa Clara [2][5]. A claim with no marker at all."
    units = citations.claim_units(answer, [cite(1, text="31,000 text"), cite(2, text="Santa Clara text")])
    assert [u["markers"] for u in units] == [[1], [2, 5]]
    assert units[1]["sources"] == [(2, "Santa Clara text")] and units[1]["missing"] == [5]


def test_a_claim_unit_carries_the_sentence_before_it_for_context():
    answer = "AMD had 31,000 employees [1]. Of this, 9,000 work in sales [2]. A closing sentence with no marker."
    units = citations.claim_units(answer, [cite(1, text="a"), cite(2, text="b")])
    assert units[0]["previous"] == "" and units[1]["previous"] == "AMD had 31,000 employees [1]."


def test_a_source_without_an_excerpt_is_reported_missing():
    units = citations.claim_units("AMD had 31,000 employees [1].", [Citation("d", marker="1", text=None)])
    assert units[0]["sources"] == [] and units[0]["missing"] == [1]


# --- summary -----------------------------------------------------------------------------------------------------

def row(markers=(1,), dangling=(), unused=(), sentences=2, cited=2, evidence=None, precision=None, support=None):
    return {"structure": {"markers": list(markers), "dangling": list(dangling), "unused": list(unused),
                          "sentences": sentences, "cited_sentences": cited},
            "evidence": evidence, "precision": precision, "support": support}


def test_summary_counts_answers_with_dangling_markers_and_averages_the_rest():
    rows = [row(evidence={"facts": 2, "cited": 2, "all_cited": True, "text_checked": True},
                precision={"precision": 1.0},
                support=[{"verdict": "supported"}, {"verdict": "partly_supported"}]),
            row(markers=(1, 4), dangling=(4,), cited=1, evidence={"facts": 2, "cited": 1, "all_cited": False, "text_checked": True},
                precision={"precision": 0.5}, support=[{"verdict": None}]),
            row(markers=())]
    s = citations.summarize(rows)
    assert (s["answers"], s["with_markers"], s["with_dangling_marker"]) == (3, 2, 1)
    assert s["cited_sentence_share"] == round((1 + 0.5 + 1) / 3, 4)
    assert s["evidence"] == {"n": 2, "all_cited": 1, "mean_share_cited": 0.75, "text_checked": 2}
    assert s["source_precision"] == {"n": 2, "mean": 0.75}
    assert s["support"]["sentences"] == 3 and s["support"]["judged"] == 2 and s["support"]["errors"] == 1
    assert s["support"]["score"] == 0.75


def test_an_empty_summary_has_no_means():
    s = citations.summarize([])
    assert s["answers"] == 0 and s["cited_sentence_share"] is None and s["support"]["score"] is None


# --- judge and scoring -------------------------------------------------------------------------------------------

def citation_script(kind, text):
    if kind == "citation":
        return {"reasoning": "r", "verdict": "unsupported" if "wrong" in text else "supported"}
    return FakeClient.default(kind, text)


def test_the_judge_checks_each_cited_sentence_against_only_its_own_sources():
    client = FakeClient(citation_script)
    judge = Judge(client, model="m", cache=NoCache())
    answer = TargetResponse(answer="AMD had 31,000 employees [1]. The wrong claim is made here [2].",
                            citations=[cite(1, text="we had 31,000 employees"), cite(2, text="we make chips")])
    out = judge.judge_citations(answer)
    assert [u["verdict"] for u in out] == ["supported", "unsupported"]
    first, second = [c["messages"][1]["content"] for c in client.calls]
    assert "[1] we had 31,000 employees" in first and "we make chips" not in first
    assert "[2] we make chips" in second and "we had 31,000" not in second


def test_the_citation_judge_is_not_shown_the_question_but_is_shown_the_sentence_before():
    client = FakeClient(citation_script)
    judge = Judge(client, model="m", cache=NoCache())
    answer = TargetResponse(answer="AMD had 31,000 employees [1]. Of this, 9,000 work in sales [2].",
                            citations=[cite(1, text="we had 31,000 employees"), cite(2, text="9,000 in sales")])
    judge.judge_citations(answer)
    first, second = [c["messages"][1]["content"] for c in client.calls]
    assert "<question>" not in first and "<question>" not in second and "<previous_sentence>" not in first
    assert "<previous_sentence>\nAMD had 31,000 employees [1].\n</previous_sentence>\n\n<statement>" in second


def test_a_sentence_whose_sources_are_all_missing_is_reported_not_judged():
    judge = Judge(FakeClient(citation_script), model="m", cache=NoCache())
    out = judge.judge_citations(TargetResponse(answer="AMD had 31,000 employees [3].", citations=[cite(1)]))
    assert out[0]["verdict"] is None and out[0]["missing"] == [3] and out[0]["error"]


def cited_run():
    golden = make_golden()
    golden["items"][0]["evidence"][0]["passages"][0]["doc_id"] = DOC
    responses = {"How much is a bath?": TargetResponse(
        answer="A bath at the daycare costs $50.00 [1]. Nail trims are priced separately [2].",
        citations=[Citation(DOC, marker="1", text="- Bath: $50.00"), Citation("other.md", marker="2", text="- Nail trim: $30.00")]),
        "And nails?": response("Nails are $30."), "Do you take cats?": response("I don't know.")}
    return golden, runner.run_golden(golden, mock(**responses))


def test_score_run_reports_citation_metrics_without_a_judge():
    golden, run = cited_run()
    scores = scoring.score_run(run, golden)
    c = scores["summary"]["overall"]["citations"]
    assert c["answers"] == 2  # the unanswerable item is not expected to cite
    assert c["with_markers"] == 1 and c["evidence"] == {"n": 1, "all_cited": 1, "mean_share_cited": 1.0, "text_checked": 1}
    assert c["source_precision"]["mean"] == 0.5 and c["support"]["sentences"] == 0
    assert "citations (answers that should carry them" in scoring.format_report(scores)


def test_score_run_with_a_judge_adds_claim_support_and_skips_declined_answers():
    golden, run = cited_run()
    judge = Judge(FakeClient(citation_script), model="m", cache=NoCache())
    scores = scoring.score_run(run, golden, judge=judge)
    support = scores["summary"]["overall"]["citations"]["support"]
    assert support["sentences"] == 2 and support["supported"] == 2 and support["score"] == 1.0
    assert "claims" in scoring.format_report(scores)


def test_a_target_that_does_not_report_retrieval_gets_no_retrieval_scores():
    golden, run = cited_run()
    run["target"]["describe"]["reports_retrieved"] = False
    scores = scoring.score_run(run, golden)
    assert scores["summary"]["overall"]["retrieval"]["n"] == 0
    assert all(r["retrieval"] is None for r in scores["items"])
    assert scores["summary"]["overall"]["citations"]["evidence"]["n"] == 1  # citations are still scored


def test_the_target_saying_it_abstained_removes_the_answer_from_the_citation_metrics():
    golden, run = cited_run()
    run["records"][0]["response"]["abstained"] = True
    assert scoring.score_run(run, golden)["summary"]["overall"]["citations"]["answers"] == 1


# --- a passage that words the fact differently --------------------------------------------------------------------

def test_a_passage_with_its_own_anchor_counts_for_its_fact():
    fact = {"anchor": "Our headquarters is in Santa Clara", "passages": [
        {"doc_id": "D", "text": "Our headquarters is in Santa Clara"},
        {"doc_id": "D", "anchor": "Headquartered in Santa Clara", "text": "Headquartered in Santa Clara, NVIDIA was founded"}]}
    other_words = Citation(doc_id="D", marker="1", text="Headquartered in Santa Clara, NVIDIA was founded in 1993")
    assert citations.evidence_cited([other_words], [fact])["all_cited"] is True
    assert citations.evidence_cited([Citation("D", "1", "Santa Clara data center")], [fact])["all_cited"] is False


def test_retrieval_matching_also_honours_a_passages_own_anchor():
    from citecheck.metrics import retrieval
    from citecheck.models import RetrievedChunk
    fact = {"anchor": "Our headquarters is in Santa Clara", "passages": [
        {"doc_id": "D", "text": "Our headquarters is in Santa Clara"},
        {"doc_id": "E", "anchor": "Headquartered in Santa Clara", "text": "Headquartered in Santa Clara, NVIDIA"}]}
    assert retrieval.chunk_matches(RetrievedChunk("E", "Headquartered in Santa Clara, NVIDIA", 1), fact)
    assert not retrieval.chunk_matches(RetrievedChunk("D", "Headquartered in Santa Clara, NVIDIA", 1), fact)  # wrong document
    assert retrieval.chunk_matches(RetrievedChunk("D", "Headquartered in Santa Clara, NVIDIA", 1), fact, require_doc=False)
