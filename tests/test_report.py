import copy
import json
from pathlib import Path

import pytest

from citecheck import cli, golden, report

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ROOT / "runs" / "published"
RAG = "2026-10-24_145034_baseline-1-1"
CITEWISE = "2026-10-25_135415_baseline-citewise"


def load(name):
    return json.loads((PUBLISHED / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rag():
    run = load(f"{RAG}.run.json")
    return {"run": run, "scores": load(f"{RAG}.citations.scores.json"), "golden": golden.load_json(ROOT / run["golden"]["path"]),
            "agreement": load(f"{RAG}.agreement-with-hand-labels.json"),
            "known_bad": [load(f"{RAG}.known-bad-think-on.json"), load(f"{RAG}.known-bad-think-off.json")]}


@pytest.fixture(scope="module")
def citewise():
    run = load(f"{CITEWISE}.run.json")
    return {"run": run, "scores": load(f"{CITEWISE}.judge-think-on.scores.json"), "golden": golden.load_json(ROOT / run["golden"]["path"]),
            "agreement": load(f"{CITEWISE}.citation-agreement.json"),
            "known_bad": [load(f"{CITEWISE}.citation-known-bad-think-on.json"), load(f"{CITEWISE}.citation-known-bad-think-off.json")]}


def build(target, **overrides):
    data = {**target, **overrides}
    return report.build_report(data["run"], data["scores"], data["golden"], data["agreement"], data["known_bad"])


def metric(built, name):
    return next(r for r in built["rows"] if r["metric"].startswith(name))


# --- content -----------------------------------------------------------------------------------------------------

def test_a_report_for_a_target_that_reports_retrieval_has_a_retrieval_section(rag):
    built = build(rag)
    assert metric(built, "Every fact retrieved")["result"] == "112/113 (99%)"
    assert any(r["section"] == "Retrieval" for r in built["rows"])
    assert "## Retrieval" in report.render_markdown(built)


def test_a_target_that_does_not_report_retrieval_gets_no_retrieval_section_and_says_why(citewise):
    built = build(citewise)
    assert not any(r["section"] == "Retrieval" for r in built["rows"])
    assert any("does not report what it retrieved" in text for text in built["limits"])


def test_a_target_that_cites_whole_files_has_no_marker_rows(rag):
    built = build(rag)
    assert metric(built, "Citation style")["result"].startswith("Lists whole files")
    assert not any(r["metric"].startswith("Answers with inline markers") for r in built["rows"])
    assert metric(built, "Declined answers that still list a source")["result"] == "1/12 (8%)"


def test_a_target_that_cites_inline_has_marker_and_claim_rows_with_their_evidence(citewise):
    built = build(citewise)
    assert metric(built, "Answers with inline markers")["result"] == "38/38 (100%)"
    support = metric(built, "Cited sentences supported")
    assert support["result"].startswith("0.943: 40 supported")
    text = " ".join(support["caveats"])
    assert "Matched 26/30 (87%) of hand labels" in text and "damaged on purpose" in text and "false alarms" in text


def test_calibration_evidence_sits_beside_the_judged_scores_it_applies_to(rag):
    caveats = " ".join(metric(build(rag), "Faithfulness")["caveats"])
    assert "Matched 24/30 (80%) of hand labels" in caveats and "every hand label was `supported`" in caveats


def test_evidence_measured_with_a_different_judge_setting_is_not_borrowed(citewise):
    off_only = [{**r} for r in citewise["agreement"] if not r["judge"]["think"]]
    built = build(citewise, agreement=off_only, known_bad=[])
    assert built["calibrated"]["citations"] is False
    assert not any("Matched" in c for r in built["rows"] for c in r["caveats"])
    assert any("calibration for citations was supplied only for other judge configurations" in text.lower() for text in built["limits"])


def test_evidence_measured_on_another_run_or_with_no_run_recorded_says_so(citewise):
    other = copy.deepcopy(citewise["agreement"])
    for result in other:
        result["labels_run_id"] = "2020-01-01_000000_other"
    assert "measured on a different run, 2020-01-01_000000_other" in " ".join(metric(build(citewise, agreement=other), "Cited sentences")["caveats"])
    unrecorded = copy.deepcopy(citewise["agreement"])
    for result in unrecorded:
        result.pop("labels_run_id")
    assert "is not recorded" in " ".join(metric(build(citewise, agreement=unrecorded), "Cited sentences")["caveats"])


def test_judged_numbers_without_evidence_are_marked_unvalidated(citewise):
    built = build(citewise)
    assert any("No calibration evidence was supplied for the answer verdicts" in text for text in built["limits"])
    bare = build(citewise, agreement=[], known_bad=[])
    assert any("citation-support verdicts" in text and "unvalidated" in text for text in bare["limits"])


def test_a_report_without_a_judge_scores_only_what_needs_none(rag):
    scores = copy.deepcopy(rag["scores"])
    scores["config"]["judge"] = None
    for group in [scores["summary"]["overall"], *scores["summary"]["by_split"].values(), *scores["summary"]["by_category"].values()]:
        group.pop("answer", None)
    built = build(rag, scores=scores)
    assert built["judge"] is None and not any(r["section"] == "Answers" for r in built["rows"])
    assert any("No judge was used" in text for text in built["limits"])


def test_the_judge_sharing_the_targets_model_is_stated(rag):
    assert any("same model family" in text for text in build(rag)["limits"])


def test_a_run_from_an_uncommitted_tree_is_flagged(citewise):
    built = build(citewise)
    assert any("uncommitted working tree" in text for text in built["limits"]) == bool(citewise["run"]["citecheck"]["dirty"])


def test_items_to_look_at_give_a_reason_for_each_flag(citewise):
    looks = {i["item_id"]: i["reasons"] for i in build(citewise)["items_to_look_at"]}
    assert "correctness judged incorrect" in looks["amzn-tsla-gap"]
    assert any("declined answer still carries citation markers" in r for r in looks["unknown-tsla-chargers"])
    assert "the passage stating a fact is not among the cited sources" in looks["amd-nvda-hq"]
    assert "factual" not in {i["category"] for i in build(citewise)["items_to_look_at"] if i["item_id"] == "amd-employees"}


# --- rendering and determinism ------------------------------------------------------------------------------------

def test_the_same_inputs_give_the_same_report(rag):
    assert build(rag) == build(rag)
    assert report.render_markdown(build(rag)) == report.render_markdown(build(rag))


def test_the_page_has_the_expected_sections_in_order(citewise):
    text = report.render_markdown(build(citewise))
    order = [text.index(h) for h in ("## How to read this", "## Answers", "## Citations", "## By split and category",
                                      "## What this cannot tell you", "## Items to look at", "## Files")]
    assert order == sorted(order)


def test_table_cells_escape_pipes_and_newlines():
    lines = report.table(["a", "b"], [["x | y", "line1\nline2"], [None, ""]])
    assert lines[2] == "| x \\| y | line1 line2 |" and lines[3] == "| - | - |"


def test_the_index_lists_reports_without_ranking_them(rag, citewise):
    reports = [build(rag), build(citewise)]
    names = {r["run"]["run_id"]: f"{n}.md" for r, n in zip(reports, ("a", "b"))}
    text = report.render_index(reports, names)
    assert "not ranked and not comparable" in text and "[rag-project on rag-demo-1.1.0](a.md)" in text
    assert text.index("rag-project") < text.index("citewise")  # by run date, not by score
    assert "judge calibrated for answers" in text and "judge calibrated for citations" in text


# --- command line ------------------------------------------------------------------------------------------------

def test_report_and_index_commands_write_the_page_a_json_copy_and_the_index(tmp_path, capsys, unreviewed):
    out = tmp_path / "out" / "citewise.md"
    args = ["report", str(PUBLISHED / f"{CITEWISE}.run.json"), "--scores", str(PUBLISHED / f"{CITEWISE}.judge-think-on.scores.json"),
            "--agreement", str(PUBLISHED / f"{CITEWISE}.citation-agreement.json"),
            "--known-bad", str(PUBLISHED / f"{CITEWISE}.citation-known-bad-think-on.json"), "--golden", str(unreviewed[0]),
            "--out", str(out)]
    assert cli.main(args) == 0 and "wrote" in capsys.readouterr().out
    page = out.read_text(encoding="utf-8")
    assert page.startswith("# citewise on citewise-filings-1.0.0") and str(tmp_path) not in page  # no absolute paths
    sidecar = json.loads((tmp_path / "out" / "citewise.report.json").read_text(encoding="utf-8"))
    assert sidecar["run"]["run_id"] == CITEWISE and sidecar["report_version"] == report.REPORT_VERSION
    assert not any("was asked from" in limit for limit in sidecar["limits"])  # the run's own question set: nothing to explain
    assert cli.main(["report-index", str(tmp_path / "out")]) == 0
    assert "[citewise on citewise-filings-1.0.0](citewise.md)" in (tmp_path / "out" / "index.md").read_text(encoding="utf-8")


def test_a_report_against_a_later_question_set_needs_the_flag_and_says_which_set_it_used(tmp_path, capsys):
    out = tmp_path / "later.md"
    args = ["report", str(PUBLISHED / f"{CITEWISE}.run.json"), "--scores", str(PUBLISHED / f"{CITEWISE}.judge-think-on.scores.json"),
            "--out", str(out)]  # the golden set the run recorded is now the reviewed version
    assert cli.main(args) == 2 and "--ignore-golden-mismatch" in capsys.readouterr().out and not out.exists()
    assert cli.main(args + ["--ignore-golden-mismatch"]) == 0
    built = json.loads((tmp_path / "later.report.json").read_text(encoding="utf-8"))
    current = golden.load_json(ROOT / "golden" / "citewise_filings_v1.json")
    assert built["title"] == "citewise on " + current["golden_version"] and built["golden"]["version"] == current["golden_version"]
    assert built["golden"]["hash"] == report.golden_hash(current)
    assert any("asked from citewise-filings-1.0.0" in limit and f"reported against {current['golden_version']}" in limit
               for limit in built["limits"])


def test_the_report_command_refuses_scores_from_another_run(tmp_path, capsys, unreviewed):
    code = cli.main(["report", str(PUBLISHED / f"{CITEWISE}.run.json"), "--scores", str(PUBLISHED / f"{RAG}.citations.scores.json"),
                     "--golden", str(unreviewed[0]), "--out", str(tmp_path / "x.md")])
    assert code == 2 and "not" in capsys.readouterr().out
    assert not (tmp_path / "x.md").exists()


def test_the_index_command_stops_when_there_is_nothing_to_list(tmp_path, capsys):
    assert cli.main(["report-index", str(tmp_path)]) == 1 and "no *.report.json" in capsys.readouterr().out
