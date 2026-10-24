import argparse
import json
import sys
from pathlib import Path

from . import golden, runner, scoring
from .adapters import TARGETS
from .adapters.base import AdapterError
from .judge import DEFAULT_MODEL, Judge, JudgeCache, JudgeError, NoCache, OllamaClient


def cmd_validate(args) -> int:
    data = golden.load_json(args.file)
    problems = golden.validate(data)
    if problems:
        print(f"{args.file}: {len(problems)} problem(s)")
        for p in problems:
            print(f"  - {p}")
        return 1
    s = golden.summarize(data)
    print(f"{args.file}: OK  ({data['golden_version']}, target {data['target']})")
    print(f"  {s['items']} items, {s['retrieval_scored']} scored for retrieval")
    print("  split:    " + ", ".join(f"{k} {v}" for k, v in s["by_split"].items()))
    print("  category: " + ", ".join(f"{k} {v}" for k, v in s["by_category"].items()))
    return 0


def parse_settings(pairs) -> dict:
    settings = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise SystemExit(f"--set expects KEY=VALUE, got {pair!r}")
        settings[key] = value
    return settings


def cmd_run(args) -> int:
    if args.resume:  # the golden set and target come from the interrupted run unless overridden
        header, _ = runner.load_checkpoint(args.resume)
        golden_path = args.golden or header["golden"]["path"]
        target = args.target or header["target"]["name"]
    elif args.golden and args.target:
        golden_path, target = args.golden, args.target
    else:
        print("--golden and --target are required, unless --resume is given")
        return 2
    data = golden.load_json(golden_path)
    problems = golden.validate(data)
    if problems:
        print(f"{golden_path} is not a valid golden set ({len(problems)} problem(s)); run `citecheck validate` first")
        return 1
    adapter = TARGETS[target](url=args.url, timeout=args.timeout, declared=parse_settings(args.set))
    try:
        run = runner.run_golden(
            data, adapter, k=args.k, repeats=args.repeat, label=args.label, golden_path=golden_path,
            ids=set(args.ids.split(",")) if args.ids else None,
            splits=set(args.split.split(",")) if args.split else None,
            progress=lambda message: print(message, flush=True),
            out_dir=args.out_dir, resume_from=args.resume, retry_errors=args.retry_errors)
    except AdapterError as e:  # describe() could not reach the target at all
        print(f"cannot reach the target: {e}")
        return 1
    except ValueError as e:
        print(f"cannot resume: {e}")
        return 1
    path = runner.save_run(run, args.out_dir)
    errors = sum(bool(r["response"]["error"]) for r in run["records"])
    print(f"\nsaved {path}  ({len(run['records'])} answers, {errors} errors)")
    print(f"score it with:  citecheck score {path}")
    return 0


def cmd_score(args) -> int:
    run_path = Path(args.run)
    run = json.loads(run_path.read_text(encoding="utf-8"))
    data = golden.load_json(args.golden or run["golden"]["path"])
    try:
        scoring.check_golden(run, data)
    except scoring.GoldenMismatch as e:
        if not args.ignore_golden_mismatch:
            print(f"{e}\nScores against a different question set are not comparable. "
                  "Use --ignore-golden-mismatch to score anyway.")
            return 2
        print(f"warning: {e}")
    ks = [int(k) for k in args.ks.split(",")]
    judge = None
    if args.judge:
        judge = Judge(OllamaClient(url=args.ollama_url, timeout=args.judge_timeout, think=args.judge_think), model=args.judge_model,
                      cache=NoCache() if args.no_cache else JudgeCache(args.cache_dir))
        try:
            judge.config()  # fails now, not halfway through, when the model is missing or Ollama is down
        except JudgeError as e:
            print(f"cannot use the judge: {e}")
            return 1
    scores = scoring.score_run(run, data, ks=ks, require_doc=not args.any_document, judge=judge,
                               progress=lambda message: print(message, flush=True))
    if judge is not None:
        print(f"judge calls: {judge.calls} asked the model, {judge.cache_hits} from the cache")
    out = scoring.save_scores(scores, run_path, args.out)
    print(scoring.format_report(scores))
    print(f"\nsaved {out}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="citecheck", description="Score a RAG system's retrieval, answers and citations.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check a golden set file")
    p.add_argument("file")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("run", help="ask a target every question in a golden set and save the raw responses")
    p.add_argument("--golden", help="golden set JSON file (required unless --resume)")
    p.add_argument("--target", choices=sorted(TARGETS), help="required unless --resume")
    p.add_argument("--resume", metavar="PARTIAL_FILE",
                   help="continue an interrupted run from its runs/*.partial.jsonl; asks only what is missing")
    p.add_argument("--retry-errors", action="store_true", help="with --resume, ask again the questions that errored")
    p.add_argument("--url", default="http://127.0.0.1:8000", help="the target's base URL (default %(default)s)")
    p.add_argument("--timeout", type=float, default=300.0, help="seconds to wait for one answer (default %(default)s)")
    p.add_argument("--set", action="append", metavar="KEY=VALUE",
                   help="a target setting the harness cannot read, e.g. RAG_TOP_K=4; saved with the run (repeatable)")
    p.add_argument("--k", type=int, help="passages to retrieve, for targets that let a caller choose")
    p.add_argument("--repeat", type=int, default=1, help="ask every question this many times (default %(default)s)")
    p.add_argument("--ids", help="comma-separated item ids; a follow-up brings its parent along")
    p.add_argument("--split", help="comma-separated splits: tuned, heldout, unlabeled")
    p.add_argument("--label", default="run", help="a name for this run, used in the file name")
    p.add_argument("--out-dir", default="runs")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("score", help="compute metrics from a saved run (does not contact the target)")
    p.add_argument("run", help="a *.run.json file")
    p.add_argument("--golden", help="golden set file (default: the one the run recorded)")
    p.add_argument("--ks", default="1,3,5", help="cut-offs for recall@k (default %(default)s)")
    p.add_argument("--any-document", action="store_true",
                   help="count a chunk as a hit if it contains the anchor phrase, whatever document it is from")
    p.add_argument("--ignore-golden-mismatch", action="store_true")
    p.add_argument("--out", help="where to save the scores (default: next to the run file)")
    p.add_argument("--judge", action="store_true",
                   help="also judge abstention, faithfulness and correctness with a local model (needs Ollama)")
    p.add_argument("--judge-model", default=DEFAULT_MODEL, help="Ollama model that judges (default %(default)s)")
    p.add_argument("--judge-think", action="store_true",
                   help="let the judge model reason before it answers (slower; changes the verdicts)")
    p.add_argument("--ollama-url", default="http://127.0.0.1:11434", help="Ollama base URL (default %(default)s)")
    p.add_argument("--judge-timeout", type=float, default=300.0,
                   help="seconds to wait for one verdict (default %(default)s)")
    p.add_argument("--cache-dir", default=".cache/judge", help="where judge replies are cached (default %(default)s)")
    p.add_argument("--no-cache", action="store_true", help="ask the judge model every time and store nothing")
    p.set_defaults(func=cmd_score)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
