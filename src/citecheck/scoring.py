"""`score`: compute metrics from a saved run and its golden set. Never contacts the target."""
import json
from pathlib import Path

from .metrics import retrieval
from .models import TargetResponse
from .runner import golden_hash

SCORES_VERSION = 1
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


def score_run(run: dict, golden: dict, ks=DEFAULT_KS, require_doc: bool = True) -> dict:
    ks = sorted(set(ks))
    items = {i["id"]: i for i in golden["items"]}
    rows = []
    for record in run["records"]:
        item = items[record["item_id"]]
        response = TargetResponse.from_dict(record["response"])
        row = {"item_id": item["id"], "repeat": record["repeat"], "split": item["split"],
               "category": item["category"], "error": response.error, "retrieval": None}
        if not response.error and item["evidence"]:
            row["retrieval"] = retrieval.score_item(response.retrieved, item["evidence"], ks, require_doc)
        rows.append(row)

    def group(selected):
        scored = [r["retrieval"] for r in selected if r["retrieval"] is not None]
        return {"asked": len(selected), "errors": sum(bool(r["error"]) for r in selected),
                "retrieval": retrieval.summarize(scored, ks)}

    def by(key):
        return {value: group([r for r in rows if r[key] == value]) for value in sorted({r[key] for r in rows})}

    repeats = sorted({r["repeat"] for r in rows})
    return {
        "scores_version": SCORES_VERSION,
        "run_id": run["run_id"],
        "golden_version": run["golden"]["golden_version"],
        "config": {"ks": ks, "require_doc": require_doc},
        "summary": {
            "overall": group(rows),
            "by_split": by("split"),
            "by_category": by("category"),
            "by_repeat": [group([r for r in rows if r["repeat"] == n]) for n in repeats],
        },
        "items": rows,
    }


def save_scores(scores: dict, run_path) -> Path:
    run_path = Path(run_path)
    path = run_path.with_name(run_path.name.removesuffix(".run.json") + ".scores.json")
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
    return "\n".join(lines)
