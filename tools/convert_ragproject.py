"""One-off conversion of rag-project's question files into a CiteCheck golden set.

    python tools/convert_ragproject.py --rag-repo PATH_TO/rag-project

Needs pypdf (to read the demo PDF); it is not a dependency of CiteCheck itself.

What it does, and what it does not do:
  * Each `retrieval_contains` phrase is located in the corpus (demo_docs/) and stored as an evidence entry with the
    verbatim line it sits on, its heading path, and (PDFs) its page. A phrase on more than one line is an error
    unless CHOSEN or ALTERNATIVES below says what to do, so nothing is guessed silently.
  * `answer_contains` / `answer_not_contains` are carried over unchanged. They are keywords, not a reference answer.
  * `reference_answer` is read from golden/reference_answers_rag_demo_v1.json (item id -> text), written from the
    corpus documents and reviewed by hand; every item must have one, and no id may be unknown.
  * Splits come from the project's README: eval_questions.json was used to tune the prompt and thresholds (tuned),
    eval_questions_fresh.json was written afterwards and not used to tune (heldout), the PDF set is not
    described either way (unlabeled).
  * eval_questions_samples.json (a different corpus) and eval_questions_injection.json (tests resistance to
    injected instructions, not retrieval or citations) are left out.

The output is deterministic, so running this twice gives the same bytes.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from citecheck.text import contains  # noqa: E402

SOURCES = [  # (file, split)
    ("eval_questions.json", "tuned"),
    ("eval_questions_fresh.json", "heldout"),
    ("eval_questions_pdf.json", "unlabeled"),
]
CATEGORY = {"fact": "factual", "yes-no": "yes_no", "multi": "multi_topic", "edge": "edge_case",
            "follow-up": "follow_up", "unanswerable": "unanswerable"}

# (item id, original phrase) -> the phrase to use instead. The original also matches an unrelated line, so a chunk
# about that other line would count as "found".
TIGHTENED = {
    ("full-day-price", "$100.00"): "Full day (over 4 hours): $100.00",
}
# (item id, phrase) -> number of lines allowed. The fact really is stated in several places, any of which is a hit.
ALTERNATIVES = {
    ("address", "123 puppy drive, Oakland ME"): 2,
}

README_NOTES = (
    "Converted from the question files in https://github.com/Nbhaskell/rag-project by tools/convert_ragproject.py. "
    "'tuned' items were used while the prompt and thresholds were adjusted, so scores on them flatter the system. "
    "'heldout' items were written afterwards and not used to tune, but were written by Claude from the documents "
    "(per that project's README), so they are unseen by the prompt, not blind to the corpus. "
    "Every item has a reference_answer, drafted by Claude from the corpus documents and checked by hand before merging "
    "(unanswerable items say the documents do not cover the question). "
    "No item is 'ambiguous' or 'conflicting' yet."
)
REFERENCE_ANSWERS = Path(__file__).resolve().parents[1] / "golden" / "reference_answers_rag_demo_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def heading_label(line: str, state: dict):
    """Track the heading path the way rag.py's chunker does, so `section` matches the chunk labels."""
    m = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
    if not m:
        return False
    level, heading = len(m.group(1)), m.group(2).strip()
    if level == 1 and not state["title_set"]:
        state["title"], state["title_set"] = heading, True
    else:
        state["path"] = state["path"][:max(level - 2, 0)] + [heading]
    return True


def index_corpus(docs_dir: Path) -> dict:
    """doc_id -> list of (page, section, line) for every non-blank line."""
    index = {}
    for path in sorted(docs_dir.iterdir()):
        rows = []
        if path.suffix == ".md":
            state = {"title": path.stem, "title_set": False, "path": []}
            for line in path.read_text(encoding="utf-8").splitlines():
                if heading_label(line, state) or not line.strip():
                    continue
                rows.append((None, " > ".join([state["title"]] + state["path"]), line.strip()))
        elif path.suffix == ".pdf":
            for number, page in enumerate(PdfReader(str(path)).pages, 1):
                rows += [(number, "", line.strip()) for line in (page.extract_text() or "").splitlines() if line.strip()]
        else:
            continue
        index[path.name] = rows
    return index


def locate(index: dict, phrase: str) -> list:
    return [(doc, page, section, line) for doc, rows in index.items()
            for page, section, line in rows if contains(line, phrase)]


def convert_item(q: dict, split: str, source: str, index: dict, references: dict, report: list) -> dict:
    qid = q["id"]
    item = {"id": qid, "split": split, "category": CATEGORY[q["type"]], "question": q["question"]}
    if q.get("follow_up_to"):
        item["follow_up_to"] = q["follow_up_to"]
    item["expected_abstain"] = q["type"] == "unanswerable"

    phrases = q.get("retrieval_contains") or []
    phrases = [phrases] if isinstance(phrases, str) else phrases
    evidence = []
    for phrase in phrases:
        anchor = TIGHTENED.get((qid, phrase), phrase)
        if anchor != phrase:
            report.append(f"tightened   {qid}: {phrase!r} -> {anchor!r} (the original also matches another line)")
        hits = locate(index, anchor)
        allowed = ALTERNATIVES.get((qid, phrase), 1)
        if len(hits) != allowed:
            raise SystemExit(f"{source}:{qid}: {anchor!r} found on {len(hits)} line(s), expected {allowed}: {hits}")
        if allowed > 1:
            report.append(f"alternatives {qid}: {anchor!r} is stated in {', '.join(sorted({h[0] for h in hits}))}")
        evidence.append({"anchor": anchor, "passages": [
            {"doc_id": doc, "section": section, "page": page, "text": line} for doc, page, section, line in hits]})
    item["evidence"] = evidence
    if qid not in references:
        raise SystemExit(f"{source}:{qid}: no reference answer in {REFERENCE_ANSWERS.name}")
    item["reference_answer"] = references[qid]

    if q.get("expected_page") is not None:
        pages = {p["page"] for ev in evidence for p in ev["passages"]}
        if q["expected_page"] not in pages:
            raise SystemExit(f"{source}:{qid}: expected_page {q['expected_page']} but the phrase is on page(s) {sorted(pages)}")

    for key in ("answer_contains", "answer_not_contains", "expected_sources", "acceptable_sources"):
        if key in q:
            item[key] = q[key]
    if q.get("note"):
        item["notes"] = q["note"]
    item["origin"] = {"file": source, "id": qid}

    if "expected_sources" in q:
        docs = {p["doc_id"] for ev in evidence for p in ev["passages"]}
        extra = sorted(set(q["expected_sources"]) - docs)
        if extra and evidence:
            report.append(f"sources      {qid}: expected_sources lists {extra}, not among the evidence documents {sorted(docs)}")
    return item


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rag-repo", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "golden" / "rag_demo_v1.json")
    parser.add_argument("--version", default="rag-demo-1.1.0")
    args = parser.parse_args()

    repo, docs_dir = args.rag_repo, args.rag_repo / "demo_docs"
    index = index_corpus(docs_dir)
    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()

    references = json.loads(REFERENCE_ANSWERS.read_text(encoding="utf-8"))
    report, items = [], []
    for filename, split in SOURCES:
        for q in json.loads((repo / filename).read_text(encoding="utf-8")):
            items.append(convert_item(q, split, filename, index, references, report))
    unknown = sorted(set(references) - {i["id"] for i in items})
    if unknown:
        raise SystemExit(f"{REFERENCE_ANSWERS.name} has ids that are not golden items: {unknown}")

    golden = {
        "schema_version": 1,
        "golden_version": args.version,
        "target": "rag-project",
        "notes": README_NOTES,
        "corpus": {
            "name": "demo_docs",
            "source": "https://github.com/Nbhaskell/rag-project",
            "commit": commit,
            "documents": {p.name: sha256(p) for p in sorted(docs_dir.iterdir()) if p.name in index},
        },
        "items": items,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(golden, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"wrote {args.out} ({len(items)} items, corpus commit {commit[:10]})")
    for line in report:
        print("  " + line)


if __name__ == "__main__":
    main()
