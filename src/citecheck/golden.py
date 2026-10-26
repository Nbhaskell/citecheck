"""Loading and checking a golden set.

validate() returns a list of problems (empty means the file is usable). It runs the JSON Schema first, then the
rules a schema cannot express: ids are unique, follow-ups point at real items, and every gold passage is
consistent with its anchor and with the corpus listed in the header.
"""
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .text import contains

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "golden" / "schema.json"


def load_json(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_schema() -> dict:
    return load_json(SCHEMA_PATH)


def schema_problems(golden: dict, schema: dict) -> list[str]:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(golden), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors]


def cross_item_problems(golden: dict) -> list[str]:
    problems = []
    docs = set(golden["corpus"]["documents"])
    items = golden["items"]
    by_id = {}
    for item in items:
        if item["id"] in by_id:
            problems.append(f"{item['id']}: id appears more than once")
        by_id[item["id"]] = item

    for item in items:
        name = item["id"]
        parent = item.get("follow_up_to")
        if parent is not None:
            if parent == name:
                problems.append(f"{name}: follow_up_to points at itself")
            elif parent not in by_id:
                problems.append(f"{name}: follow_up_to {parent!r} is not an item")
            elif by_id[parent].get("follow_up_to") is not None:
                problems.append(f"{name}: follow_up_to {parent!r}, which is itself a follow-up (chains are not supported)")
            elif items.index(by_id[parent]) > items.index(item):
                problems.append(f"{name}: follow_up_to {parent!r} comes later in the file")
        for key in ("expected_sources", "acceptable_sources"):
            for doc in item.get(key, []):
                if doc not in docs:
                    problems.append(f"{name}: {key} names {doc!r}, which is not in corpus.documents")
        for ev in item["evidence"]:
            for passage in ev["passages"]:
                if passage["doc_id"] not in docs:
                    problems.append(f"{name}: passage doc_id {passage['doc_id']!r} is not in corpus.documents")
                anchor = passage.get("anchor", ev["anchor"])
                if not contains(passage["text"], anchor):
                    problems.append(f"{name}: anchor {anchor!r} does not occur in its passage {passage['text'][:50]!r}")
    return problems


def validate(golden: dict, schema: dict | None = None) -> list[str]:
    problems = schema_problems(golden, schema or load_schema())
    if problems:  # the cross-item rules assume the structure is right
        return problems
    return cross_item_problems(golden)


def summarize(golden: dict) -> dict:
    """Counts for a one-glance report: items per split and category, and how many are scored for retrieval."""
    items = golden["items"]
    count = lambda key: {k: sum(i[key] == k for i in items) for k in sorted({i[key] for i in items})}
    return {
        "items": len(items),
        "by_split": count("split"),
        "by_category": count("category"),
        "retrieval_scored": sum(bool(i["evidence"]) for i in items),
    }
