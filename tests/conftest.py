import json
from pathlib import Path

import pytest

from citecheck import golden, reference_review

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "golden" / "citewise_filings_v1.json"
QUESTIONS = ROOT / "golden" / "citewise_questions_v1.json"
CITEWISE_RUN = ROOT / "runs" / "published" / "2026-10-25_135415_baseline-citewise.run.json"


@pytest.fixture(scope="session")
def unreviewed(tmp_path_factory):
    """The CiteWise golden set and questions file as they were before the reference-answer review was applied.

    The published CiteWise run was asked from that version, and the commands that read a run check its golden set, so tests
    of those commands (and of applying a review) need the earlier files. They are rebuilt from the committed ones by undoing
    what apply_review wrote, and checked against the hash the run recorded.
    """
    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    data = golden.load_json(GOLDEN)
    review = questions.pop("reference_review", None)
    if review:
        before = json.loads((ROOT / review["record"]).read_text(encoding="utf-8"))["golden_version_before"]
        data["notes"] = data["notes"].replace(reference_review.review_clause(review), reference_review.review_clause(None))
        data["golden_version"] = questions["golden_version"] = before
    folder = tmp_path_factory.mktemp("unreviewed") / "golden"
    folder.mkdir()
    (folder / GOLDEN.name).write_text(reference_review.dumps(data, 2), encoding="utf-8", newline="\n")
    (folder / QUESTIONS.name).write_text(reference_review.dumps(questions, 1), encoding="utf-8", newline="\n")
    recorded = json.loads(CITEWISE_RUN.read_text(encoding="utf-8"))["golden"]
    assert reference_review.golden_hash(data) == recorded["hash"], "the undone review does not give back the golden set the run was asked from"
    return folder / GOLDEN.name, folder / QUESTIONS.name
