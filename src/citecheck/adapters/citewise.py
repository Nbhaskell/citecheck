"""Adapter for Citewise for Markets (https://github.com/Nbhaskell/citewise-markets), over its JSON API.

The server must already be running (`python -m api` in that project, with its database and Ollama up). Facts about this
target that shape the mapping:
  * POST /api/copilot returns an answer with inline numbered citations ("... [1]. ... [3][6]") and a `sources` list whose
    `number` matches the marker. Each source has a `kind` (filing, price, fundamentals, headline or sentiment), a one-line
    `title` and the cited `excerpt`. The title ("NVDA 10-K filed 2026-02-25") is used as the document id.
  * `sources` holds only the passages the answer cited, not everything the model was shown, so retrieval cannot be
    scored: `retrieved` stays empty and describe() says so (`reports_retrieved: false`). What can be scored is whether the
    right passage was cited.
  * Prices, headlines and the P/E change every night, so a golden set for this target should rest on filing text.
  * Earlier turns go in as {question, answer, companies}; the companies are left empty and the server detects them.
  * It has no login. The rag-project token is deliberately not sent here.
"""
import time
from collections.abc import Sequence

from ..models import Citation, TargetResponse
from .base import AdapterError
from .rag_project import RagProjectAdapter

HEALTH_KEYS = ("status", "database", "ai_model", "ai_model_available")


def history_turns(history: Sequence[dict]) -> list[dict]:
    """citecheck's [{"role", "content"}, ...] as the API's [{"question", "answer", "companies"}, ...]."""
    turns, pending = [], None
    for message in history:
        if message["role"] == "user":
            pending = message["content"]
        elif message["role"] == "assistant" and pending is not None:
            turns.append({"question": pending, "answer": message["content"], "companies": []})
            pending = None
    return turns


class CitewiseAdapter(RagProjectAdapter):
    """Reuses the HTTP plumbing of the rag-project adapter (timeouts, error mapping); only the endpoints differ."""

    name = "citewise"

    def __init__(self, url: str = "http://127.0.0.1:8000", token: str | None = None, timeout: float = 300.0,
                 declared: dict | None = None, rate_limit_retries: int = 3, rate_limit_wait: float = 10.0):
        super().__init__(url, None, timeout, declared, rate_limit_retries, rate_limit_wait)
        self.token = None  # never the environment's rag-project token

    def describe(self) -> dict:
        health = self._request("GET", "/health")
        stocks = self._request("GET", "/api/stocks")
        return {"url": self.url,
                "server": {key: health[key] for key in HEALTH_KEYS if key in health},
                "companies": sorted(s["symbol"] for s in stocks),
                "reports_retrieved": False,
                "declared": self.declared}

    def query(self, question: str, *, history: Sequence[dict] = (), k: int | None = None) -> TargetResponse:
        body = {"question": question, "history": history_turns(history)[-4:]}
        if k is not None:
            body["limit"] = k
        started = time.perf_counter()
        data = self._request("POST", "/api/copilot", body)
        elapsed = time.perf_counter() - started
        try:
            citations = [Citation(doc_id=s["title"], marker=str(s["number"]), text=s.get("excerpt"))
                         for s in data["sources"]]
            return TargetResponse(
                answer=data["answer"],
                citations=citations,
                abstained=bool(data["refused"]),
                latency_s=round(elapsed, 3),
                raw={"grounded": data.get("grounded"), "companies": data.get("companies"),
                     "evidence_kinds": data.get("evidence_kinds"), "model_route": data.get("model_route"),
                     "unverified_numbers": data.get("unverified_numbers"), "cautions": data.get("cautions"),
                     "searches": data.get("searches"), "interpreted_question": data.get("interpreted_question"),
                     "source_kinds": {str(s["number"]): s.get("kind") for s in data["sources"]}})
        except (KeyError, TypeError) as e:
            raise AdapterError(f"unexpected reply from /api/copilot: missing {e}") from e
