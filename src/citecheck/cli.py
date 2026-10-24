import argparse
import sys

from . import golden


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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="citecheck", description="Score a RAG system's retrieval, answers and citations.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("validate", help="check a golden set file")
    p.add_argument("file")
    p.set_defaults(func=cmd_validate)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
