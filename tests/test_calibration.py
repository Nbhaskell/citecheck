import json

import pytest

from citecheck import calibration, calibration_sheet, cli, runner
from citecheck.calibration import AGREE, DISAGREE, LabelsError

from test_runner import make_golden, mock


def verdict(value):
    return {"verdict": value, "error": None}


def scores_file(rows, think=False, run_id="r1"):
    """rows: {item_id: {dimension: verdict}} -> a minimal scores file."""
    items = [{"item_id": item_id, "repeat": 1,
              "judged": {d: verdict(v) for d, v in dims.items()}} for item_id, dims in rows.items()]
    return {"run_id": run_id, "items": items,
            "config": {"judge": {"model": "m", "think": think, "prompt_version": "1"}}}


def many_items(n, unanswerable=()):
    return {f"i{k}": {"expected_abstain": f"i{k}" in unanswerable} for k in range(n)}


# --- sampling ----------------------------------------------------------------------------------------------------

def two_settings(n=40, disagree_ids=()):
    off = {f"i{k}": {"abstention": "answered", "faithfulness": "supported"} for k in range(n)}
    on = {key: dict(value) for key, value in off.items()}
    for item_id in disagree_ids:
        on[item_id]["faithfulness"] = "partly_supported"
    return [scores_file(off), scores_file(on, think=True)]


def test_the_sample_takes_most_disagreements_and_fills_up_from_agreements():
    scores = two_settings(40, disagree_ids=[f"i{k}" for k in range(20)])
    sample = calibration.select_sample(scores, many_items(40), n=10, seed=1)
    assert len(sample["picks"]) == 10 and len(set(sample["picks"])) == 10
    assert sorted(sample["strata"].values()).count(DISAGREE) == 6  # 65% of 10, rounded
    assert sample["population"] == {DISAGREE: 20, AGREE: 20}
    assert all(sample["strata"][i] == (DISAGREE if int(i[1:]) < 20 else AGREE) for i in sample["picks"])


def test_the_sample_is_repeatable_and_changes_with_the_seed():
    scores = two_settings(40, disagree_ids=[f"i{k}" for k in range(20)])
    one = calibration.select_sample(scores, many_items(40), n=10, seed=1)
    again = calibration.select_sample(scores, many_items(40), n=10, seed=1)
    other = calibration.select_sample(scores, many_items(40), n=10, seed=2)
    assert one == again and one["picks"] != other["picks"]


def test_when_few_answers_disagree_the_rest_of_the_sample_comes_from_agreements():
    scores = two_settings(40, disagree_ids=["i0", "i1"])
    sample = calibration.select_sample(scores, many_items(40), n=10, seed=0)
    assert len(sample["picks"]) == 10
    assert list(sample["strata"].values()).count(DISAGREE) == 2


def test_the_agreeing_part_of_the_sample_includes_unanswerable_questions():
    items = many_items(60, unanswerable={f"i{k}" for k in range(50, 60)})
    sample = calibration.select_sample(two_settings(60), items, n=12, seed=3)
    assert sum(items[i]["expected_abstain"] for i in sample["picks"]) >= 2


def test_answers_not_judged_under_every_setting_are_left_out():
    scores = two_settings(10)
    scores[1]["items"] = scores[1]["items"][:5]
    assert len(calibration.select_sample(scores, many_items(10), n=10)["picks"]) == 5


# --- the sheet ---------------------------------------------------------------------------------------------------

def run_and_golden():
    golden = make_golden()
    for item in golden["items"]:
        item["reference_answer"] = f"reference for {item['id']}"
    return runner.run_golden(golden, mock()), golden


def test_the_sheet_shows_the_answer_and_passages_but_no_judge_verdicts():
    run, golden = run_and_golden()
    scores = [scores_file({"bath": {"abstention": "answered"}, "and-nails": {"abstention": "answered"},
                           "cats": {"abstention": "abstained"}}, run_id=run["run_id"])]
    sample = calibration.select_sample(scores, {i["id"]: i for i in golden["items"]}, n=3)
    data = calibration.sheet_data(run, golden, sample)
    assert {c["id"] for c in data["cards"]} == {"bath", "and-nails", "cats"}
    bath = next(c for c in data["cards"] if c["id"] == "bath")
    assert bath["answer"] == "A bath is $50." and len(bath["passages"]) == 4 and bath["answerable"]
    follow_up = next(c for c in data["cards"] if c["id"] == "and-nails")
    assert follow_up["history"][0]["content"] == "How much is a bath?"
    assert not next(c for c in data["cards"] if c["id"] == "cats")["answerable"]
    assert "verdict" not in json.dumps(data) and "judge" not in json.dumps(data)


def test_the_sheet_html_embeds_its_data_without_closing_the_script_tag():
    data = {"run_id": "r", "golden_version": "g", "labels_version": 1, "population": {}, "cards": [
        {"id": "x", "question": "q", "history": [], "reference_answer": "", "answerable": True,
         "answer": "</script><b>", "passages": [], "stratum": AGREE}]}
    html = calibration_sheet.render(data)
    assert "</script><b>" not in html and "\\u003c/script>" in html


# --- agreement ---------------------------------------------------------------------------------------------------

def test_kappa_is_one_for_perfect_agreement_and_zero_for_chance_level():
    assert calibration.cohens_kappa([("a", "a"), ("b", "b")]) == 1.0
    assert calibration.cohens_kappa([("a", "a"), ("a", "b"), ("b", "a"), ("b", "b")]) == 0.0
    assert calibration.cohens_kappa([("a", "a"), ("a", "a")]) is None  # one label only: kappa is undefined
    assert calibration.cohens_kappa([]) is None


def labels_file(items, population=None):
    return {"labels_version": 1, "run_id": "r1", "golden_version": "g", "golden_hash": "h",
            "population": population or {AGREE: 2, DISAGREE: 2}, "items": items}


def entry(stratum, **labels):
    return {"abstention": None, "faithfulness": None, "correctness": None, "note": "", "stratum": stratum, **labels}


def test_agreement_counts_matches_confusions_and_lists_disagreements():
    labels = labels_file({
        "a": entry(AGREE, abstention="answered", faithfulness="supported"),
        "b": entry(DISAGREE, abstention="answered", faithfulness="supported"),
        "c": entry(DISAGREE, abstention="answered", faithfulness="unsupported")})
    scores = scores_file({"a": {"abstention": "answered", "faithfulness": "supported"},
                          "b": {"abstention": "answered", "faithfulness": "partly_supported"},
                          "c": {"abstention": "answered", "faithfulness": "unsupported"}})
    result = calibration.agreement(labels, scores)["dimensions"]
    assert result["abstention"]["agreement"] == 1.0 and result["correctness"]["n"] == 0
    faith = result["faithfulness"]
    assert (faith["n"], faith["agree"], faith["agreement"]) == (3, 2, 0.667)
    assert faith["confusion"] == {"supported -> partly_supported": 1, "supported -> supported": 1,
                                  "unsupported -> unsupported": 1}
    assert faith["disagreements"] == [{"item_id": "b", "human": "supported", "judge": "partly_supported"}]
    assert faith["top_label_agreement"] == 0.667


def test_weighted_agreement_scales_each_group_to_its_size_in_the_run():
    labels = labels_file({"a": entry(AGREE, abstention="answered"),
                          "b": entry(DISAGREE, abstention="answered")}, population={AGREE: 90, DISAGREE: 10})
    scores = scores_file({"a": {"abstention": "answered"}, "b": {"abstention": "abstained"}})
    d = calibration.agreement(labels, scores)["dimensions"]["abstention"]
    assert d["agreement"] == 0.5 and d["weighted_agreement"] == 0.9  # the agreeing group is 90% of the run


def test_agreement_refuses_scores_from_another_run():
    with pytest.raises(LabelsError, match="run r1"):
        calibration.agreement(labels_file({}), scores_file({}, run_id="other"))


def test_a_judge_failure_is_not_counted_as_a_disagreement():
    labels = labels_file({"a": entry(AGREE, abstention="answered")})
    scores = scores_file({"a": {"abstention": "answered"}})
    scores["items"][0]["judged"]["abstention"]["verdict"] = None
    d = calibration.agreement(labels, scores)["dimensions"]["abstention"]
    assert d["n"] == 0 and d["missing_judge_verdict"] == 1


def test_labels_with_an_unknown_label_or_stratum_are_rejected(tmp_path):
    bad = labels_file({"a": entry("odd", abstention="maybe")})
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(LabelsError) as error:
        calibration.load_labels(path)
    assert "maybe" in str(error.value) and "stratum" in str(error.value)


# --- command line ------------------------------------------------------------------------------------------------

def test_sheet_and_calibrate_commands_work_end_to_end(tmp_path, capsys):
    run, golden = run_and_golden()
    run_path = runner.save_run(run, tmp_path)
    golden_path = tmp_path / "golden.json"
    golden_path.write_text(json.dumps(golden), encoding="utf-8")
    rows = {"bath": {"abstention": "answered", "faithfulness": "supported", "correctness": "correct"},
            "and-nails": {"abstention": "answered", "faithfulness": "supported", "correctness": "correct"},
            "cats": {"abstention": "abstained"}}
    paths = []
    for name, think in (("off", False), ("on", True)):
        path = tmp_path / f"{name}.scores.json"
        path.write_text(json.dumps(scores_file(rows, think=think, run_id=run["run_id"])), encoding="utf-8")
        paths.append(str(path))
    sheet = tmp_path / "out" / "sheet.html"
    code = cli.main(["sheet", str(run_path), "--golden", str(golden_path), "--scores", paths[0], "--scores", paths[1],
                     "--n", "3", "--out", str(sheet)])
    assert code == 0 and "3 answers" in capsys.readouterr().out and "How much is a bath?" in sheet.read_text(encoding="utf-8")

    labels = labels_file({k: entry(AGREE, **{d: v for d, v in dims.items()}) for k, dims in rows.items()},
                         population={AGREE: 3, DISAGREE: 0})
    labels["run_id"] = run["run_id"]
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps(labels), encoding="utf-8")
    saved = tmp_path / "agreement.json"
    code = cli.main(["calibrate", str(labels_path), "--scores", paths[0], "--scores", paths[1], "--save", str(saved)])
    out = capsys.readouterr().out
    assert code == 0 and "thinking off" in out and "thinking on" in out and "1.000" in out
    assert len(json.loads(saved.read_text(encoding="utf-8"))) == 2
