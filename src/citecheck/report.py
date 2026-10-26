"""The report: one Markdown page per scored run, built from a data structure so it can be tested and re-rendered.

A report is built from a run file, a scores file and, when they exist, the calibration evidence for the judge that produced
the scores (agreement with hand labels, known-bad checks). Every score sits in a table row beside the evidence and the known
weaknesses that bear on it, and a closing block says what the numbers cannot tell the reader. Nothing in a report is computed
by a model: it only arranges numbers already saved in those files, and it is deterministic, so the same inputs give the same
page. A JSON copy of the data is saved next to the page and is what the index reads.

Calibration evidence applies only to the judge configuration it was measured with (model, reasoning on or off, prompt
version). A report for a different configuration says so instead of borrowing it.
"""
from collections import Counter

REPORT_VERSION = 1
JUDGE_KEYS = ("model", "think", "prompt_version")

# Weaknesses that bear on a metric whatever the data, each worded as a fact about the method.
WEAKNESS = {
    "retrieval": "Deterministic. It follows the target's own ranking and says nothing about whether retrieval is good.",
    "abstention": "An off-topic answer is usually read as a refusal, so it skips the faithfulness check; correctness still flags it.",
    "faithfulness": "The judge leans strict: it can call a claim that a passage states outright partly supported.",
    "correctness": "The judge can penalise extra detail that the reference does not contain, and can miss a contradicted opening.",
    "markers": "Applies to targets that cite inline. A target that lists only files has no markers.",
    "evidence": "Strict: an answer that cites another passage stating the same fact counts as missing it unless that wording "
                "is listed in the golden set as an alternate.",
    "precision": "Expected documents are the golden set's evidence documents and any listed alternates.",
    "support": "The judge saw each excerpt without the title of the filing it came from, and can judge a sentence on "
               "whether it answers the question, which it is told not to do. Small figure changes and changed dates are often missed.",
}


def fraction(part: int, whole: int) -> str:
    return "none" if whole == 0 else f"{part}/{whole} ({100 * part / whole:.0f}%)"


def number(value, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def same_judge(a: dict | None, b: dict | None) -> bool:
    return a is not None and b is not None and all(a.get(k) == b.get(k) for k in JUDGE_KEYS)


def kind_of_known_bad(data: dict) -> str:
    return "citations" if "figure_changed" in data["summary"] or "source_swapped" in data["summary"] else "answers"


def kind_of_agreement(result: dict) -> str:
    return "citations" if "citation_support" in result["dimensions"] else "answers"


def calibration_evidence(judge: dict | None, agreements: list, known_bad: list) -> dict:
    """Pick the evidence measured with this judge configuration. Evidence supplied for a kind (answers or citations) but
    measured only with other configurations is listed under "unmatched"."""
    evidence = {"answers": {}, "citations": {}, "unmatched": []}
    if judge is None:
        return evidence
    supplied = {}
    for result in agreements:
        kind = kind_of_agreement(result)
        supplied.setdefault(kind, []).append(("agreement with hand labels", result["judge"]))
        if same_judge(judge, result["judge"]):
            evidence[kind]["agreement"] = result
    for data in known_bad:
        kind = kind_of_known_bad(data)
        supplied.setdefault(kind, []).append(("known-bad check", data["judge"]))
        if same_judge(judge, data["judge"]):
            evidence[kind]["known_bad"] = data
    for kind, entries in supplied.items():
        if not evidence[kind]:
            others = "; ".join(sorted({f"{name} with {describe_judge(j)}" for name, j in entries}))
            evidence["unmatched"].append(f"calibration for {kind} was supplied only for other judge configurations ({others})")
    return evidence


def describe_judge(judge: dict) -> str:
    return f"{judge['model']}, reasoning {'on' if judge['think'] else 'off'}, prompt v{judge['prompt_version']}"


def provenance(entry: dict, run_id: str, field: str) -> str:
    """Words for where a piece of calibration evidence was measured, when that is not this run."""
    measured_on = entry.get(field)
    if measured_on is None:
        return " (the run it was measured on is not recorded)"
    return "" if measured_on == run_id else f" (measured on a different run, {measured_on})"


def agreement_caveat(evidence: dict, dimension: str, run_id: str) -> str | None:
    result = evidence.get("agreement")
    if not result or dimension not in result["dimensions"]:
        return None
    d = result["dimensions"][dimension]
    if not d["n"]:
        return None
    human_labels = {pair.split(" -> ")[0] for pair in d["confusion"]}
    text = f"Matched {fraction(d['agree'], d['n'])} of hand labels, from a sample chosen to be hard"
    if len(human_labels) == 1:
        text += f"; every hand label was `{next(iter(human_labels))}`, so the labels cannot show whether the judge catches a bad one"
    return text + provenance(result, run_id, "labels_run_id") + "."


def known_bad_caveat(evidence: dict, dimension: str, run_id: str) -> str | None:
    data = evidence.get("known_bad")
    if not data:
        return None
    flagged = total = 0
    citation_check = "figure_changed" in data["summary"]
    for kind, entry in data["summary"].items():
        if kind == "control":
            continue
        if citation_check:  # the citation check has no per-dimension breakdown
            flagged, total = flagged + entry["flagged"], total + entry["n"] - entry["judge_errors"]
        elif dimension in entry.get("dimensions", {}):
            flagged, total = flagged + entry["dimensions"][dimension]["flagged"], total + entry["dimensions"][dimension]["n"]
    control = data["summary"].get("control", {})
    if citation_check:
        control = {"n": control.get("n", 0) - control.get("judge_errors", 0), "flagged": control.get("flagged", 0)}
    else:
        control = control.get("dimensions", {}).get(dimension, {})
    if not total:
        return None
    noun = "cited sentences" if citation_check else "answers"
    text = f"Flagged {fraction(flagged, total)} of {noun} damaged on purpose"
    if control.get("n"):
        text += f" and {fraction(control['flagged'], control['n'])} of unchanged good ones (false alarms)"
    return text + provenance(data, run_id, "run_id") + "."


def row(section: str, metric: str, result: str, n, caveats: list) -> dict:
    return {"section": section, "metric": metric, "result": result, "n": n, "caveats": [c for c in caveats if c]}


def build_rows(scores: dict, evidence: dict, reports_retrieved: bool, run_id: str) -> list[dict]:
    overall = scores["summary"]["overall"]
    rows = []
    retrieval = overall["retrieval"]
    if reports_retrieved and retrieval["n"]:
        rows += [
            row("Retrieval", "Every fact retrieved (found)", fraction(retrieval["found"], retrieval["n"]), retrieval["n"], [WEAKNESS["retrieval"]]),
            row("Retrieval", "Mean recall at the first 1 / 3 / 5 chunks",
                " / ".join(number(retrieval["mean_recall_at"][k]) for k in ("1", "3", "5") if k in retrieval["mean_recall_at"])
                or " / ".join(number(v) for v in retrieval["mean_recall_at"].values()), retrieval["n"], []),
            row("Retrieval", "Mean reciprocal rank", number(retrieval["mrr"]), retrieval["n"], [])]
    answer = overall.get("answer")
    if answer:
        un, an = answer["abstention"]["unanswerable"], answer["abstention"]["answerable"]
        abstention_evidence = [agreement_caveat(evidence["answers"], "abstention", run_id), known_bad_caveat(evidence["answers"], "abstention", run_id)]
        rows += [
            row("Answers", "Unanswerable questions declined (right)", fraction(un["abstained"], un["n"]), un["n"], [WEAKNESS["abstention"]] + abstention_evidence),
            row("Answers", "Answerable questions declined (false refusals)", fraction(an["abstained"], an["n"]), an["n"], [])]
        faithfulness, correctness = answer["faithfulness"], answer["correctness"]
        rows += [
            row("Answers", "Faithfulness (supported = 1, partly = 0.5)",
                f"{number(faithfulness['score'])}: {faithfulness['supported']} supported, {faithfulness['partly_supported']} partly, "
                f"{faithfulness['unsupported']} unsupported", faithfulness["n"],
                [WEAKNESS["faithfulness"], agreement_caveat(evidence["answers"], "faithfulness", run_id), known_bad_caveat(evidence["answers"], "faithfulness", run_id)]),
            row("Answers", "Correctness against the reference answer",
                f"{number(correctness['score'])}: {correctness['correct']} correct, {correctness['partly_correct']} partly, "
                f"{correctness['incorrect']} incorrect", correctness["n"],
                [WEAKNESS["correctness"], agreement_caveat(evidence["answers"], "correctness", run_id), known_bad_caveat(evidence["answers"], "correctness", run_id)])]
    c = overall.get("citations")
    if c and c["answers"]:
        support = c["support"]
        inline = c["with_markers"] > 0
        if inline:
            rows += [
                row("Citations", "Answers with inline markers", fraction(c["with_markers"], c["answers"]), c["answers"], [WEAKNESS["markers"]]),
                row("Citations", "Answers with a dangling marker / an unused source",
                    f"{c['with_dangling_marker']} / {c['with_unused_source']}", c["answers"], []),
                row("Citations", "Mean share of sentences that carry a marker", number(c["cited_sentence_share"]), c["answers"], [])]
        else:
            rows.append(row("Citations", "Citation style", "Lists whole files; no inline markers", c["answers"],
                            ["Marker, dangling-marker, unused-source and claim-support checks need inline markers, so they do not apply."]))
        rows += [
            row("Citations", "Every fact's passage among the cited sources", fraction(c["evidence"]["all_cited"], c["evidence"]["n"]),
                c["evidence"]["n"], [WEAKNESS["evidence"]] + ([] if c["evidence"]["text_checked"] else
                                                               ["No excerpts were available, so this was matched on the document alone."])),
            row("Citations", "Mean share of cited documents that are expected", number(c["source_precision"]["mean"]),
                c["source_precision"]["n"], [WEAKNESS["precision"]])]
        if support["judged"]:
            rows.append(row("Citations", "Cited sentences supported by their sources (supported = 1, partly = 0.5)",
                            f"{number(support['score'])}: {support['supported']} supported, {support['partly_supported']} partly, "
                            f"{support['unsupported']} unsupported", support["judged"],
                            [WEAKNESS["support"], agreement_caveat(evidence["citations"], "citation_support", run_id),
                             known_bad_caveat(evidence["citations"], "citation_support", run_id)]))
        if inline:
            rows.append(row("Citations", "Declined answers that still carry citation markers",
                            fraction(c["declined"]["with_markers"], c["declined"]["n"]), c["declined"]["n"], []))
        else:
            rows.append(row("Citations", "Declined answers that still list a source",
                            fraction(c["declined"]["with_listed_sources"], c["declined"]["n"]), c["declined"]["n"], []))
    return rows


def group_rows(scores: dict, key: str, reports_retrieved: bool) -> list[dict]:
    rows = []
    for name, g in scores["summary"][key].items():
        entry = {"group": name, "asked": g["asked"], "errors": g["errors"]}
        if reports_retrieved and g["retrieval"]["n"]:
            entry["found"] = fraction(g["retrieval"]["found"], g["retrieval"]["n"])
        if g.get("answer"):
            f, k = g["answer"]["faithfulness"], g["answer"]["correctness"]
            entry["faithfulness"] = None if f["score"] is None else f"{f['score']:.2f} (n={f['n']})"
            entry["correctness"] = None if k["score"] is None else f"{k['score']:.2f} (n={k['n']})"
        c = g.get("citations")
        if c and c["answers"]:
            entry["evidence_cited"] = fraction(c["evidence"]["all_cited"], c["evidence"]["n"]) if c["evidence"]["n"] else None
            entry["support"] = None if c["support"]["score"] is None else f"{c['support']['score']:.2f} (n={c['support']['judged']})"
        rows.append(entry)
    return rows


def items_to_look_at(scores: dict, reports_retrieved: bool) -> list[dict]:
    flagged = []
    for r in scores["items"]:
        reasons = []
        if r["error"]:
            reasons.append(f"the target returned an error: {r['error']}")
        if reports_retrieved and r["retrieval"] and not r["retrieval"].get("found", True):
            reasons.append("a fact the question depends on was not retrieved")
        j = r["judged"] or {}
        if j.get("abstention") and j["abstention"]["verdict"] == "abstained" and not r["expected_abstain"]:
            reasons.append("declined a question the documents answer")
        if j.get("abstention") and j["abstention"]["verdict"] == "answered" and r["expected_abstain"]:
            reasons.append("answered a question the documents do not cover")
        if j.get("faithfulness") and j["faithfulness"]["verdict"] not in (None, "supported"):
            reasons.append(f"faithfulness judged {j['faithfulness']['verdict'].replace('_', ' ')}")
        if j.get("correctness") and j["correctness"]["verdict"] not in (None, "correct"):
            reasons.append(f"correctness judged {j['correctness']['verdict'].replace('_', ' ')}")
        c = r.get("citations")
        if c:
            if c["structure"]["dangling"]:
                reasons.append(f"dangling marker(s) {c['structure']['dangling']}")
            if c["evidence"] and c["evidence"]["all_cited"] is False:
                reasons.append("the passage stating a fact is not among the cited sources")
            bad = [u for u in (c["support"] or []) if u["verdict"] not in (None, "supported")]
            if bad:
                reasons.append(f"{len(bad)} cited sentence(s) judged less than supported")
        if r.get("declined") and r["declined"]["markers"]:
            reasons.append("a declined answer still carries citation markers")
        if reasons:
            flagged.append({"item_id": r["item_id"], "category": r["category"], "reasons": reasons})
    return flagged


def build_limits(run: dict, scores: dict, golden: dict, evidence: dict, reports_retrieved: bool) -> list[str]:
    judge = scores["config"].get("judge")
    limits = []
    if golden.get("notes"):
        limits.append(f"About the question set: {golden['notes']}")
    if run["citecheck"].get("dirty"):
        limits.append("The run was made from an uncommitted working tree, so the recorded commit is the previous one, not the exact code.")
    repeats = len({r["repeat"] for r in run["records"]})
    limits.append(f"This is {'one pass' if repeats == 1 else f'{repeats} passes'} over the question set. Answers vary from run to run, "
                  "and a model target gives no seed, so a difference of a few answers is not evidence of a real change.")
    if not reports_retrieved:
        limits.append("This target does not report what it retrieved, so retrieval is not scored; faithfulness is checked against "
                      "the sources it cited, which is weaker than checking against everything the model read.")
    if judge is None:
        limits.append("No judge was used, so only retrieval and the structure of the citations are scored.")
    else:
        target_model = str(run["target"]["describe"].get("server", {}).get("chat_model") or run["target"]["describe"].get("server", {}).get("ai_model") or "")
        base = judge["model"].split(":")[0]
        if base and base in target_model:
            limits.append(f"The judge ({judge['model']}) and the target answer with the same model family ({target_model}), so the judge "
                          "may favour its own kind of answer. The calibration checks measure agreement with a person and with known "
                          "damage; they do not rule that out.")
        answers_scored = scores["summary"]["overall"].get("answer") is not None
        citations_scored = (scores["summary"]["overall"].get("citations") or {}).get("support", {}).get("judged", 0) > 0
        if answers_scored and not evidence["answers"]:
            limits.append(f"No calibration evidence was supplied for the answer verdicts (abstention, faithfulness, correctness) with "
                          f"this judge configuration ({describe_judge(judge)}), so they are unvalidated here.")
        if citations_scored and not evidence["citations"]:
            limits.append(f"No calibration evidence was supplied for the citation-support verdicts with this judge configuration "
                          f"({describe_judge(judge)}), so they are unvalidated here.")
        for item in evidence["unmatched"]:
            limits.append(item[0].upper() + item[1:] + ", so it is not used.")
        limits.append("Where the tables show hand-label agreement, read it as an estimate for hard cases from a small sample, not a "
                      "measured error rate.")
        single = [kind for kind in ("answers", "citations") if evidence[kind].get("agreement") and all(
            len({pair.split(" -> ")[0] for pair in d["confusion"]}) == 1
            for d in evidence[kind]["agreement"]["dimensions"].values() if d["n"])]
        if single:
            limits.append("In the hand labels for " + " and ".join(single) + ", every label in each dimension was the same, so they cannot "
                          "show whether the judge catches a bad one; the known-bad check, where shown, covers that.")
    return limits


def build_report(run: dict, scores: dict, golden: dict, agreements=(), known_bad=(), sources: dict | None = None) -> dict:
    judge = scores["config"].get("judge")
    reports_retrieved = run["target"]["describe"].get("reports_retrieved", True)
    evidence = calibration_evidence(judge, list(agreements), list(known_bad))
    return {
        "report_version": REPORT_VERSION,
        "title": f"{run['target']['name']} on {run['golden']['golden_version']}",
        "run": {"run_id": run["run_id"], "label": run.get("label"), "created": run["created"], "citecheck": run["citecheck"],
                "python": run.get("python")},
        "target": {"name": run["target"]["name"], "describe": run["target"]["describe"]},
        "golden": {"version": run["golden"]["golden_version"], "hash": run["golden"]["hash"], "items": len(golden["items"]),
                   "splits": dict(Counter(i["split"] for i in golden["items"])),
                   "categories": dict(Counter(i["category"] for i in golden["items"]))},
        "judge": judge,
        "calibrated": {kind: bool(evidence[kind]) for kind in ("answers", "citations")},
        "rows": build_rows(scores, evidence, reports_retrieved, run["run_id"]),
        "by_split": group_rows(scores, "by_split", reports_retrieved),
        "by_category": group_rows(scores, "by_category", reports_retrieved),
        "items_to_look_at": items_to_look_at(scores, reports_retrieved),
        "limits": build_limits(run, scores, golden, evidence, reports_retrieved),
        "sources": sources or {},
    }


def table(headers: list[str], rows: list[list]) -> list[str]:
    cell = lambda v: "-" if v in (None, "") else str(v).replace("|", "\\|").replace("\n", " ")
    return ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"] + \
           ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows]


def render_group(title: str, rows: list[dict]) -> list[str]:
    columns = [("asked", "asked"), ("errors", "errors"), ("found", "found"), ("faithfulness", "faithful"), ("correctness", "correct"),
               ("evidence_cited", "evidence cited"), ("support", "claim support")]
    present = [(k, h) for k, h in columns if any(k in r for r in rows)]
    return [f"### {title}", ""] + table(["group"] + [h for _, h in present], [[r["group"]] + [r.get(k) for k, _ in present] for r in rows]) + [""]


def render_markdown(report: dict) -> str:
    run, golden, judge = report["run"], report["golden"], report["judge"]
    server = report["target"]["describe"].get("server", {})
    lines = [f"# {report['title']}", "",
             f"Run `{run['run_id']}`, made {run['created']} with citecheck {str(run['citecheck'].get('commit'))[:10]}"
             f"{' (uncommitted changes)' if run['citecheck'].get('dirty') else ''}. "
             f"Question set `{golden['version']}` ({golden['items']} items), hash `{golden['hash'][:12]}`.", ""]
    if server:
        lines += ["Target: " + ", ".join(f"{k} {v}" for k, v in server.items() if not isinstance(v, (list, dict))) + ".", ""]
    declared = report["target"]["describe"].get("declared")
    if declared:
        lines += ["Settings the target does not report, recorded by hand: " + ", ".join(f"{k}={v}" for k, v in declared.items()) + ".", ""]
    lines += ["Judge: " + (describe_judge(judge) + f", model digest `{judge['model_digest'][:12]}`." if judge else "none for this report."), ""]
    lines += ["## How to read this", "",
              "Each score sits beside what is known about how far to trust it. Retrieval and the structure of the citations are "
              "counted from the target's own output. Faithfulness, correctness, abstention and claim support are a model's verdicts "
              "and are only as good as the calibration shown next to them. Nothing here compares this target with another: the "
              "question sets, corpora and checks differ.", ""]
    for section in ("Retrieval", "Answers", "Citations"):
        rows = [r for r in report["rows"] if r["section"] == section]
        if rows:
            lines += [f"## {section}", ""] + table(["Metric", "Result", "n", "Evidence and caveats"],
                                                    [[r["metric"], r["result"], r["n"], " ".join(r["caveats"])] for r in rows]) + [""]
    lines += ["## By split and category", ""] + render_group("By split", report["by_split"]) + render_group("By category", report["by_category"])
    lines += ["## What this cannot tell you", ""] + [f"- {text}" for text in report["limits"]] + [""]
    looks = report["items_to_look_at"]
    lines += [f"## Items to look at ({len(looks)})", "",
              "Every question with something unusual in its result. This is a reading list, not a failure count: a flag from the "
              "judge may be the judge's mistake.", ""]
    lines += table(["Item", "Category", "Why"], [[f"`{i['item_id']}`", i["category"], "; ".join(i["reasons"])] for i in looks]) if looks else ["None."]
    lines += ["", "## Files", ""] + [f"- {name}: `{path}`" for name, path in report["sources"].items()] + [""]
    return "\n".join(lines)


def render_index(reports: list[dict], names: dict) -> str:
    lines = ["# Reports", "",
             "One report per scored run. They are not ranked and not comparable with each other: each uses its own question set, "
             "corpus and target, and some checks apply to one target and not another. Read each report's own caveats.", ""]
    rows = []
    for report in sorted(reports, key=lambda r: (r["run"]["created"], r["title"])):
        calibrated = report["calibrated"]
        status = ("no judge" if report["judge"] is None else
                  "judge calibrated for " + (" and ".join(k for k, v in calibrated.items() if v) or "nothing"))
        rows.append([f"[{report['title']}]({names[report['run']['run_id']]})", report["run"]["created"][:10], report["target"]["name"],
                     f"{report['golden']['version']} ({report['golden']['items']})", status])
    return "\n".join(lines + table(["Report", "Run date", "Target", "Question set (items)", "Judge"], rows) + [""])
