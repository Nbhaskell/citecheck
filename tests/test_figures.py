import json
from pathlib import Path

import pytest

from citecheck import cli, known_bad_figures, scoring
from citecheck.metrics import figures

from test_citations import cited_run

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ROOT / "runs" / "published"


def texts(text):
    return [f["text"] for f in figures.extract(text)]


def kinds(text):
    return {f["text"]: f["kind"] for f in figures.extract(text)}


# --- what counts as a figure -------------------------------------------------------------------------------------

def test_money_numbers_and_scales_are_figures():
    assert texts("A bath is $50.00, 1,576,000 people, 6.8 million square feet, 12%.") == [
        "$50.00", "1,576,000", "6.8 million", "12"]


def test_dates_are_one_figure_however_they_are_written():
    for text in ("December 31, 2025", "Dec. 31, 2025", "31 December 2025", "2025-12-31", "december 31 2025"):
        found = figures.extract(f"As of {text}, 5 dogs.")
        assert [f["kind"] for f in found] == ["date", "number"], text
        assert found[0]["keys"] == [("date", 2025, 12, 31)], text


def test_times_of_day_are_figures_and_compare_on_a_twelve_hour_clock():
    found = figures.extract("Open 8:30am to 6:00 PM, closing at 18:00 or 6pm.")
    assert [f["keys"] for f in found] == [[("time", 8, 30)], [("time", 6, 0)], [("time", 6, 0)], [("time", 6, 0)]]


def test_markers_list_numbering_form_names_and_codes_are_not_figures():
    assert texts("AMD had 31,000 employees [1][3]. See the 10-K and Form 8-K.") == ["31,000"]
    assert texts("Reasons:\n1. Aggression\n2. Resource guarding\n  10. Other") == []
    assert texts("The H100 and Q3 results, 4.2 hours.") == ["4.2"]


def test_a_decimal_is_not_split_and_a_year_is_a_number():
    assert texts("Founded in 1969; rate $0.26 per share.") == ["1969", "$0.26"]


# --- grounding ---------------------------------------------------------------------------------------------------

def check(answer, sources, context=()):
    return figures.check(answer, sources, context)


def test_a_figure_in_the_sources_is_grounded_whatever_its_format():
    assert check("A bath is $50.", ["Bath: $50.00"])["ungrounded"] == []
    assert check("$44.0 billion remained.", ["remaining: 44,000 million"])["ungrounded"] == []
    assert check("It is 1,576,000.", ["we employ 1576000 people"])["ungrounded"] == []


def test_a_figure_in_no_source_is_ungrounded():
    result = check("A bath is $60.00 and nails are $30.", ["Bath: $50.00. Nails: $30.00"])
    assert (result["n"], result["ungrounded"]) == (2, ["$60.00"])


def test_a_date_must_match_in_full_and_a_changed_day_is_ungrounded():
    sources = ["As of Dec. 31, 2025, we had 5,000 employees."]
    assert check("As of December 31, 2025, 5,000 employees.", sources)["ungrounded"] == []
    assert check("As of December 22, 2025, 5,000 employees.", sources)["ungrounded"] == ["December 22, 2025"]


def test_the_year_of_a_source_date_grounds_the_same_year_stated_alone():
    assert check("In fiscal 2025 it grew.", ["As of December 31, 2025 it grew."])["ungrounded"] == []


def test_a_time_must_match_and_am_pm_is_not_told_apart():
    assert check("Pickup by 6:00pm.", ["Closing time is 6 pm."])["ungrounded"] == []
    assert check("Pickup by 7:00pm.", ["Closing time is 6 pm."])["ungrounded"] == ["7:00pm"]


def test_the_question_and_earlier_turns_ground_a_figure_too():
    assert check("Three nights is $375.", ["Nightly: $125"], context=["How much for three nights?"])["ungrounded"] == ["$375"]
    assert check("For 3 nights.", ["Nightly: $125"], context=["How much for three nights?"])["ungrounded"] == []
    assert check("Yes, $125 a night.", [], context=["Is it $125 a night?"])["ungrounded"] == []


# --- the lenient tier --------------------------------------------------------------------------------------------

def test_a_sum_product_or_quotient_of_source_numbers_is_derivable():
    sources = ["Full day $100.00. Second dog $50.00. Overnight $125.00. Package of 10 days $800."]
    for stated in ("$150", "$375 for 3 nights", "$1,000 for 10 days", "$200 saved", "$80 per day"):
        result = check(f"The total is {stated}.", sources, context=["For 3 nights and 10 days?"])
        assert result["ungrounded"] and result["underived"] == [], stated


def test_a_figure_no_arithmetic_on_the_sources_explains_stays_underived():
    result = check("A bath is $62.00.", ["Bath: $50.00. Nails: $30.00."])
    assert result["ungrounded"] == result["underived"] == ["$62.00"]


def test_trivial_operands_do_not_explain_a_figure_one_step_away():
    result = check("The fee is $51.", ["Bath: $50.00. One bath."])
    assert result["underived"] == ["$51"]


def test_dates_and_times_are_never_derived():
    result = check("As of December 22, 2025.", ["December 20, 2025 and 2 days"])
    assert result["underived"] == ["December 22, 2025"]


def test_the_lenient_tier_can_miss_a_changed_figure_that_equals_a_sum():
    # $150 is the changed figure here, and it happens to be $100 plus $50 from the same passage
    result = check("A bath is $150.", ["Bath: $100.00. Add-on: $50.00."])
    assert result["ungrounded"] == ["$150"] and result["underived"] == []


def test_summaries_count_answers_and_figures():
    checks = [check("No figures here.", ["x"]), check("It is $50.", ["$50"]), check("It is $62 and $30.", ["$50, $30"]),
              check("$150.", ["$100, $50"])]
    s = figures.summarize(checks)
    assert s == {"answers": 4, "with_figures": 3, "all_grounded": 1, "all_derivable": 2, "figures": 4,
                 "ungrounded": 2, "underived": 1}


# --- in a scored run ---------------------------------------------------------------------------------------------

def test_a_scored_run_checks_the_figures_of_answers_that_were_not_declined():
    golden, run = cited_run()
    run["target"]["describe"]["reports_retrieved"] = False  # the sources are the cited excerpts
    scores = scoring.score_run(run, golden)
    rows = {r["item_id"]: r for r in scores["items"]}
    assert scores["scores_version"] == 4
    assert rows["bath"]["figures"] == {"n": 1, "ungrounded": [], "underived": []}
    # an answer that cites nothing has no source for its figure
    assert rows["and-nails"]["figures"] == {"n": 1, "ungrounded": ["$30"], "underived": ["$30"]}
    assert rows["cats"]["figures"] is None  # declined answers are not checked
    overall = scores["summary"]["overall"]["figures"]
    assert (overall["answers"], overall["with_figures"], overall["all_grounded"], overall["ungrounded"]) == (2, 2, 1, 1)
    run["records"][0]["response"]["answer"] = "A bath at the daycare costs $65.00 [1]. Nail trims are priced separately [2]."
    changed = scoring.score_run(run, golden)
    assert {r["item_id"]: r["figures"]["ungrounded"] for r in changed["items"] if r["figures"]}["bath"] == ["$65.00"]
    assert "figure grounding" in scoring.format_report(changed)


# --- the damage measurement --------------------------------------------------------------------------------------

def test_swapping_a_figure_uses_a_different_figure_from_the_sources():
    swapped = known_bad_figures.swap_figure("A bath is $50.00 and nails take 15 minutes.",
                                            ["Bath: $50.00. Nails: $30.00. Full day: $100.00. 15 minutes."])
    assert swapped == "A bath is $30.00 and nails take 15 minutes."  # nearest different figure that the text lacks
    assert figures.check(swapped, ["Bath: $50.00. Nails: $30.00. Full day: $100.00. 15 minutes."])["ungrounded"] == []


def test_swapping_skips_dates_and_needs_another_figure_to_offer():
    assert known_bad_figures.swap_figure("As of December 31, 2025.", ["December 31, 2025 and $40"]) is None
    assert known_bad_figures.swap_figure("A bath is $50.00.", ["Bath: $50.00."]) is None
    assert known_bad_figures.swap_figure("No figures.", ["$40, $60"]) is None


def test_the_published_known_bad_sets_give_the_figures_the_check_is_meant_to_catch():
    run = json.loads((PUBLISHED / "2026-10-25_135415_baseline-citewise.run.json").read_text(encoding="utf-8"))
    golden = json.loads((ROOT / run["golden"]["path"]).read_text(encoding="utf-8"))
    labels = json.loads((ROOT / "labels" / "citewise_filings_v1.citation-labels.json").read_text(encoding="utf-8"))
    results = known_bad_figures.evaluate_sentences(run, golden, labels)
    summary = known_bad_figures.summarize(results, known_bad_figures.SENTENCE_KINDS)
    assert summary["control"]["n"] == 30 and summary["control"]["underived"] == 0
    assert summary["date_changed"]["not_found"] == summary["date_changed"]["n"] == 10
    assert summary["figure_changed"]["not_found"] == summary["figure_changed"]["n"] == 18
    assert summary["figure_swapped"]["not_found"] == 0


def test_judge_flags_are_read_from_both_kinds_of_saved_result():
    answers = {"cases": [
        {"item_id": "a", "kind": "number_changed", "verdicts": {"faithfulness": "partly_supported", "correctness": "correct"}, "errors": []},
        {"item_id": "b", "kind": "number_changed", "verdicts": {"faithfulness": "supported", "correctness": "correct"}, "errors": []},
        {"item_id": "c", "kind": "number_changed", "verdicts": {}, "errors": ["timed out"]}]}
    sentences = {"cases": [{"key": "x#1", "kind": "date_changed", "verdict": "supported", "error": None},
                           {"key": "x#2", "kind": "date_changed", "verdict": "unsupported", "error": None}]}
    assert known_bad_figures.judge_flags(answers) == {("a", "number_changed"): True, ("b", "number_changed"): False}
    assert known_bad_figures.judge_flags(sentences) == {("x#1", "date_changed"): False, ("x#2", "date_changed"): True}


def test_the_command_prints_the_table_and_saves_the_cases(tmp_path, capsys):
    out = tmp_path / "figure-check.json"
    code = cli.main(["figure-check", str(PUBLISHED / "2026-10-25_135415_baseline-citewise.run.json"),
                     "--labels", str(ROOT / "labels" / "citewise_filings_v1.citation-labels.json"),
                     "--judge-results", str(PUBLISHED / "2026-10-25_135415_baseline-citewise.citation-known-bad-think-on.json"),
                     "--out", str(out)])
    assert code == 0
    assert "date_changed" in capsys.readouterr().out
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["scope"] == "cited sentences" and saved["summary"]["date_changed"]["judge"]["flagged"] == 2


def test_a_report_shows_figure_grounding_only_when_the_scores_have_it():
    from citecheck import golden as golden_module, report
    run = json.loads((PUBLISHED / "2026-10-24_145034_baseline-1-1.run.json").read_text(encoding="utf-8"))
    data = golden_module.load_json(ROOT / run["golden"]["path"])
    scores = scoring.score_run(run, data)
    grounding = lambda: [r["result"] for r in report.build_report(run, scores, data)["rows"]
                         if r["metric"].startswith(("Answers whose every figure", "The same, also accepting"))]
    assert grounding() == ["89/95 (94%)", "95/95 (100%)"]
    del scores["summary"]["overall"]["figures"]
    assert grounding() == []
