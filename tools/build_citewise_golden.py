"""Build the CiteWise golden set from golden/citewise_questions_v1.json and the filings Citewise for Markets has stored.

    python tools/build_citewise_golden.py --citewise-repo PATH_TO/stockMarket            # write the golden set
    python tools/build_citewise_golden.py --citewise-repo PATH_TO/stockMarket --check    # show what each anchor matched

The Citewise API must be running (`python -m api` in that project). Nothing here needs its database password; the
stored passages are read through GET /api/filings/search.

What it does:
  * Each fact in the question file is an anchor phrase and a company. The anchor is searched, and every returned passage
    that contains it (compared after lower-casing and collapsing whitespace) becomes evidence. A fact stated in more
    than one filing (a 10-K and a later 10-Q) gets one passage per filing, and any of them counts as a hit.
  * A fact may list `alternates`: other phrasings of the same fact in other passages. Their passages are added to the
    evidence with their own anchor, so a source that states the fact in those words counts too.
  * A document id is the title Citewise gives its sources, e.g. "NVDA 10-K filed 2026-02-25".
  * The corpus header lists every stored filing of the companies named, each with a fingerprint: the SHA-256 of
    "accession number|url". SEC filings are immutable, so this identifies the document; it does not hash its text.
  * An anchor that matches nothing stops the build, so no evidence is guessed.
  * Prices, headlines and the P/E change every night, so the set rests on filing text only.

The output depends on what the server has stored. A new filing adds documents; a changed passage changes the golden set's
hash, and saved runs then refuse to be scored against it.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from citecheck.text import contains  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "golden" / "citewise_questions_v1.json"
NOTES = (
    "Questions written by Claude from the SEC filings stored by Citewise for Markets, built by tools/build_citewise_golden.py "
    "from golden/citewise_questions_v1.json. Every item is split 'heldout': the target was not tuned on them, but they were "
    "written from the stored text, so they are unseen by the target, not blind to the corpus. Only filing text is used, "
    "because prices, headlines and the P/E change every night. Reference answers were drafted from the same text and have not yet been reviewed by a person. "
    "A document id is the title Citewise gives its sources; its fingerprint identifies the filing, not its "
    "text. Unanswerable items are things the stored filings do not state, as far as searched."
)


def get(base: str, path: str, **params):
    query = urllib.parse.urlencode(params, doseq=True)
    with urllib.request.urlopen(f"{base}{path}?{query}" if query else f"{base}{path}", timeout=300) as response:
        return json.load(response)


def doc_id(symbol: str, form: str, filed_at: str) -> str:
    return f"{symbol} {form} filed {filed_at}"


def find_passages(base: str, fact: dict) -> list[dict]:
    hits = get(base, "/api/filings/search", q=fact.get("query", fact["anchor"]), symbol=fact["symbol"], limit=20)
    found, seen = [], set()
    for hit in hits:
        if hit["symbol"] != fact["symbol"] or not contains(hit["text"], fact["anchor"]):
            continue
        key = (hit["form"], hit["filed_at"], hit["text"])
        if key in seen:
            continue
        seen.add(key)
        found.append({"doc_id": doc_id(hit["symbol"], hit["form"], hit["filed_at"]), "section": hit.get("section") or "",
                      "page": None, "text": hit["text"]})
    return sorted(found, key=lambda p: (p["doc_id"], p["text"]))


def corpus_documents(base: str, symbols: list[str]) -> dict:
    documents = {}
    for symbol in symbols:
        for filing in get(base, f"/api/stocks/{symbol}/filings"):
            fingerprint = hashlib.sha256(f"{filing['accession_number']}|{filing['url']}".encode("utf-8")).hexdigest()
            documents[doc_id(symbol, filing["form"], filing["filed_at"])] = fingerprint
    return dict(sorted(documents.items()))


def around(text: str, anchor: str, width: int = 140) -> str:
    flat = " ".join(text.split())
    index = flat.lower().find(" ".join(anchor.split()).lower())
    if index < 0:
        return flat[:width * 2]
    return flat[max(0, index - width): index + len(anchor) + width]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--citewise-repo", required=True, type=Path, help="the Citewise for Markets checkout (for its git commit)")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", type=Path, default=ROOT / "golden" / "citewise_filings_v1.json")
    parser.add_argument("--version", default="citewise-filings-1.0.0")
    parser.add_argument("--check", action="store_true", help="print what every anchor matched and write nothing")
    args = parser.parse_args()

    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    evidence_by_item, problems = {}, []
    for entry in spec["items"]:
        evidence = []
        for fact in entry["facts"]:
            passages = find_passages(args.url, fact)
            for alternate in fact.get("alternates", []):  # the same fact worded differently elsewhere
                known = {(q["doc_id"], q["text"]) for q in passages}
                for q in find_passages(args.url, {"symbol": fact["symbol"], **alternate}):
                    if (q["doc_id"], q["text"]) not in known:
                        passages.append({**q, "anchor": alternate["anchor"]})
            passages.sort(key=lambda q: (q["doc_id"], q["text"]))
            if args.check:
                docs = sorted({p["doc_id"] for p in passages})
                print(f"{entry['id']:<26}{fact['symbol']:<6}{len(passages)} passage(s) in {docs}")
                for p in passages[:1]:
                    print(f"      ...{around(p['text'], fact['anchor'])}...")
            if not passages:
                problems.append(f"{entry['id']}: no stored passage contains {fact['anchor']!r}")
            evidence.append({"anchor": fact["anchor"], "passages": passages})
        evidence_by_item[entry["id"]] = evidence
        if not args.check and entry["reference_answer"].strip() in ("", "TODO"):
            problems.append(f"{entry['id']}: reference_answer is not written")
    if problems:
        raise SystemExit("\n".join(problems))
    if args.check:
        return

    symbols = sorted({f["symbol"] for e in spec["items"] for f in e["facts"]})
    commit = subprocess.run(["git", "-C", str(args.citewise_repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()
    items = []
    for entry in spec["items"]:
        item = {"id": entry["id"], "split": "heldout", "category": entry["category"], "question": entry["question"]}
        if entry.get("follow_up_to"):
            item["follow_up_to"] = entry["follow_up_to"]
        item["expected_abstain"] = entry["category"] == "unanswerable"
        item["evidence"] = evidence_by_item[entry["id"]]
        item["reference_answer"] = entry["reference_answer"]
        for key in ("answer_contains", "answer_not_contains"):
            if entry.get(key):
                item[key] = entry[key]
        if entry.get("notes"):
            item["notes"] = entry["notes"]
        item["origin"] = {"file": SPEC.name, "id": entry["id"]}
        items.append(item)
    golden = {
        "schema_version": 1, "golden_version": args.version, "target": "citewise", "notes": NOTES,
        "corpus": {"name": "citewise-stored-filings", "source": "https://github.com/Nbhaskell/citewise-markets",
                   "commit": commit, "fingerprint": "filing-identifier",
                   "documents": corpus_documents(args.url, symbols)},
        "items": items,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(golden, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {args.out} ({len(items)} items, {len(golden['corpus']['documents'])} filings, app commit {commit[:10]})")


if __name__ == "__main__":
    main()
