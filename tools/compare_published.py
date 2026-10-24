"""Compare CiteCheck's retrieval scores with the per-question results saved in rag-project's published runs.

    python tools/compare_published.py --scores runs/X.scores.json --golden golden/rag_demo_v1.json \
        --published-dir PATH_TO/rag-project/eval_runs/published

rag-project's run_eval.py saves, for every question, whether all expected phrases were in the retrieved chunks
(`retrieval`) and the rank of the worst-placed one (`retrieval_rank`). CiteCheck's `found` and `worst_hit_rank` are meant
to be the same two numbers, so on the same index they should agree question by question. This lists every question where
they do not. Retrieval is not perfectly repeatable (a model call splits compound questions), so the published run's
repeats are shown too: a disagreement that also appears between two published repeats is noise, not a metric difference.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

PUBLISHED = {  # the question file a golden item came from -> the published run that used it
    "eval_questions.json": "2026-10-22_103530_demo-corpus.json",
    "eval_questions_fresh.json": "2026-10-22_105009_demo-corpus-fresh.json",
    "eval_questions_pdf.json": "2026-10-22_102007_pdf.json",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--scores", required=True, type=Path, nargs="+",
                        help="one or more *.scores.json files; for a question in several, the last file wins "
                             "(use it to patch in a re-run of questions that timed out)")
    parser.add_argument("--golden", required=True, type=Path)
    parser.add_argument("--published-dir", required=True, type=Path)
    args = parser.parse_args()

    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    origin = {i["id"]: i["origin"]["file"] for i in golden["items"]}

    ours = defaultdict(dict)  # file -> id -> (found, worst rank), from CiteCheck's first repeat
    for path in args.scores:
        for row in json.loads(path.read_text(encoding="utf-8"))["items"]:
            if row["repeat"] == 1 and row["retrieval"] is not None:
                r = row["retrieval"]
                ours[origin[row["item_id"]]][row["item_id"]] = (r["found"], r["worst_hit_rank"])

    total_both = total_agree = 0
    for filename, published_name in PUBLISHED.items():
        published = json.loads((args.published_dir / published_name).read_text(encoding="utf-8"))
        per_repeat = [{r["id"]: (r["retrieval"], r.get("retrieval_rank")) for r in rep["results"] if r["retrieval"] is not None}
                      for rep in published["repeats"]]
        ids = sorted(set(ours[filename]) | set(per_repeat[0]))
        agree, notes = 0, []
        for item_id in ids:
            mine, theirs = ours[filename].get(item_id), per_repeat[0].get(item_id)
            if mine is None or theirs is None:
                notes.append(f"  only on one side: {item_id}  ours={mine} published={theirs}")
            elif mine == theirs:
                agree += 1
            else:
                others = [rep.get(item_id) for rep in per_repeat[1:]]
                notes.append(f"  differs: {item_id:<32} ours (found, rank)={mine}  published repeat 1={theirs}  published repeats 2+={others}")
        both = sum(1 for i in ids if i in ours[filename] and i in per_repeat[0])
        total_both += both
        total_agree += agree
        found_ours = sum(v[0] for v in ours[filename].values())
        found_pub = sum(v[0] for v in per_repeat[0].values())
        print(f"{filename}: questions on both sides {both}, identical (found and rank) {agree}; "
              f"found: ours {found_ours}/{len(ours[filename])}, published {found_pub}/{len(per_repeat[0])}")
        for note in notes:
            print(note)
    print(f"\ntotal: {total_agree}/{total_both} identical")


if __name__ == "__main__":
    main()
