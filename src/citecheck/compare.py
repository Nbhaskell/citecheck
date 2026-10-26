"""`compare`: do two settings of one target give different results, beyond the variation between repeated passes?

Each arm is a setting (for example `RAG_TOP_K=4`) and holds several judged passes over the same question set. Nothing
here calls a model or a target: it reads saved scores files (and the run file beside each) and arranges numbers.

Four headline measures are decided in advance; everything else is descriptive.

    found           share of questions with evidence whose every fact was retrieved
    faithfulness    mean faithfulness score of the answers that did not abstain (supported = 1, partly = 0.5)
    correctness     mean correctness score of the answerable questions (correct = 1, partly = 0.5)
    false_refusals  share of answerable questions the answer declined (lower is better)

A difference between arms counts as larger than noise only when both tests hold:

    1. spread test    the difference of the arm means exceeds the two-sided 95% t value times its standard error,
                      where the standard error comes from the spread between the passes of the two arms pooled
    2. question test  the 95% percentile interval of a paired bootstrap over questions excludes zero; each question's
                      value is its mean over the passes of an arm, and the interval covers the question-by-question
                      difference between the arms

Meeting only one is reported as unclear. When the passes of both arms agree exactly (retrieval does not vary with how
an answer is worded), the spread test has nothing to measure and the question test alone decides.
"""
import json
import math
import random
from collections import Counter
from pathlib import Path

from .metrics.answer import WEIGHTS

HEADLINE = ("found", "faithfulness", "correctness", "false_refusals")
DESCRIPTIVE = ("mrr", "recall_at_1", "recall_at_5")
MEASURES = HEADLINE + DESCRIPTIVE
COUNTED = ("found", "false_refusals")  # shown as "k/n" per pass
LABELS = {
    "found": "Every fact retrieved", "faithfulness": "Faithfulness", "correctness": "Correctness",
    "false_refusals": "Answerable questions declined (lower is better)", "mrr": "MRR", "recall_at_1": "Recall@1",
    "recall_at_5": "Recall@5",
}
LARGER, UNCLEAR, WITHIN = "larger than noise", "unclear", "within noise"
CHANGED_BY = 0.8  # a question is listed when its mean for the two arms differs by this much (4 of 5 passes, say)
LIST_LIMIT = 40
ZERO_SPREAD = 1e-9  # a pooled spread below this is rounding error on values that are in fact identical

# two-sided 95% critical values of Student's t, by degrees of freedom; between entries the lower one is used
T_CRITICAL = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
              11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
              20: 2.086, 25: 2.060, 30: 2.042}


class CompareError(Exception):
    pass


def t_critical(df: int) -> float:
    if df < 1:
        raise ValueError("no degrees of freedom")
    if df > 30:
        return 1.96
    return T_CRITICAL[max(key for key in T_CRITICAL if key <= df)]


def verdict(spread_test: bool | None, question_test: bool, spread_known: bool = True) -> str:
    """The rule in the module docstring. spread_test is None when there was no usable spread: the passes agreed
    exactly (spread_known) or there were too few passes to estimate it (not spread_known)."""
    if spread_test is None:
        if question_test:
            return LARGER if spread_known else UNCLEAR
        return WITHIN
    if spread_test and question_test:
        return LARGER
    return UNCLEAR if spread_test or question_test else WITHIN


def mean(values) -> float:
    values = list(values)
    return sum(values) / len(values)


def average(values, flat: bool = False) -> float | None:
    """Mean of a list, or None when it is empty; with flat, of the lists' items taken together."""
    if flat:
        values = [v for group in values for v in group]
    return mean(values) if values else None


def sd(values) -> float | None:
    values = list(values)
    if len(values) < 2:
        return None
    centre = mean(values)
    return math.sqrt(sum((v - centre) ** 2 for v in values) / (len(values) - 1))


# --- one pass ----------------------------------------------------------------------------------------------------

def row_measures(row: dict) -> dict:
    """The measures one scored answer contributes to; a measure is absent when the answer has nothing to say about it."""
    out = {}
    retrieval = row.get("retrieval")
    if retrieval:
        out["found"] = 1.0 if retrieval["found"] else 0.0
        out["mrr"] = retrieval["reciprocal_rank"]
        for k in (1, 5):
            if str(k) in retrieval["recall_at"]:
                out[f"recall_at_{k}"] = retrieval["recall_at"][str(k)]
    judged = row.get("judged")
    if judged:
        for name in ("faithfulness", "correctness"):
            verdict_ = judged.get(name, {}).get("verdict")
            if verdict_ is not None:
                out[name] = WEIGHTS[verdict_]
        stance = judged["abstention"]["verdict"]
        if not row["expected_abstain"] and stance is not None:
            out["false_refusals"] = 1.0 if stance == "abstained" else 0.0
    return out


def pass_measures(rows) -> dict:
    """Each measure over the rows of one pass: its value, how many answers it covers and, for rates, the count."""
    values = {name: [] for name in MEASURES}
    for row in rows:
        for name, value in row_measures(row).items():
            values[name].append(value)
    return {name: {"value": mean(vs), "n": len(vs), "count": round(sum(vs)) if name in COUNTED else None}
            for name, vs in values.items() if vs}


# --- loading -----------------------------------------------------------------------------------------------------

def load_source(path) -> tuple[dict, dict]:
    path = Path(path)
    scores = json.loads(path.read_text(encoding="utf-8"))
    if scores.get("config", {}).get("judge") is None:
        raise CompareError(f"{path.name} has no judged scores; score the run with --judge first")
    run_path = path.with_name(f"{scores['run_id']}.run.json")
    if not run_path.exists():
        raise CompareError(f"{path.name}: its run file {run_path.name} is not in the same folder")
    return scores, json.loads(run_path.read_text(encoding="utf-8"))


def load_arm(label: str, paths) -> dict:
    """The passes of one arm, from judged scores files (each may hold several repeats of one run)."""
    arm = {"label": label, "files": [], "run_ids": [], "declared": None, "describe": None, "passes": []}
    seen = set()
    for path in paths:
        scores, run = load_source(path)
        declared = run["target"]["describe"].get("declared", {})
        if arm["declared"] is not None and declared != arm["declared"]:
            raise CompareError(f"arm {label}: the runs declare different target settings ({arm['declared']} and {declared})")
        arm["declared"], arm["describe"] = declared, run["target"]["describe"]
        arm["files"].append(Path(path).name)
        arm["run_ids"].append(run["run_id"])
        arm.setdefault("fingerprint", {
            "golden_version": run["golden"]["golden_version"], "golden_hash": run["golden"]["hash"],
            "judge": scores["config"]["judge"], "ks": scores["config"]["ks"],
            "require_doc": scores["config"]["require_doc"], "scores_version": scores["scores_version"]})
        for repeat in sorted({r["repeat"] for r in scores["items"]}):
            pass_id = f"{run['run_id']}#{repeat}"
            if pass_id in seen:
                raise CompareError(f"arm {label}: pass {pass_id} appears twice (two scores files of the same run?)")
            seen.add(pass_id)
            rows = [r for r in scores["items"] if r["repeat"] == repeat]
            records = [r["response"] for r in run["records"] if r["repeat"] == repeat and not r["response"]["error"]]
            latencies = [r["latency_s"] for r in records if r.get("latency_s") is not None]
            arm["passes"].append({
                "id": pass_id, "rows": rows, "measures": pass_measures(rows),
                "passages": [len(r["retrieved"]) for r in records],
                "latency": mean(latencies) if latencies else None})
    return arm


def check_arms(arms) -> None:
    first = arms[0]
    for arm in arms:
        if not arm["passes"]:
            raise CompareError(f"arm {arm['label']} has no passes")
        for key, value in arm["fingerprint"].items():
            if value != first["fingerprint"][key]:
                raise CompareError(f"arm {arm['label']} differs from {first['label']} in {key}: {value!r} against "
                                   f"{first['fingerprint'][key]!r}; scores made that way are not comparable")
    questions = {frozenset(r["item_id"] for r in p["rows"]) for arm in arms for p in arm["passes"]}
    if len(questions) != 1:
        raise CompareError("the passes do not all cover the same questions")


# --- comparing ---------------------------------------------------------------------------------------------------

def per_question(arm: dict, name: str) -> dict:
    """Each question's mean of one measure over the passes of an arm."""
    values: dict[str, list[float]] = {}
    for p in arm["passes"]:
        for row in p["rows"]:
            m = row_measures(row)
            if name in m:
                values.setdefault(row["item_id"], []).append(m[name])
    return {q: mean(vs) for q, vs in values.items()}


def bootstrap_interval(diffs: list[float], seed: int, resamples: int) -> tuple[float, float] | None:
    if not diffs:
        return None
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(resamples))
    return means[int(0.025 * resamples)], means[math.ceil(0.975 * resamples) - 1]


def compare_measure(base: dict, other: dict, name: str, seed: int, resamples: int) -> dict | None:
    a = [p["measures"][name]["value"] for p in base["passes"] if name in p["measures"]]
    b = [p["measures"][name]["value"] for p in other["passes"] if name in p["measures"]]
    if not a or not b:
        return None
    difference = mean(b) - mean(a)
    df = len(a) + len(b) - 2
    pooled = se = threshold = t = None
    spread_test = None
    if df >= 1:
        pooled = math.sqrt((sum((x - mean(a)) ** 2 for x in a) + sum((x - mean(b)) ** 2 for x in b)) / df)
        if pooled > ZERO_SPREAD:
            se = pooled * math.sqrt(1 / len(a) + 1 / len(b))
            t, threshold = difference / se, t_critical(df) * se
            spread_test = abs(difference) > threshold
    base_q, other_q = per_question(base, name), per_question(other, name)
    shared = sorted(set(base_q) & set(other_q))
    diffs = [other_q[q] - base_q[q] for q in shared]
    interval = bootstrap_interval(diffs, seed, resamples)
    question_test = interval is not None and (interval[0] > 0 or interval[1] < 0)
    return {
        "measure": name, "base": a, "other": b, "base_mean": mean(a), "other_mean": mean(b),
        "base_sd": sd(a), "other_sd": sd(b), "difference": difference, "pooled_sd": pooled, "df": df,
        "standard_error": se, "t": t, "spread_threshold": threshold, "spread_test": spread_test,
        "questions": len(shared), "question_mean_difference": mean(diffs) if diffs else None,
        "question_interval": interval, "question_test": question_test,
        "verdict": verdict(spread_test, question_test, spread_known=df >= 1)}


def grouped(base: dict, other: dict, key: str) -> list[dict]:
    """Headline means of both arms for each split or category: descriptive, with no verdict."""
    names = sorted({row[key] for p in base["passes"] for row in p["rows"]})
    out = []
    for group in names:
        entry = {"group": group, "questions": len({row["item_id"] for p in base["passes"] for row in p["rows"] if row[key] == group})}
        for name in HEADLINE:
            means = []
            for arm in (base, other):
                vs = [m[name]["value"] for p in arm["passes"]
                      if (m := pass_measures([r for r in p["rows"] if r[key] == group])) and name in m]
                means.append(mean(vs) if vs else None)
            entry[name] = {"base": means[0], "other": means[1],
                           "difference": None if None in means else means[1] - means[0]}
        out.append(entry)
    return out


def changed_questions(base: dict, other: dict) -> list[dict]:
    out = []
    for name in HEADLINE:
        a, b = per_question(base, name), per_question(other, name)
        for q in sorted(set(a) & set(b)):
            if abs(b[q] - a[q]) >= CHANGED_BY:
                out.append({"item_id": q, "measure": name, "base": a[q], "other": b[q]})
    return out


def setting_check(arm: dict) -> dict:
    """Whether the passages returned per answer fit the declared RAG_TOP_K: a mismatch means the setting was
    recorded but not applied."""
    counts = Counter(n for p in arm["passes"] for n in p["passages"])
    if not counts:
        return {"most_common": None, "answers": 0, "declared": None, "consistent": None}
    (common, times), = counts.most_common(1)
    declared = arm["declared"].get("RAG_TOP_K")
    consistent = None if declared is None or not str(declared).isdigit() else int(declared) == common
    return {"most_common": common, "times": times, "answers": sum(counts.values()), "declared": declared,
            "consistent": consistent}


def describe_differences(base: dict, other: dict) -> list[str]:
    keys = sorted(set(base["declared"]) | set(other["declared"]))
    found = [f"{k}: {base['declared'].get(k)} against {other['declared'].get(k)}" for k in keys
             if base["declared"].get(k) != other["declared"].get(k)]
    a, b = base["describe"].get("server", {}), other["describe"].get("server", {})
    found += [f"server {k}: {a.get(k)} against {b.get(k)}" for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
    return found


def build_comparison(arms, title: str = "Comparison of settings", seed: int = 0, resamples: int = 10000) -> dict:
    """arms: loaded arms, the first being the baseline that every other is compared with."""
    if len(arms) < 2:
        raise CompareError("a comparison needs at least two arms")
    check_arms(arms)
    base = arms[0]
    first = base["fingerprint"]
    built = {
        "title": title, "seed": seed, "resamples": resamples, "golden": {k: first[k] for k in ("golden_version", "golden_hash")},
        "judge": first["judge"],
        "arms": [{
            "label": a["label"], "files": a["files"], "run_ids": a["run_ids"], "declared": a["declared"],
            "passes": [{"id": p["id"], "measures": p["measures"], "latency": p["latency"],
                        "mean_passages": mean(p["passages"]) if p["passages"] else None} for p in a["passes"]],
            "mean_passages": average([p["passages"] for p in a["passes"] if p["passages"]], flat=True),
            "mean_latency": average([p["latency"] for p in a["passes"] if p["latency"] is not None]),
            "setting_check": setting_check(a)} for a in arms],
        "comparisons": []}
    for other in arms[1:]:
        results = {name: compare_measure(base, other, name, seed, resamples) for name in MEASURES}
        built["comparisons"].append({
            "base": base["label"], "other": other["label"], "results": {k: v for k, v in results.items() if v},
            "by_split": grouped(base, other, "split"), "by_category": grouped(base, other, "category"),
            "changed_questions": changed_questions(base, other), "other_differences": describe_differences(base, other)})
    built["limits"] = limits(arms, built)
    return built


def limits(arms, built) -> list[str]:
    base = arms[0]
    notes = [
        "Each arm is a block of passes run one after another, not interleaved with the other arms, so a change in the "
        "machine over time is not separated from the setting.",
        "The spread between passes covers variation in the answers (and the judge's reading of them) only. It does not "
        "cover other questions, another corpus or another judge.",
        "Rows for the `tuned` split come from questions the system was adjusted against; `heldout` rows are the fairer read.",
        "The judge's agreement with hand labels was measured on an earlier run, not on these answers.",
        f"{len(HEADLINE)} headline measures are compared per pair of arms, so one borderline result in {len(HEADLINE)} is "
        "expected by chance about once in five comparisons; an isolated `unclear` is not a finding.",
    ]
    chat = base["describe"].get("server", {}).get("chat_model")
    if chat and chat == built["judge"].get("model"):
        notes.append(f"The judge is the same model as the one answering ({chat}), which may favour its own style.")
    passages = [mean(p["passages"]) for a in arms for p in a["passes"] if p["passages"]]
    if passages and max(passages) - min(passages) >= 0.5:
        notes.append("The arms return different numbers of passages, and faithfulness is judged against the passages "
                     "returned, so a faithfulness difference is not between like-for-like checks.")
    if any(c["results"].get("found") and c["results"]["found"]["pooled_sd"] == 0 for c in built["comparisons"]):
        notes.append("Retrieval was identical in every pass within each arm, so for it the only uncertainty is which "
                     "questions were asked, and the question test alone decides.")
    for a in built["arms"]:
        if a["setting_check"]["consistent"] is False:
            notes.append(f"Arm {a['label']}: RAG_TOP_K={a['setting_check']['declared']} was declared but the most common "
                         f"number of passages per answer is {a['setting_check']['most_common']}; the setting may not have "
                         "been applied to the target.")
    return notes


# --- rendering ---------------------------------------------------------------------------------------------------

def fmt(value, places: int = 3) -> str:
    return "-" if value is None else f"{value:.{places}f}"


def signed(value, places: int = 3) -> str:
    return "-" if value is None else f"{value:+.{places}f}"


def cell(pass_: dict, name: str) -> str:
    m = pass_["measures"].get(name)
    if m is None:
        return "-"
    return f"{m['count']}/{m['n']}" if name in COUNTED else fmt(m["value"])


def table(header, rows) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"] + \
           ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]


def render_markdown(built: dict) -> str:
    judge = built["judge"]
    lines = [f"# {built['title']}", "",
             "Settings of one target compared over repeated passes of the same question set. Every number is arranged from "
             "saved scores files; no model is called to make this page.", "", "## Provenance", ""]
    def passages(a):
        check = a["setting_check"]
        common = "" if check["most_common"] is None else f" (most common {check['most_common']}, {check['times']} of {check['answers']})"
        return fmt(a["mean_passages"], 2) + common

    lines += table(["Arm", "Declared settings", "Passes", "Runs", "Passages per answer", "Seconds per answer"], [
        [a["label"], ", ".join(f"{k}={v}" for k, v in sorted(a["declared"].items())) or "-", len(a["passes"]),
         ", ".join(f"`{r}`" for r in a["run_ids"]), passages(a), fmt(a["mean_latency"], 1)]
        for a in built["arms"]])
    lines += ["", f"Question set `{built['golden']['golden_version']}` (hash `{built['golden']['golden_hash'][:10]}`). Judge "
              f"`{judge['model']}` (digest `{judge['model_digest'][:12]}`, prompt version {judge['prompt_version']}), identical "
              "for every pass. Seconds per answer depend on the machine and are descriptive only.", "",
              "## How a difference is judged", "",
              "A difference between an arm and the first arm counts as **larger than noise** only when both tests hold:", "",
              "1. **Spread test.** The difference of the arm means is larger than the 95% t value times its standard error, "
              "where the standard error comes from the spread between passes (the two arms pooled).",
              f"2. **Question test.** The 95% interval of a paired bootstrap over questions ({built['resamples']} resamples, seed "
              f"{built['seed']}) excludes zero. Each question's value is its mean over an arm's passes.", "",
              "Meeting one test gives **unclear**, neither gives **within noise**. Where the passes agree exactly there is no "
              "spread to measure and the question test alone decides. The four headline measures were chosen before any result "
              "was seen; the others are descriptive.", ""]
    for comparison in built["comparisons"]:
        lines += [f"## {comparison['other']} against {comparison['base']}", ""]
        if comparison["other_differences"]:
            lines += ["Differences recorded between the two targets: " + "; ".join(comparison["other_differences"]) + ".", ""]
        base = next(a for a in built["arms"] if a["label"] == comparison["base"])
        other = next(a for a in built["arms"] if a["label"] == comparison["other"])
        lines += ["### Every pass", ""]
        lines += table(["Measure", f"{comparison['base']}, per pass", f"{comparison['other']}, per pass"], [
            [LABELS[n], ", ".join(cell(p, n) for p in base["passes"]), ", ".join(cell(p, n) for p in other["passes"])]
            for n in MEASURES if n in comparison["results"]])
        lines += ["", "### Result", ""]
        rows = []
        for name in MEASURES:
            r = comparison["results"].get(name)
            if not r:
                continue
            interval = "-" if r["question_interval"] is None else f"{signed(r['question_interval'][0])} to {signed(r['question_interval'][1])}"
            threshold = "no spread to measure" if r["spread_threshold"] is None else f"±{fmt(r['spread_threshold'])}"
            if name in HEADLINE:
                rows.append([LABELS[name], f"{fmt(r['base_mean'])} ({fmt(r['base_sd'])})", f"{fmt(r['other_mean'])} ({fmt(r['other_sd'])})",
                             signed(r["difference"]), interval, threshold, f"**{r['verdict']}**"])
            else:
                rows.append([LABELS[name] + " (descriptive)", f"{fmt(r['base_mean'])} ({fmt(r['base_sd'])})",
                             f"{fmt(r['other_mean'])} ({fmt(r['other_sd'])})", signed(r["difference"]), interval, threshold, "-"])
        lines += table(["Measure", f"{comparison['base']} mean (SD)", f"{comparison['other']} mean (SD)", "Difference",
                        "95% interval over questions", "Spread test needs more than", "Verdict"], rows)
        lines += ["", "The interval is for the question-by-question difference (each question's mean over passes), so its centre can "
                      "differ slightly from the difference of the pass means when the passes cover different numbers of answers.", ""]
        for title, key in (("By split (descriptive)", "by_split"), ("By category (descriptive)", "by_category")):
            lines += [f"### {title}", ""]
            lines += table(["Group", "Questions"] + [f"{LABELS[n].split(' (')[0]}: {comparison['base']} / {comparison['other']} / difference"
                                                      for n in HEADLINE],
                           [[g["group"], g["questions"]] + [
                               f"{fmt(g[n]['base'])} / {fmt(g[n]['other'])} / {signed(g[n]['difference'])}" for n in HEADLINE]
                            for g in comparison[key]])
            lines.append("")
        changed = comparison["changed_questions"]
        lines += ["### Questions that changed", "",
                  f"Questions whose mean for a headline measure differs by {CHANGED_BY} or more between the arms. A reading list, "
                  "not a count of failures."]
        if changed:
            lines += ["", f"{len(changed)} listed" + (f", the first {LIST_LIMIT} shown" if len(changed) > LIST_LIMIT else ""), ""]
            lines += table(["Question", "Measure", comparison["base"], comparison["other"]],
                           [[f"`{c['item_id']}`", LABELS[c["measure"]].split(" (")[0], fmt(c["base"], 2), fmt(c["other"], 2)]
                            for c in changed[:LIST_LIMIT]])
        else:
            lines += ["", "None."]
        lines.append("")
    lines += ["## What this cannot tell you", ""] + [f"- {note}" for note in built["limits"]]
    return "\n".join(lines) + "\n"


def save_comparison(built: dict, out) -> tuple[Path, Path]:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(built), encoding="utf-8", newline="\n")
    sidecar = out.with_name(out.name.removesuffix(".md") + ".compare.json")
    sidecar.write_text(json.dumps(built, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return out, sidecar
