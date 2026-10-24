"""Text comparison shared by the golden-set checks and (later) the retrieval metrics."""
import re


def normalize(text: str) -> str:
    """Lower-case, curly apostrophes straightened, whitespace collapsed.

    Same rule the RAG project's run_eval.py uses, so a phrase counts as present here exactly when it does there.
    """
    return re.sub(r"\s+", " ", text.lower().replace("’", "'")).strip()


def contains(haystack: str, phrase: str) -> bool:
    return normalize(phrase) in normalize(haystack)
