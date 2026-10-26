"""Citation metrics: are the citations an answer carries real, and do they point at the right places?

No model is involved in this module; the judge's per-sentence support verdicts are counted here but decided in judge/.

Vocabulary. A target cites in one of two ways. Inline: the answer text has markers like [2] or [3][6], and each marker
names a listed source (CiteWise). File level: the answer has no markers and the target only lists the documents it used
(rag-project). The checks below say which of them need markers.

    dangling marker    a marker in the answer that matches no listed source
    unused source      a listed source whose marker the answer never uses
    cited share        the share of an answer's sentences that carry at least one marker
    evidence cited     a fact the question depends on counts as cited when a listed source comes from a document that
                       states it and, when the target gives the excerpt, the excerpt contains the fact's anchor phrase
    source precision   the share of distinct cited documents that are expected (the evidence documents, plus the item's
                       expected_sources and acceptable_sources)
    claim support      the judge's verdict on whether the sources cited for one sentence support that sentence
"""
import re
from collections.abc import Sequence

from ..models import Citation
from ..text import contains
from .retrieval import passage_anchor

MARKER = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'*(\[])")
MIN_SENTENCE = 25  # shorter fragments (headings, a lone figure) are not counted as claims
WEIGHTS = {"supported": 1.0, "partly_supported": 0.5, "unsupported": 0.0}


def markers_in(text: str) -> list[int]:
    """Every marker number in the order it appears, repeats included; [1, 2] counts as 1 and 2."""
    return [int(n) for m in MARKER.finditer(text) for n in re.split(r"\s*[,;]\s*", m.group(1))]


def sentences(text: str) -> list[str]:
    """Sentences long enough to be a claim. Markers stay attached to the sentence they end."""
    parts = []
    for line in text.splitlines():
        parts += SENTENCE_END.split(line.strip())
    return [p.strip() for p in parts if len(MARKER.sub("", p).strip()) >= MIN_SENTENCE]


def listed_markers(citations: Sequence[Citation]) -> set[int]:
    return {int(c.marker) for c in citations if c.marker is not None and c.marker.isdigit()}


def structure(answer: str, citations: Sequence[Citation]) -> dict:
    cited, listed = set(markers_in(answer)), listed_markers(citations)
    claims = sentences(answer)
    with_marker = [s for s in claims if MARKER.search(s)]
    return {
        "markers": sorted(cited), "listed": sorted(listed),
        "dangling": sorted(cited - listed), "unused": sorted(listed - cited),
        "sentences": len(claims), "cited_sentences": len(with_marker),
        "uncited": [s for s in claims if not MARKER.search(s)],
    }


def evidence_cited(citations: Sequence[Citation], evidence: Sequence[dict], require_doc: bool = True) -> dict:
    """Which of the item's facts a listed source covers. text_checked is False when no source gave its excerpt, so the
    match could only be made on the document."""
    text_checked = any(c.text for c in citations)
    covered = []
    for fact in evidence:
        covered.append(any(
            (not require_doc or c.doc_id == p["doc_id"]) and (c.text is None or contains(c.text, passage_anchor(fact, p)))
            for c in citations for p in fact["passages"]))
    return {"facts": len(evidence), "cited": sum(covered), "all_cited": all(covered) if covered else None,
            "text_checked": text_checked}


def source_precision(citations: Sequence[Citation], item: dict) -> dict:
    cited = {c.doc_id for c in citations}
    allowed = ({p["doc_id"] for fact in item["evidence"] for p in fact["passages"]}
               | set(item.get("expected_sources", [])) | set(item.get("acceptable_sources", [])))
    return {"documents": len(cited), "expected": len(cited & allowed),
            "precision": None if not cited else round(len(cited & allowed) / len(cited), 4)}


def claim_units(answer: str, citations: Sequence[Citation]) -> list[dict]:
    """The sentences that carry markers, each with the excerpts of the sources it cites. Markers with no listed source,
    and sources without an excerpt, are reported so the judge is never asked about a source it cannot see."""
    by_marker = {int(c.marker): c for c in citations if c.marker is not None and c.marker.isdigit()}
    units = []
    for sentence in sentences(answer):
        numbers = list(dict.fromkeys(markers_in(sentence)))
        if not numbers:
            continue
        units.append({"sentence": sentence, "markers": numbers,
                      "missing": [n for n in numbers if n not in by_marker or not by_marker[n].text],
                      "sources": [(n, by_marker[n].text) for n in numbers if n in by_marker and by_marker[n].text]})
    return units


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarize(rows: Sequence[dict], declined: Sequence[dict] = ()) -> dict:
    """rows: one per answer that should carry citations, each {"structure", "evidence", "precision", "support"}; evidence,
    precision and support are None where they do not apply. declined: one {"markers", "listed"} per answer that declined,
    to count declines that still carry citations."""
    structured = [r["structure"] for r in rows]
    evidence = [r["evidence"] for r in rows if r["evidence"] and r["evidence"]["facts"]]
    precision = [r["precision"]["precision"] for r in rows if r["precision"] and r["precision"]["precision"] is not None]
    verdicts = [u["verdict"] for r in rows for u in (r["support"] or [])]
    judged = [v for v in verdicts if v is not None]
    return {
        "answers": len(rows),
        "declined": {"n": len(declined), "with_markers": sum(d["markers"] > 0 for d in declined),
                     "with_listed_sources": sum(d["listed"] > 0 for d in declined)},
        "with_markers": sum(bool(s["markers"]) for s in structured),
        "with_dangling_marker": sum(bool(s["dangling"]) for s in structured),
        "with_unused_source": sum(bool(s["unused"]) for s in structured),
        "cited_sentence_share": _mean([s["cited_sentences"] / s["sentences"] for s in structured if s["sentences"]]),
        "evidence": {"n": len(evidence), "all_cited": sum(bool(e["all_cited"]) for e in evidence),
                     "mean_share_cited": _mean([e["cited"] / e["facts"] for e in evidence]),
                     "text_checked": sum(bool(e["text_checked"]) for e in evidence)},
        "source_precision": {"n": len(precision), "mean": _mean(precision)},
        "support": {"sentences": len(verdicts), "judged": len(judged),
                    "errors": len(verdicts) - len(judged),
                    **{label: judged.count(label) for label in WEIGHTS},
                    "score": _mean([WEIGHTS[v] for v in judged])},
    }
