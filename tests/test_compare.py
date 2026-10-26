import json
import random
from pathlib import Path

import pytest

from citecheck import cli, compare

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ROOT / "runs" / "published"
JUDGE = {"model": "judge-model", "model_digest": "d" * 64, "prompt_version": 1, "think": True, "options": {}}


def write_arm(tmp_path, run_id, repeats, change=None, declared=None, judge=JUDGE, golden_hash="g", questions=20):
    """A judged scores file and its run file in tmp_path; `change(q, repeat)` overrides what one answer got."""
    items, records = [], []
    for repeat in range(1, repeats + 1):
        for q in range(questions):
            got = {"found": True, "faith": "supported", "corr": "correct", "abstained": False, "passages": 4,
                   **(change(q, repeat) if change else {})}
            judged = {"abstention": {"verdict": "abstained" if got["abstained"] else "answered", "error": None},
                      "correctness": {"verdict": got["corr"], "error": None}}
            if not got["abstained"]:
                judged["faithfulness"] = {"verdict": got["faith"], "error": None}
            hit = 1.0 if got["found"] else 0.0
            items.append({"item_id": f"q{q}", "repeat": repeat, "split": "tuned" if q % 2 else "heldout",
                          "category": "factual", "error": None, "expected_abstain": False, "declined": None,
                          "retrieval": {"found": got["found"], "reciprocal_rank": hit,
                                        "recall_at": {"1": hit, "3": hit, "5": hit}},
                          "judged": judged})
            records.append({"item_id": f"q{q}", "repeat": repeat, "history": [],
                            "response": {"error": None, "latency_s": 2.0, "retrieved": [{}] * got["passages"]}})
    scores = {"scores_version": 3, "run_id": run_id, "golden_version": "g1",
              "config": {"ks": [1, 3, 5], "require_doc": True, "judge": judge}, "items": items}
    run = {"run_id": run_id, "golden": {"golden_version": "g1", "hash": golden_hash},
           "target": {"name": "t", "describe": {"declared": declared or {}, "server": {"chat_model": "judge-model"}}},
           "records": records}
    (tmp_path / f"{run_id}.run.json").write_text(json.dumps(run), encoding="utf-8")
    path = tmp_path / f"{run_id}.judge.scores.json"
    path.write_text(json.dumps(scores), encoding="utf-8")
    return path


def compared(base, other, **options):
    return compare.build_comparison([compare.load_arm("A", [base]), compare.load_arm("B", [other])], **options)


def verdicts(built):
    return {name: r["verdict"] for name, r in built["comparisons"][0]["results"].items()}


# --- the rule ----------------------------------------------------------------------------------------------------

def test_t_critical_uses_the_table_entry_at_or_below_the_degrees_of_freedom():
    assert compare.t_critical(8) == 2.306
    assert compare.t_critical(22) == 2.086
    assert compare.t_critical(100) == 1.96
    with pytest.raises(ValueError):
        compare.t_critical(0)


@pytest.mark.parametrize("spread, question, known, expected", [
    (True, True, True, compare.LARGER),
    (True, False, True, compare.UNCLEAR),
    (False, True, True, compare.UNCLEAR),
    (False, False, True, compare.WITHIN),
    (None, True, True, compare.LARGER),      # the passes agreed exactly: the question test alone decides
    (None, False, True, compare.WITHIN),
    (None, True, False, compare.UNCLEAR),    # too few passes to know the spread
    (None, False, False, compare.WITHIN),
])
def test_a_difference_needs_both_tests_to_count(spread, question, known, expected):
    assert compare.verdict(spread, question, known) == expected


# --- comparing arms ----------------------------------------------------------------------------------------------

def test_arms_that_behave_the_same_are_within_noise(tmp_path):
    change = lambda q, r: {"corr": "partly_correct" if q < r % 3 else "correct"}
    built = compared(write_arm(tmp_path, "a", 5, change), write_arm(tmp_path, "b", 5, change))
    assert set(verdicts(built).values()) <= {compare.WITHIN}
    assert built["comparisons"][0]["results"]["correctness"]["difference"] == 0


def test_a_large_consistent_drop_is_larger_than_noise(tmp_path):
    a = lambda q, r: {"corr": "partly_correct" if q < r % 3 else "correct"}
    b = lambda q, r: {"corr": "incorrect" if q >= 10 else a(q, r)["corr"]}
    result = compared(write_arm(tmp_path, "a", 5, a), write_arm(tmp_path, "b", 5, b))["comparisons"][0]["results"]["correctness"]
    assert result["verdict"] == compare.LARGER
    assert result["difference"] < -0.4 and result["question_interval"][1] < 0 and result["spread_test"] is True


def test_random_differences_between_passes_are_not_larger_than_noise(tmp_path):
    rng = random.Random(7)
    flips = {arm: {(q, r): rng.random() < 0.1 for q in range(40) for r in range(1, 6)} for arm in "ab"}
    change = lambda arm: lambda q, r: {"corr": "partly_correct" if flips[arm][(q, r)] else "correct"}
    built = compared(write_arm(tmp_path, "a", 5, change("a"), questions=40), write_arm(tmp_path, "b", 5, change("b"), questions=40))
    assert verdicts(built)["correctness"] != compare.LARGER


def test_retrieval_that_never_varies_is_decided_by_the_question_test(tmp_path):
    lost = lambda q, r: {"found": q >= 10}
    built = compared(write_arm(tmp_path, "a", 5), write_arm(tmp_path, "b", 5, lost))
    result = built["comparisons"][0]["results"]["found"]
    assert result["spread_test"] is None and result["spread_threshold"] is None
    assert result["verdict"] == compare.LARGER and result["difference"] == -0.5
    assert any("identical in every pass" in note for note in built["limits"])


def test_rounding_error_between_identical_values_is_not_counted_as_spread():
    arm = lambda label, values: {"label": label, "rows": [], "passes": [
        {"measures": {"mrr": {"value": v, "n": 1, "count": None}}, "rows": []} for v in values]}
    result = compare.compare_measure(arm("A", [0.3, 0.1 + 0.2, 0.3]), arm("B", [0.5, 0.5, 0.5]), "mrr", seed=0, resamples=10)
    assert result["pooled_sd"] < compare.ZERO_SPREAD
    assert result["spread_test"] is None and result["spread_threshold"] is None


def test_a_single_pass_per_arm_can_not_be_larger_than_noise(tmp_path):
    built = compared(write_arm(tmp_path, "a", 1), write_arm(tmp_path, "b", 1, lambda q, r: {"corr": "incorrect"}))
    result = built["comparisons"][0]["results"]["correctness"]
    assert result["verdict"] == compare.UNCLEAR and result["spread_test"] is None


def test_the_bootstrap_is_reproducible_and_a_zero_difference_has_an_interval_around_zero(tmp_path):
    change = lambda q, r: {"corr": "partly_correct" if (q + r) % 4 == 0 else "correct"}
    a, b = write_arm(tmp_path, "a", 3, change), write_arm(tmp_path, "b", 3, change)
    first, second = compared(a, b, seed=3), compared(a, b, seed=3)
    assert first["comparisons"] == second["comparisons"]
    assert first["comparisons"][0]["results"]["correctness"]["question_interval"] == (0.0, 0.0)


def test_questions_that_changed_are_listed(tmp_path):
    drop = lambda q, r: {"corr": "incorrect" if q == 3 else "correct"}
    changed = compared(write_arm(tmp_path, "a", 4), write_arm(tmp_path, "b", 4, drop))["comparisons"][0]["changed_questions"]
    assert changed == [{"item_id": "q3", "measure": "correctness", "base": 1.0, "other": 0.0}]


def test_groups_report_the_split_and_category_means(tmp_path):
    drop = lambda q, r: {"corr": "incorrect" if q % 2 else "correct"}  # the odd questions are the tuned split
    comparison = compared(write_arm(tmp_path, "a", 2), write_arm(tmp_path, "b", 2, drop))["comparisons"][0]
    by_split = {g["group"]: g for g in comparison["by_split"]}
    assert by_split["tuned"]["correctness"]["difference"] == -1.0
    assert by_split["heldout"]["correctness"]["difference"] == 0.0


def test_a_declared_setting_the_target_did_not_apply_is_flagged(tmp_path):
    applied = compared(write_arm(tmp_path, "a", 2, declared={"RAG_TOP_K": "4"}),
                       write_arm(tmp_path, "b", 2, lambda q, r: {"passages": 6}, declared={"RAG_TOP_K": "6"}))
    assert [a["setting_check"]["consistent"] for a in applied["arms"]] == [True, True]
    assert applied["comparisons"][0]["other_differences"] == ["RAG_TOP_K: 4 against 6"]
    assert any("different numbers of passages" in note for note in applied["limits"])
    ignored = compared(write_arm(tmp_path, "c", 2, declared={"RAG_TOP_K": "4"}),
                       write_arm(tmp_path, "d", 2, declared={"RAG_TOP_K": "6"}))
    assert ignored["arms"][1]["setting_check"]["consistent"] is False
    assert any("may not have been applied" in note for note in ignored["limits"])


def test_several_scores_files_make_one_arm(tmp_path):
    first, second = write_arm(tmp_path, "a1", 2), write_arm(tmp_path, "a2", 3)
    arm = compare.load_arm("A", [first, second])
    assert [p["id"] for p in arm["passes"]] == ["a1#1", "a1#2", "a2#1", "a2#2", "a2#3"]


# --- refusals ----------------------------------------------------------------------------------------------------

def test_arms_made_with_a_different_judge_or_question_set_are_refused(tmp_path):
    base = write_arm(tmp_path, "a", 2)
    other_judge = write_arm(tmp_path, "b", 2, judge={**JUDGE, "think": False})
    other_golden = write_arm(tmp_path, "c", 2, golden_hash="other")
    with pytest.raises(compare.CompareError, match="judge"):
        compared(base, other_judge)
    with pytest.raises(compare.CompareError, match="golden_hash"):
        compared(base, other_golden)


def test_the_same_pass_counted_twice_is_refused(tmp_path):
    path = write_arm(tmp_path, "a", 2)
    with pytest.raises(compare.CompareError, match="appears twice"):
        compare.load_arm("A", [path, path])


def test_scores_without_a_judge_or_without_their_run_file_are_refused(tmp_path):
    path = write_arm(tmp_path, "a", 1)
    scores = json.loads(path.read_text(encoding="utf-8"))
    scores["config"]["judge"] = None
    unjudged = tmp_path / "unjudged.scores.json"
    unjudged.write_text(json.dumps(scores), encoding="utf-8")
    with pytest.raises(compare.CompareError, match="no judged scores"):
        compare.load_arm("A", [unjudged])
    (tmp_path / "a.run.json").unlink()
    with pytest.raises(compare.CompareError, match="run file"):
        compare.load_arm("A", [path])


def test_a_comparison_needs_two_arms(tmp_path):
    with pytest.raises(compare.CompareError, match="two arms"):
        compare.build_comparison([compare.load_arm("A", [write_arm(tmp_path, "a", 1)])])


# --- the saved page ----------------------------------------------------------------------------------------------

def test_the_command_writes_a_page_and_a_json_copy(tmp_path, capsys):
    a = write_arm(tmp_path, "a", 3)
    b = write_arm(tmp_path, "b", 3, lambda q, r: {"corr": "incorrect" if q >= 10 else "correct"})
    out = tmp_path / "out" / "page.md"
    code = cli.main(["compare", "--arm", f"RAG_TOP_K=4={a}", "--arm", f"RAG_TOP_K=6={b}", "--out", str(out),
                     "--resamples", "500"])
    assert code == 0
    page = out.read_text(encoding="utf-8")
    assert "## How a difference is judged" in page and "## What this cannot tell you" in page
    assert "RAG_TOP_K=6 against RAG_TOP_K=4" in page and "**larger than noise**" in page
    assert json.loads(out.with_name("page.compare.json").read_text(encoding="utf-8"))["comparisons"]
    assert "larger than noise" in capsys.readouterr().out


def test_the_command_reports_a_refusal_without_a_traceback(tmp_path, capsys):
    a, b = write_arm(tmp_path, "a", 1), write_arm(tmp_path, "b", 1, golden_hash="other")
    assert cli.main(["compare", "--arm", f"A={a}", "--arm", f"B={b}", "--out", str(tmp_path / "x.md")]) == 1
    assert "cannot compare" in capsys.readouterr().out
    assert cli.main(["compare", "--arm", "no-equals-sign", "--out", str(tmp_path / "x.md")]) == 2


def test_a_published_run_loads_and_compares_with_itself():
    path = PUBLISHED / "2026-10-24_145034_baseline-1-1.judge-think-on.scores.json"
    built = compared(path, path)
    results = built["comparisons"][0]["results"]
    assert results["found"]["base_mean"] == pytest.approx(112 / 113)
    assert results["correctness"]["difference"] == 0 and results["correctness"]["verdict"] == compare.WITHIN
    assert built["arms"][0]["setting_check"]["most_common"] == 4
    assert built["arms"][0]["setting_check"]["consistent"] is True


def test_the_committed_top_k_comparison_matches_the_published_runs():
    arms = [("RAG_TOP_K=4", "2026-10-26_102237_topk4"), ("RAG_TOP_K=6", "2026-10-26_122339_topk6"),
            ("RAG_TOP_K=2", "2026-10-26_143749_topk2")]
    built = compare.build_comparison(
        [compare.load_arm(label, [PUBLISHED / f"{run}.judge-think-on.scores.json"]) for label, run in arms],
        title="RAG_TOP_K 4 compared with 6 and 2 (rag-project, demo corpus)")
    saved = json.loads((ROOT / "reports" / "rag-project-top-k.compare.json").read_text(encoding="utf-8"))
    assert json.loads(json.dumps(built)) == saved
    assert compare.render_markdown(built) == (ROOT / "reports" / "rag-project-top-k.md").read_text(encoding="utf-8")
