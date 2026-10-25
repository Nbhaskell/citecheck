import json

from citecheck import cli, known_bad, runner
from citecheck.judge import Judge, NoCache
from citecheck.models import TargetResponse

from test_judge import FakeClient
from test_runner import make_golden, mock


def test_a_number_is_changed_to_one_the_passages_do_not_contain():
    changed = known_bad.change_number("A bath is $50.00 and takes 2 hours.", ["Nail trim: $67.00", "Bath: $50.00"])
    assert changed.startswith("A bath is $") and "$50.00" not in changed and "$67.00" not in changed
    assert changed.endswith("and takes 2 hours.")  # only the first money amount changes


def test_without_a_money_amount_the_first_number_changes_and_without_numbers_nothing_does():
    assert known_bad.change_number("Cancel 12 hours before.", ["12 hours"]) != "Cancel 12 hours before."
    assert known_bad.change_number("It depends.", []) is None


def test_a_leading_yes_or_no_is_flipped_and_other_answers_are_left_alone():
    assert known_bad.flip_yes_no("Yes, you can.") == "No, you can."
    assert known_bad.flip_yes_no("No. Not allowed.") == "Yes. Not allowed."
    assert known_bad.flip_yes_no("Notably, it is $5.") is None
    assert known_bad.flip_yes_no("Bath: $50.") is None


def candidates():
    return [{"item_id": "a", "answer": "Yes, it is $50.", "passages": ["Bath: $50.00"]},
            {"item_id": "b", "answer": "The fee is $30.", "passages": ["Nails: $30.00"]}]


def test_each_answer_gets_every_kind_of_damage_that_applies_to_it():
    cases = known_bad.build_cases(candidates())
    kinds = {(c["item_id"], c["kind"]) for c in cases}
    assert ("a", "yes_no_flipped") in kinds and ("b", "yes_no_flipped") not in kinds
    assert {k for i, k in kinds if i == "b"} == {"number_changed", "claim_added", "wrong_answer", "declined"}
    wrong = next(c for c in cases if c["item_id"] == "a" and c["kind"] == "wrong_answer")
    assert wrong["answer"] == "The fee is $30."
    added = next(c for c in cases if c["item_id"] == "a" and c["kind"] == "claim_added")
    assert added["answer"].startswith("Yes, it is $50. ") and added["answer"] != "Yes, it is $50. "


def test_building_cases_is_repeatable():
    assert known_bad.build_cases(candidates()) == known_bad.build_cases(candidates())


def results(kind, **rows):
    return [{"item_id": i, "kind": kind, "verdicts": v, "errors": []} for i, v in rows.items()]


def test_summary_counts_flagged_and_certainly_flagged_per_dimension():
    rs = (results("control", a={"faithfulness": "supported", "correctness": "correct"},
                  b={"faithfulness": "partly_supported", "correctness": "correct"})
          + results("number_changed", a={"faithfulness": "unsupported", "correctness": "incorrect"},
                    b={"faithfulness": "supported", "correctness": "partly_correct"})
          + results("declined", a={"abstention": "abstained", "correctness": "incorrect"}))
    summary = known_bad.summarize(rs)
    assert summary["control"]["dimensions"]["faithfulness"] == {"n": 2, "flagged": 1, "flagged_for_certain": 0}
    changed = summary["number_changed"]["dimensions"]
    assert changed["faithfulness"] == {"n": 2, "flagged": 1, "flagged_for_certain": 1}
    assert changed["correctness"] == {"n": 2, "flagged": 2, "flagged_for_certain": 1}
    assert summary["declined"]["dimensions"]["abstention"] == {"n": 1, "flagged": 1, "flagged_for_certain": 1}


def test_a_judge_failure_is_left_out_of_the_counts():
    rs = results("claim_added", a={"faithfulness": "unsupported"})
    rs[0]["errors"] = ["timed out"]
    entry = known_bad.summarize(rs)["claim_added"]
    assert entry["judge_errors"] == 1 and entry["dimensions"]["faithfulness"]["n"] == 0


def test_cases_are_judged_with_the_damaged_answer_and_the_original_passages():
    golden = make_golden()
    golden["items"][0]["reference_answer"] = "A bath is $50."
    run = runner.run_golden(golden, mock())
    record = run["records"][0]
    response = TargetResponse.from_dict(record["response"])
    client = FakeClient()
    judge = Judge(client, model="m", cache=NoCache())
    items = {i["id"]: i for i in golden["items"]}
    cases = [{"item_id": "bath", "kind": "declined", "answer": "I don't know."}]
    out = known_bad.judge_cases(judge, items, {"bath": response}, {"bath": []}, cases)
    assert [r["kind"] for r in out] == ["control", "declined"]
    assert out[1]["verdicts"]["abstention"] == "abstained"
    seen = [c["messages"][1]["content"] for c in client.calls]
    assert any("A bath is $50." in text for text in seen[:3]) and any("I don't know." in text for text in seen[3:])
    assert any("- Bath: $50.00" in text for text in seen)  # the original passages reach the faithfulness check


def test_candidates_are_only_the_answers_labelled_supported_and_correct():
    run = runner.run_golden(make_golden(), mock())
    labels = {"items": {"bath": {"faithfulness": "supported", "correctness": "correct"},
                        "and-nails": {"faithfulness": "partly_supported", "correctness": "correct"},
                        "cats": {"faithfulness": None, "correctness": None}}}
    found, responses, histories = known_bad.candidates_from(run, labels)
    assert [c["item_id"] for c in found] == ["bath"] and list(responses) == ["bath"]
    assert found[0]["passages"][1] == "- Bath: $50.00"
    assert histories["bath"] == []


def test_the_report_names_the_judge_and_each_kind_of_damage():
    summary = known_bad.summarize(results("control", a={"faithfulness": "supported", "correctness": "correct"})
                                  + results("claim_added", a={"faithfulness": "unsupported"}))
    text = known_bad.format_report(summary, {"model": "m", "think": True, "prompt_version": "1"})
    assert "thinking on" in text and "claim_added" in text and "1/1" in text
