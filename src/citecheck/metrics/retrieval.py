"""Retrieval metrics: did the target fetch the passages the answer depends on, and how high did it rank them?

No model is involved, so every number here is deterministic given the retrieved chunks.

Vocabulary. An item's `evidence` is a list of facts; each fact has an `anchor` phrase and the passage(s) that state it.
A chunk *matches* a fact when it contains the anchor (compared after lower-casing and collapsing whitespace) and, by
default, comes from a document that states the fact. Matching on text rather than on chunk ids is what lets the same
golden set score targets that chunk differently.

    fact rank       rank of the best-ranked chunk that matches the fact (None: no chunk does)
    found           every fact has a rank, i.e. the published "retrieval found the fact"
    recall@k        share of facts with rank <= k
    reciprocal rank 1 / rank of the first chunk matching any fact (0 if none): MRR is its mean over items
    worst rank      the lowest-placed fact's rank when all are found (rag-project's "rank of the fact")
    precision@k     share of the first k chunks that match some fact. The denominator is the number of chunks the
                    target actually returned when that is fewer than k, so a target that returns 4 is not
                    punished at k=5. A chunk can be useful without containing the anchor, so this understates.
"""
from collections.abc import Iterable, Sequence

from ..models import RetrievedChunk
from ..text import contains


def chunk_matches(chunk: RetrievedChunk, fact: dict, require_doc: bool = True) -> bool:
    if not contains(chunk.text, fact["anchor"]):
        return False
    return not require_doc or chunk.doc_id in {p["doc_id"] for p in fact["passages"]}


def fact_ranks(chunks: Sequence[RetrievedChunk], evidence: Sequence[dict], require_doc: bool = True) -> list[int | None]:
    """Rank of the best-ranked matching chunk for each fact, over everything the target returned."""
    ranks = []
    for fact in evidence:
        hits = [c.rank for c in chunks if chunk_matches(c, fact, require_doc)]
        ranks.append(min(hits) if hits else None)
    return ranks


def score_item(chunks: Sequence[RetrievedChunk], evidence: Sequence[dict], ks: Iterable[int], require_doc: bool = True) -> dict:
    """All retrieval numbers for one answer. `evidence` must not be empty."""
    if not evidence:
        raise ValueError("score_item needs at least one evidence entry")
    ordered = sorted(chunks, key=lambda c: c.rank)
    ranks = fact_ranks(ordered, evidence, require_doc)
    hit_ranks = [r for r in ranks if r is not None]
    first = min(hit_ranks) if hit_ranks else None
    found = len(hit_ranks) == len(ranks)

    recall_at, found_at, precision_at = {}, {}, {}
    for k in ks:
        within = [r for r in hit_ranks if r <= k]
        recall_at[k] = len(within) / len(ranks)
        found_at[k] = len(within) == len(ranks)
        top = ordered[:k]
        relevant = sum(any(chunk_matches(c, fact, require_doc) for fact in evidence) for c in top)
        precision_at[k] = relevant / len(top) if top else 0.0

    return {
        "n_facts": len(ranks),
        "n_chunks": len(ordered),
        "fact_ranks": ranks,
        "found": found,
        "first_hit_rank": first,
        "worst_hit_rank": max(hit_ranks) if found else None,
        "reciprocal_rank": 1 / first if first else 0.0,
        "recall_at": recall_at,
        "found_at": found_at,
        "precision_at": precision_at,
    }


def summarize(scores: Sequence[dict], ks: Iterable[int]) -> dict:
    """Aggregate score_item results. `scores` holds only scored answers (no errors, no items without evidence)."""
    ks = list(ks)
    n = len(scores)
    if n == 0:
        return {"n": 0}
    mean = lambda values: sum(values) / len(values)
    worst = [s["worst_hit_rank"] for s in scores if s["worst_hit_rank"] is not None]
    return {
        "n": n,
        "found": sum(s["found"] for s in scores),
        "found_at": {k: sum(s["found_at"][k] for s in scores) for k in ks},
        "top_ranked": sum(s["worst_hit_rank"] == 1 for s in scores),
        "mrr": mean([s["reciprocal_rank"] for s in scores]),
        "mean_recall_at": {k: mean([s["recall_at"][k] for s in scores]) for k in ks},
        "mean_precision_at": {k: mean([s["precision_at"][k] for s in scores]) for k in ks},
        "mean_worst_rank": mean(worst) if worst else None,
        "mean_chunks": mean([s["n_chunks"] for s in scores]),
    }
