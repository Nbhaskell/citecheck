import json

import pytest

from citecheck import calibration, calibration_sheet, citation_calibration, cli, known_bad_citations, runner
from citecheck.calibration import AGREE, DISAGREE, LabelsError
from citecheck.judge import Judge, NoCache
from citecheck.models import Citation, TargetResponse

from test_judge import FakeClient
from test_runner import DOC, make_golden, mock


def support_scores(units_by_item, think=False, run_id="r1"):
    """units_by_item: {item_id: [verdict, ...]} -> a minimal scores file with one judged unit per verdict."""
    items = [{"item_id": item_id, "repeat": 1,
              "citations": {"support": [{"verdict": v, "sentence": f"s{k}"} for k, v in enumerate(verdicts, 1)]}}
             for item_id, verdicts in units_by_item.items()]
    return {"run_id": run_id, "items": items, "config": {"judge": {"model": "m", "think": think, "prompt_version": "1"}}}


def test_unit_verdicts_are_keyed_by_item_and_position_and_skip_failed_judgments():
    scores = support_scores({"a": ["supported", None, "unsupported"]})
    assert citation_calibration.unit_verdicts(scores) == {"a#1": "supported", "a#3": "unsupported"}


def test_the_sample_takes_disagreements_first_and_is_repeatable():
    off = {f"i{k}": ["supported", "supported"] for k in range(20)}
    on = {key: list(value) for key, value in off.items()}
    for k in range(10):
        on[f"i{k}"][0] = "partly_supported"
    scores = [support_scores(off), support_scores(on, think=True)]
    sample = citation_calibration.select_units(scores, n=10, seed=2)
    assert len(sample["picks"]) == 10 and list(sample["strata"].values()).count(DISAGREE) == 6
    assert sample["population"] == {DISAGREE: 10, AGREE: 30}
    assert sample == citation_calibration.select_units(scores, n=10, seed=2)


def cited_run():
    golden = make_golden()
    responses = {"How much is a bath?": TargetResponse(
        answer="A bath at the daycare costs $50.00 [1]. Nail trims are priced separately and cost $30.00 [2].",
        citations=[Citation(DOC, marker="1", text="- Bath: $50.00"), Citation(DOC, marker="2", text="- Nail trim: $30.00")])}
    return golden, runner.run_golden(golden, mock(**responses))


def test_the_citation_sheet_shows_the_statement_and_only_its_cited_sources():
    golden, run = cited_run()
    sample = {"picks": ["bath#2"], "strata": {"bath#2": AGREE}, "population": {AGREE: 2}}
    data = citation_calibration.sheet_data(run, golden, sample)
    card = data["cards"][0]
    assert data["kind"] == "citations" and card["id"] == "bath#2"
    statement = next(b["text"] for b in card["blocks"] if b["label"] == "The statement to check")
    assert statement.startswith("Nail trims are priced separately") and statement.endswith("[2].")
    assert [i["text"] for i in card["details"]["items"]] == ["- Nail trim: $30.00"] and card["details"]["open"] is True
    assert [g["dim"] for g in card["groups"]] == ["citation_support"]
    assert "judge" not in json.dumps(card)


def test_citation_labels_are_checked_against_the_support_vocabulary(tmp_path):
    bad = {"labels_version": 1, "kind": "citations", "run_id": "r1", "population": {}, "items": {
        "a#1": {"citation_support": "maybe", "stratum": AGREE}}}
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(LabelsError, match="maybe"):
        calibration.load_labels(path)


def test_agreement_compares_labels_on_cited_sentences_with_the_judges_verdicts():
    labels = {"labels_version": 1, "kind": "citations", "run_id": "r1", "golden_version": "g", "golden_hash": "h",
              "population": {AGREE: 2, DISAGREE: 2}, "items": {
                  "a#1": {"citation_support": "supported", "note": "", "stratum": AGREE},
                  "a#2": {"citation_support": "supported", "note": "", "stratum": DISAGREE}}}
    result = calibration.agreement(labels, support_scores({"a": ["supported", "partly_supported"]}))
    d = result["dimensions"]["citation_support"]
    assert (d["n"], d["agree"], d["agreement"]) == (2, 1, 0.5)
    assert d["disagreements"] == [{"item_id": "a#2", "human": "supported", "judge": "partly_supported"}]
    assert list(result["dimensions"]) == ["citation_support"]


# --- known-bad check for citation support --------------------------------------------------------------------------

def candidates():
    return [{"key": "a#1", "item_id": "a", "question": "q", "history": [], "statement": "AMD had 31,000 employees.",
             "sources": [(1, "we had approximately 31,000 employees")]},
            {"key": "b#1", "item_id": "b", "question": "q", "history": [], "statement": "NVIDIA is based in Santa Clara, California.",
             "sources": [(1, "Our headquarters is in Santa Clara, California")]}]


def test_each_sentence_gets_the_damage_that_applies_to_it():
    cases = known_bad_citations.build_cases(candidates())
    kinds = {(c["key"], c["kind"]) for c in cases}
    assert ("a#1", "figure_changed") in kinds and ("b#1", "figure_changed") not in kinds  # no figure to change
    assert ("a#1", "date_changed") not in kinds  # no date to change
    swapped = next(c for c in cases if c["key"] == "a#1" and c["kind"] == "source_swapped")
    assert swapped["statement"] == "AMD had 31,000 employees." and swapped["sources"] == candidates()[1]["sources"]
    changed = next(c for c in cases if c["key"] == "a#1" and c["kind"] == "figure_changed")
    assert "31,000" not in changed["statement"] and changed["sources"] == candidates()[0]["sources"]
    added = next(c for c in cases if c["key"] == "b#1" and c["kind"] == "claim_added")
    assert added["statement"].startswith("NVIDIA is based in Santa Clara, California. ")


def test_markers_are_removed_from_the_statement_before_damage():
    assert known_bad_citations.clean("AMD had 31,000 employees [1][2] .") == "AMD had 31,000 employees."


def test_the_known_bad_run_judges_a_control_and_every_damaged_case():
    def script(kind, text):
        return {"reasoning": "r", "verdict": "unsupported" if "Santa Clara" in text.split("<cited_sources>")[1] and "31,000" in text.split("<statement>")[1].split("</statement>")[0] else "supported"}
    judge = Judge(FakeClient(script), model="m", cache=NoCache())
    cs = candidates()
    results = known_bad_citations.judge_cases(judge, cs, known_bad_citations.build_cases(cs))
    summary = known_bad_citations.summarize(results)
    assert summary["control"]["n"] == 2 and summary["control"]["flagged"] == 0
    assert summary["source_swapped"]["flagged"] == 1  # the 31,000 statement shown the Santa Clara source
    text = known_bad_citations.format_report(summary, {"model": "m", "think": True, "prompt_version": "1"})
    assert "source_swapped" in text and "thinking on" in text


def test_the_citation_sheet_and_calibrate_commands_work_end_to_end(tmp_path, capsys):
    golden, run = cited_run()
    run_path = runner.save_run(run, tmp_path)
    golden_path = tmp_path / "golden.json"
    golden_path.write_text(json.dumps(golden), encoding="utf-8")
    paths = []
    for name, think in (("off", False), ("on", True)):
        path = tmp_path / f"{name}.scores.json"
        path.write_text(json.dumps(support_scores({"bath": ["supported", "supported"]}, think=think, run_id=run["run_id"])), encoding="utf-8")
        paths.append(str(path))
    sheet = tmp_path / "citations.html"
    code = cli.main(["sheet", str(run_path), "--golden", str(golden_path), "--scores", paths[0], "--scores", paths[1],
                     "--citations", "--n", "2", "--out", str(sheet)])
    out = capsys.readouterr().out
    assert code == 0 and "2 cited sentences" in out and "Label the citations" in sheet.read_text(encoding="utf-8")
    labels = {"labels_version": 1, "kind": "citations", "run_id": run["run_id"], "golden_version": "g", "golden_hash": "h",
              "population": {AGREE: 2}, "items": {"bath#1": {"citation_support": "supported", "note": "", "stratum": AGREE},
                                                  "bath#2": {"citation_support": "supported", "note": "", "stratum": AGREE}}}
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps(labels), encoding="utf-8")
    code = cli.main(["calibrate", str(labels_path), "--scores", paths[0], "--scores", paths[1]])
    out = capsys.readouterr().out
    assert code == 0 and "citation_support" in out and "1.000" in out


def test_a_figure_is_changed_but_never_the_day_or_year_of_a_date():
    changed = known_bad_citations.change_figure("As of December 31, 2025, Alphabet had 190,820 employees.", ["190,820"])
    assert changed.startswith("As of December 31, 2025, Alphabet had 190,8") and "190,820" not in changed
    assert known_bad_citations.change_figure("On June 30, 2026 it was in 2025.", ["x"]) is None
    assert known_bad_citations.change_figure("Up to $60.0 billion remained.", ["$60.0 billion"]) == "Up to $77.0 billion remained."
    assert known_bad_citations.change_figure("It is based in Santa Clara.", []) is None


def test_a_date_changes_to_another_valid_day_and_only_when_there_is_one():
    for day in range(1, 32):
        changed = known_bad_citations.change_date(f"As of December {day}, 2025, it had 5 people.")
        new_day = int(changed.split("December ")[1].split(",")[0])
        assert 1 <= new_day <= 28 and new_day != day or day > 28
    assert known_bad_citations.change_date("It had 5 people in fiscal year 2026.") is None
