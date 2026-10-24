import copy
import json

import pytest

from citecheck import cli, golden, runner, scoring
from citecheck.adapters import AdapterError, MockAdapter
from citecheck.models import RetrievedChunk, TargetResponse

DOC = "03-pricing.md"
BATH_TEXT = "- Bath: $50.00"


def make_golden():
    def item(item_id, category, question, split="tuned", **extra):
        return {"id": item_id, "split": split, "category": category, "question": question,
                "expected_abstain": category == "unanswerable", "evidence": [], **extra}

    bath = {"anchor": "Bath: $50.00", "passages": [{"doc_id": DOC, "text": BATH_TEXT}]}
    return {
        "schema_version": 1, "golden_version": "test-1.0.0", "target": "mock",
        "corpus": {"name": "test", "documents": {DOC: "0" * 64}},
        "items": [
            item("bath", "factual", "How much is a bath?", evidence=[bath]),
            item("and-nails", "follow_up", "And nails?", follow_up_to="bath"),
            item("cats", "unanswerable", "Do you take cats?", split="heldout"),
        ],
    }


def response(answer="ok", ranks_with_bath=()):
    chunks = [RetrievedChunk(DOC, BATH_TEXT if r in ranks_with_bath else "something else", r) for r in range(1, 5)]
    return TargetResponse(answer=answer, retrieved=chunks)


def mock(**overrides):
    table = {"How much is a bath?": response("A bath is $50.", {2}), "And nails?": response("Nails are $30."),
             "Do you take cats?": response("I don't know.")}
    table.update(overrides)
    return MockAdapter(table, settings={"top_k": 4})


def test_fixture_is_a_valid_golden_set():
    assert golden.validate(make_golden()) == []


def test_run_asks_every_question_and_records_the_target_settings():
    adapter = mock()
    run = runner.run_golden(make_golden(), adapter, label="first try")
    assert [r["item_id"] for r in run["records"]] == ["bath", "and-nails", "cats"]
    assert run["target"] == {"name": "mock", "describe": {"top_k": 4}}
    assert run["golden"]["golden_version"] == "test-1.0.0"
    assert run["run_id"].endswith("_first-try")


def test_follow_up_is_asked_with_its_parents_question_and_this_runs_answer():
    adapter = mock()
    runner.run_golden(make_golden(), adapter)
    follow_up_call = adapter.calls[1]
    assert follow_up_call["history"] == [{"role": "user", "content": "How much is a bath?"},
                                         {"role": "assistant", "content": "A bath is $50."}]
    assert adapter.calls[0]["history"] == []


def test_follow_up_is_not_asked_when_its_parent_failed():
    adapter = mock()
    del adapter.responses["How much is a bath?"]
    run = runner.run_golden(make_golden(), adapter)
    errors = {r["item_id"]: r["response"]["error"] for r in run["records"]}
    assert "mock has no response" in errors["bath"]
    assert "parent question 'bath' has no answer" in errors["and-nails"]
    assert errors["cats"] is None
    assert [c["question"] for c in adapter.calls] == ["How much is a bath?", "Do you take cats?"]


def test_selecting_a_follow_up_brings_its_parent():
    assert [i["id"] for i in runner.select_items(make_golden(), ids={"and-nails"})] == ["bath", "and-nails"]
    assert [i["id"] for i in runner.select_items(make_golden(), splits={"heldout"})] == ["cats"]


def test_repeats_ask_everything_again():
    run = runner.run_golden(make_golden(), mock(), repeats=2)
    assert [(r["item_id"], r["repeat"]) for r in run["records"]][3:] == [("bath", 2), ("and-nails", 2), ("cats", 2)]


def test_run_file_round_trips(tmp_path):
    run = runner.run_golden(make_golden(), mock(), label="x")
    path = runner.save_run(run, tmp_path)
    assert path.name.endswith("_x.run.json")
    assert json.loads(path.read_text(encoding="utf-8")) == run


def test_golden_hash_ignores_layout_but_not_content():
    data = make_golden()
    reordered = json.loads(json.dumps(data, sort_keys=True))
    assert runner.golden_hash(data) == runner.golden_hash(reordered)
    changed = copy.deepcopy(data)
    changed["items"][0]["question"] = "How much is a bath, please?"
    assert runner.golden_hash(data) != runner.golden_hash(changed)


def test_score_run_counts_only_answers_that_have_evidence_and_no_error():
    adapter = mock()
    del adapter.responses["Do you take cats?"]
    run = runner.run_golden(make_golden(), adapter)
    scores = scoring.score_run(run, make_golden(), ks=(1, 3))
    overall = scores["summary"]["overall"]
    assert (overall["asked"], overall["errors"]) == (3, 1)
    assert overall["retrieval"]["n"] == 1  # only "bath": the follow-up has no evidence, "cats" errored
    assert overall["retrieval"]["found"] == 1 and overall["retrieval"]["mrr"] == 0.5
    assert overall["retrieval"]["mean_recall_at"] == {1: 0.0, 3: 1.0}


def test_score_run_groups_by_split_category_and_repeat():
    run = runner.run_golden(make_golden(), mock(), repeats=2)
    summary = scoring.score_run(run, make_golden())["summary"]
    assert summary["by_split"]["tuned"]["asked"] == 4 and summary["by_split"]["heldout"]["asked"] == 2
    assert set(summary["by_category"]) == {"factual", "follow_up", "unanswerable"}
    assert [g["asked"] for g in summary["by_repeat"]] == [3, 3]


def test_scoring_against_a_changed_golden_set_is_refused():
    run = runner.run_golden(make_golden(), mock())
    changed = make_golden()
    changed["items"][0]["question"] = "different"
    with pytest.raises(scoring.GoldenMismatch):
        scoring.check_golden(run, changed)
    scoring.check_golden(run, make_golden())


def test_report_mentions_every_split(capsys):
    run = runner.run_golden(make_golden(), mock())
    text = scoring.format_report(scoring.score_run(run, make_golden()))
    assert "overall" in text and "tuned" in text and "heldout" in text and "recall@1" in text


def test_cli_score_refuses_a_changed_golden_set_and_can_be_overridden(tmp_path, capsys):
    golden_path = tmp_path / "g.json"
    golden_path.write_text(json.dumps(make_golden()), encoding="utf-8")
    run = runner.run_golden(make_golden(), mock(), golden_path=str(golden_path))
    run_path = runner.save_run(run, tmp_path)

    assert cli.main(["score", str(run_path)]) == 0
    assert run_path.with_name(run_path.name.replace(".run.json", ".scores.json")).exists()

    changed = make_golden()
    changed["items"][2]["question"] = "Do you take dogs?"
    golden_path.write_text(json.dumps(changed), encoding="utf-8")
    assert cli.main(["score", str(run_path)]) == 2
    assert "not comparable" in capsys.readouterr().out
    assert cli.main(["score", str(run_path), "--ignore-golden-mismatch"]) == 0


def test_unreachable_target_fails_before_any_question_is_asked():
    class Down(MockAdapter):
        def describe(self):
            raise AdapterError("connection refused")

    adapter = Down({})
    with pytest.raises(AdapterError):
        runner.run_golden(make_golden(), adapter)
    assert adapter.calls == []


def test_report_columns_stay_apart_for_three_digit_counts():
    row = {"asked": 112, "errors": 0, "retrieval": {"n": 112, "found": 111, "mrr": 0.95, "mean_worst_rank": 1.4, "top_ranked": 85,
                                                    "mean_recall_at": {1: 0.8}, "mean_precision_at": {1: 0.5}}}
    scores = {"run_id": "r", "golden_version": "g", "config": {"ks": [1], "require_doc": True},
              "summary": {"overall": row, "by_split": {}, "by_category": {}, "by_repeat": [row]}}
    assert "111/112" in scoring.format_report(scores).splitlines()[3].split()
