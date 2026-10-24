"""Adapter for rag-project (https://github.com/Nbhaskell/rag-project), over its JSON API.

The server must already be running (`python chat.py`, with RAG_DOCS_DIR / RAG_DB_DIR pointing at the corpus the golden
set was written for). Facts about this target that shape the mapping:
  * POST /api/ask returns the passages the model was given, best match first, with their distance (smaller is
    closer), and a file-level "sources" list. There are no inline citations.
  * The number of passages is fixed by the server (RAG_TOP_K, 4 by default; a question split into parts adds more), so
    k is ignored. Pass the server's settings with `declared` so they are saved with the run.
  * Every request runs the chat model, so retrieval cannot be measured on its own over HTTP.
  * Passage text arrives without the "Title > Section" label line the model also sees.
"""
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Sequence

from ..models import Citation, RetrievedChunk, TargetResponse
from .base import AdapterError

STATUS_KEYS = ("chat_model", "embed_model", "thinking", "split_search", "files", "chunks", "documents")


class RagProjectAdapter:
    name = "rag-project"

    def __init__(self, url: str = "http://127.0.0.1:8000", token: str | None = None, timeout: float = 300.0,
                 declared: dict | None = None, rate_limit_retries: int = 3, rate_limit_wait: float = 10.0):
        self.url = url.rstrip("/")
        self.token = token or os.environ.get("RAG_API_TOKEN") or None
        self.timeout = timeout
        self.declared = dict(declared or {})
        self.rate_limit_retries = rate_limit_retries
        self.rate_limit_wait = rate_limit_wait

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        for attempt in range(self.rate_limit_retries + 1):
            request = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < self.rate_limit_retries:
                    time.sleep(self.rate_limit_wait)
                    continue
                try:
                    detail = json.loads(e.read().decode("utf-8")).get("error", "")
                except Exception:
                    detail = ""
                raise AdapterError(f"HTTP {e.code} from {path}: {detail}".rstrip(": ")) from e
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
                raise AdapterError(f"{type(e).__name__} calling {self.url}{path}: {e}") from e
        raise AdapterError(f"rate limited on {path} after {self.rate_limit_retries} retries")  # pragma: no cover

    def describe(self) -> dict:
        status = self._request("GET", "/api/status")
        return {"url": self.url,
                "server": {key: status[key] for key in STATUS_KEYS if key in status},
                "declared": self.declared}

    def query(self, question: str, *, history: Sequence[dict] = (), k: int | None = None) -> TargetResponse:
        started = time.perf_counter()
        data = self._request("POST", "/api/ask", {"question": question, "history": list(history)})
        elapsed = time.perf_counter() - started
        retrieved = [RetrievedChunk(doc_id=p["source"], text=p["text"], rank=rank, score=p.get("distance"),
                                    section=p.get("section", ""), page=p.get("page"))
                     for rank, p in enumerate(data.get("passages", []), 1)]
        return TargetResponse(
            answer=data["answer"],
            retrieved=retrieved,
            citations=[Citation(doc_id=source) for source in data.get("sources", [])],
            latency_s=round(elapsed, 3),
            raw={"server_seconds": data.get("seconds")},
        )
