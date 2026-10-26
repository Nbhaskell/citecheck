"""`score`: compute metrics from a saved run and its golden set. Never contacts the target."""
import json
from pathlib import Path

from .metrics import answer, citations, retrieval
from .models import TargetResponse
from .runner import golden_hash

SCORES_VERSION = 3
DEFAULT_KS = (1, 3, 5)


class GoldenMismatch(Exception):
    pass


def check_golden(run: dict, golden: dict) -> None:
    """A run is only meaningful against the golden set it was asked from."""
    expected = run["golden"]
    if golden["golden_version"] != expected["golden_version"] or golden_hash(golden) != expected["hash"]:
        raise GoldenMismatch(
            f"run {run['run_id']} was asked from {expected['golden_version']} (hash {expected['hash'][:10]}), "
            f"but this golden set is {golden['golden_version']} (hash {golden_hash(golden)[:10]})")


def should_cite(item: dict, response: TargetResponse, judged: dict | None) -> bool:
    """Citations are expected on an answer to a question the corpus answers, unless the target (or the judge) says the
    answer abstained."""
    if response.error or item["expected_abstain"] or response.abstained:
        return False
    return not (judged and judged["abstention"]["verdict"] == "abstained")


def is_declined(item: dict, response: TargetResponse, judged: dict | None) -> bool:
    """The answer declines: the question is unanswerable, or the target or the judge says it abstained."""
    if response.error:
        return False
    return bool(item["expected_abstain"] or response.abstained or (judged and judged["abstention"]["verdict"] == "abstained"))


def score_run(run: dict, golden: dict, ks=DEFAULT_KS, require_doc: bool = True, judge=None, progress=None) -> dict:
    """Retrieval and citation metrics for every answer; with a judge, also abstention, faithfulness, correctness and
    whether each cited sentence is supported by its sources. A target that does not report what it retrieved
    (describe()["reports_retrieved"] is false) gets no retrieval scores."""
    ks = sorted(set(ks))
    items = {i["id"]: i for i in golden["items"]}
    reports_retrieved = run["target"]["describe"].get("reports_retrieved", True)
    rows = []
    for record in run["records"]:
        item = items[record["item_id"]]
        history = record.get("history", ())
        response = TargetResponse.from_dict(record["response"])
        row = {"item_id": item["id"], "repeat": record["repeat"], "split": item["split"],
               "category": item["category"], "error": response.error, "retrieval": None,
               "expected_abstain": item["expected_abstain"], "judged": None, "citations": None, "declined": None}
        if reports_retrieved and not response.error and item["evidence"]:
            row["retrieval"] = retrieval.score_item(response.retrieved, item["evidence"], ks, require_doc)
        if judge is not None and not response.error:
            row["judged"] = judge.judge_item(item, response, history=history)
        if should_cite(item, response, row["judged"]):
            row["citations"] = {
                "structure": citations.structure(response.answer, response.citations),
                "evidence": citations.evidence_cited(response.citations, item["evidence"], require_doc) if item["evidence"] else None,
                "precision": citations.source_precision(response.citations, item) if item["evidence"] else None,
                "support": judge.judge_citations(item["question"], response, history=history) if judge is not None else None}
        if is_declined(item, response, row["judged"]):
            row["declined"] = {"markers": len(set(citations.markers_in(response.answer))), "listed": len(response.citations)}
        if progress and judge is not None:
            progress(f"judged {len(rows) + 1}/{len(run['records'])} {item['id']}")
        rows.append(row)

    def group(selected):
        scored = [r["retrieval"] for r in selected if r["retrieval"] is not None]
        out = {"asked": len(selected), "errors": sum(bool(r["error"]) for r in selected),
               "retrieval": retrieval.summarize(scored, ks)}
        if judge is not None:
            out["answer"] = answer.summarize([r for r in selected if r["judged"] is not None])
        out["citations"] = citations.summarize([r["citations"] for r in selected if r["citations"] is not None],
                                               [r["declined"] for r in selected if r["declined"] is not None])
        return out

    def by(key):
        return {value: group([r for r in rows if r[key] == value]) for value in sorted({r[key] for r in rows})}

    repeats = sorted({r["repeat"] for r in rows})
    return {
        "scores_version": SCORES_VERSION,
        "run_id": run["run_id"],
        "golden_version": run["golden"]["golden_version"],
        "config": {"ks": ks, "require_doc": require_doc, "judge": None if judge is None else judge.config()},
        "summary": {
            "overall": group(rows),
            "by_split": by("split"),
            "by_category": by("category"),
            "by_repeat": [group([r for r in rows if r["repeat"] == n]) for n in repeats],
        },
        "items": rows,
    }


def save_scores(scores: dict, run_path, out=None) -> Path:
    run_path = Path(run_path)
    path = Path(out) if out else run_path.with_name(run_path.name.removesuffix(".run.json") + ".scores.json")
    path.write_text(json.dumps(scores, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return path


def format_report(scores: dict) -> str:
    ks = scores["config"]["ks"]
    head = f"{'':<14}{'asked':>6}{'errors':>7}{'scored':>7}{'found':>9}  " \
           + "".join(f"{'recall@' + str(k):>9}" for k in ks) + f"{'MRR':>7}{'worst rank':>11}{'top-1':>7}"
    lines = [f"run {scores['run_id']}  |  golden {scores['golden_version']}  |  "
             f"ks {ks}, require_doc={scores['config']['require_doc']}", "", head]

    def row(name, g):
        r = g["retrieval"]
        if r["n"] == 0:
            return f"{name:<14}{g['asked']:>6}{g['errors']:>7}{0:>7}"
        worst = "-" if r["mean_worst_rank"] is None else f"{r['mean_worst_rank']:.2f}"
        return (f"{name:<14}{g['asked']:>6}{g['errors']:>7}{r['n']:>7}{str(r['found']) + '/' + str(r['n']):>9}  "
                + "".join(f"{r['mean_recall_at'][k]:>9.3f}" for k in ks) + f"{r['mrr']:>7.3f}{worst:>11}{r['top_ranked']:>7}")

    summary = scores["summary"]
    lines.append(row("overall", summary["overall"]))
    for name, g in summary["by_split"].items():
        lines.append(row(name, g))
    lines += ["", "by category"]
    for name, g in summary["by_category"].items():
        lines.append(row(name, g))
    if len(summary["by_repeat"]) > 1:
        found = [g["retrieval"].get("found", 0) for g in summary["by_repeat"]]
        lines += ["", f"found per repeat: {', '.join(map(str, found))}"]
    lines += ["", "scored = answers with evidence and no error; found = every fact retrieved; "
                  "recall@k is the mean share of facts within the first k chunks"]
    if scores["config"].get("judge") is not None:
        lines += format_answer_report(scores)
    if scores["summary"]["overall"].get("citations", {}).get("answers"):
        lines += format_citation_report(scores)
    return "\n".join(lines)


def format_citation_report(scores: dict) -> list[str]:
    judged = scores["config"].get("judge") is not None
    lines = ["", "citations (answers that should carry them: answerable questions the target did not decline)", "",
             f"{'':<14}{'answers':>8}{'markers':>9}{'dangling':>9}{'unused':>8}{'cited sent.':>12}{'evidence cited':>16}"
             f"{'source prec.':>13}" + (f"{'claims':>8}{'support':>9}" if judged else "") + f"{'declined':>10}{'+markers':>9}"]

    def row(name, g):
        c = g["citations"]
        fmt = lambda x: "-" if x is None else f"{x:.3f}"
        evidence = f"{c['evidence']['all_cited']}/{c['evidence']['n']}"
        text = (f"{name:<14}{c['answers']:>8}{c['with_markers']:>9}{c['with_dangling_marker']:>9}{c['with_unused_source']:>8}"
                f"{fmt(c['cited_sentence_share']):>12}{evidence:>16}{fmt(c['source_precision']['mean']):>13}")
        if judged:
            text += f"{c['support']['judged']:>8}{fmt(c['support']['score']):>9}"
        return text + f"{c['declined']['n']:>10}{c['declined']['with_markers']:>9}"

    summary = scores["summary"]
    lines.append(row("overall", summary["overall"]))
    for name, g in summary["by_split"].items():
        lines.append(row(name, g))
    lines += ["", "markers / dangling / unused = answers with any marker, with a marker that names no listed source, with a "
                  "listed source the answer never uses. cited sent. = mean share of sentences carrying a marker. evidence "
                  "cited = answers where every fact's passage is among the cited sources. source prec. = mean share of "
                  "cited documents that are expected. claims / support = cited sentences the judge checked, and the mean "
                  "of supported = 1, partly = 0.5 (a target that cites only whole files has no markers, so no claims). declined = answers "
                  "that decline, and +markers = how many of those still carry a citation marker."]
    return lines


def format_answer_report(scores: dict) -> list[str]:
    judge = scores["config"]["judge"]
    summary = scores["summary"]
    lines = ["", f"answer quality, judged by {judge['model']} (prompt v{judge['prompt_version']}, "
                 f"digest {judge['model_digest'][:12]})", "",
             f"{'':<14}{'judged':>7}{'faithful':>10}{'n':>5}{'correct':>9}{'n':>5}{'declined (answerable)':>23}"
             f"{'declined (unanswerable)':>25}"]

    def row(name, g):
        a = g["answer"]
        score = lambda t: "-" if t["score"] is None else f"{t['score']:.3f}"
        declined = lambda t: f"{t['abstained']}/{t['n']}"
        return (f"{name:<14}{a['judged']:>7}{score(a['faithfulness']):>10}{a['faithfulness']['n']:>5}"
                f"{score(a['correctness']):>9}{a['correctness']['n']:>5}{declined(a['abstention']['answerable']):>23}"
                f"{declined(a['abstention']['unanswerable']):>25}")

    lines.append(row("overall", summary["overall"]))
    for name, g in summary["by_split"].items():
        lines.append(row(name, g))
    lines += ["", "by category"]
    for name, g in summary["by_category"].items():
        lines.append(row(name, g))
    lines += ["", "faithful / correct: mean with supported or correct = 1, partly = 0.5, otherwise 0 (n = answers judged). "
                  "Faithfulness skips answers that abstained. Declined = the answer abstained: wrong for an answerable "
                  "question, right for an unanswerable one."]
    errors = summary["overall"]["answer"]["judge_errors"]
    if errors:
        lines.append(f"judge errors: {errors} call(s) gave no usable verdict and are left out of the averages")
    return lines
