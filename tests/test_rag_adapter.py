import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from citecheck.adapters import AdapterError, RagProjectAdapter

STATUS = {"files": 7, "chunks": 52, "documents": ["a.md"], "last_sync": "2026-10-24T10:00:00", "last_change": None,
          "watching": True, "chat_model": "qwen3:8b", "embed_model": "embeddinggemma", "thinking": True,
          "split_search": True, "auth_required": False}
ASK = {"answer": "A bath is $50.", "sources": ["03-pricing.md"], "seconds": 3.2,
       "passages": [{"source": "03-pricing.md", "section": "Add-Ons", "page": None, "text": "- Bath: $50.00",
                     "distance": 0.21, "best": True, "listed": True},
                    {"source": "07-guide.pdf", "section": "", "page": 2, "text": "Wait at the lobby.",
                     "distance": 0.4, "best": False, "listed": False}]}


@pytest.fixture
def server():
    """A stand-in for rag-project's API. `state` lets a test script its replies and see what was sent."""
    state = {"asks": [], "headers": [], "script": []}  # script: [(status, body)] consumed one per /api/ask

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body):
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            state["headers"].append(dict(self.headers))
            self.reply(200, STATUS)

        def do_POST(self):
            state["headers"].append(dict(self.headers))
            state["asks"].append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            status, body = state["script"].pop(0) if state["script"] else (200, ASK)
            self.reply(status, body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield state
    httpd.shutdown()


def test_query_maps_passages_and_sources(server):
    response = RagProjectAdapter(server["url"]).query("How much is a bath?")
    assert response.answer == "A bath is $50."
    assert [(c.rank, c.doc_id, c.score, c.page) for c in response.retrieved] == [(1, "03-pricing.md", 0.21, None), (2, "07-guide.pdf", 0.4, 2)]
    assert response.retrieved[0].text == "- Bath: $50.00" and response.retrieved[0].section == "Add-Ons"
    assert [c.doc_id for c in response.citations] == ["03-pricing.md"]
    assert response.error is None and response.latency_s is not None
    assert response.raw == {"server_seconds": 3.2}


def test_history_is_sent_with_the_question(server):
    history = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
    RagProjectAdapter(server["url"]).query("And a half day?", history=history, k=9)
    assert server["asks"] == [{"question": "And a half day?", "history": history}]  # k is not sent: the server fixes it


def test_describe_keeps_stable_server_facts_and_declared_settings(server):
    described = RagProjectAdapter(server["url"], declared={"RAG_TOP_K": "4"}).describe()
    assert described["server"]["chat_model"] == "qwen3:8b" and described["server"]["chunks"] == 52
    assert "last_sync" not in described["server"] and "watching" not in described["server"]
    assert described["declared"] == {"RAG_TOP_K": "4"}
    assert "token" not in json.dumps(described).lower()


def test_token_is_sent_as_a_bearer_header(server):
    RagProjectAdapter(server["url"], token="s3cret").describe()
    assert server["headers"][0]["Authorization"] == "Bearer s3cret"


def test_rate_limit_is_waited_out_then_retried(server):
    server["script"] = [(429, {"error": "slow down", "code": "rate_limited"})]
    response = RagProjectAdapter(server["url"], rate_limit_wait=0).query("q")
    assert response.answer == "A bath is $50." and len(server["asks"]) == 2


def test_server_error_message_reaches_the_runner(server):
    server["script"] = [(504, {"error": "The model took too long to answer.", "code": "model_timeout"})]
    with pytest.raises(AdapterError, match="HTTP 504.*took too long"):
        RagProjectAdapter(server["url"]).query("q")


def test_unreachable_server_is_an_adapter_error():
    with pytest.raises(AdapterError):
        RagProjectAdapter("http://127.0.0.1:9", timeout=2).describe()
