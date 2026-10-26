import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from citecheck import runner, scoring
from citecheck.adapters import TARGETS, AdapterError, CitewiseAdapter
from citecheck.adapters.citewise import history_turns

HEALTH = {"status": "ok", "database": True, "ai_model": "ollama:qwen3:latest", "ai_model_available": True}
STOCKS = [{"symbol": "NVDA"}, {"symbol": "AMD"}]
COPILOT = {
    "question": "Where is AMD headquartered?", "answer": "AMD is based in Santa Clara [1]. It has 31,000 employees [2].",
    "refused": False, "grounded": True, "companies": ["AMD"], "evidence_kinds": ["filing"], "model_route": [],
    "unverified_numbers": [], "cautions": ["a caution"],
    "sources": [{"number": 1, "kind": "filing", "symbol": "AMD", "title": "AMD 10-K filed 2026-02-04",
                 "excerpt": "Our headquarters are located in Santa Clara, California"},
                {"number": 2, "kind": "filing", "symbol": "AMD", "title": "AMD 10-K filed 2026-02-04",
                 "excerpt": "we had approximately 31,000 employees"}],
    "searches": ["where is AMD headquartered"], "interpreted_question": None, "disclaimer": "..."}


@pytest.fixture
def server():
    state = {"posts": [], "headers": []}

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
            self.reply(200, HEALTH if self.path == "/health" else STOCKS)

        def do_POST(self):
            state["headers"].append(dict(self.headers))
            state["posts"].append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.reply(*state.get("script", (200, COPILOT)))

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield state
    httpd.shutdown()


def test_the_adapter_is_registered_under_its_name():
    assert TARGETS["citewise"] is CitewiseAdapter and CitewiseAdapter.name == "citewise"


def test_sources_become_numbered_citations_with_their_excerpts(server):
    response = CitewiseAdapter(server["url"]).query("Where is AMD headquartered?")
    assert response.answer.startswith("AMD is based in Santa Clara [1]")
    assert [(c.marker, c.doc_id, c.text) for c in response.citations] == [
        ("1", "AMD 10-K filed 2026-02-04", "Our headquarters are located in Santa Clara, California"),
        ("2", "AMD 10-K filed 2026-02-04", "we had approximately 31,000 employees")]
    assert response.abstained is False and response.retrieved == [] and response.error is None
    assert response.raw["cautions"] == ["a caution"] and response.raw["source_kinds"] == {"1": "filing", "2": "filing"}


def test_describe_says_that_retrieval_is_not_reported(server):
    described = CitewiseAdapter(server["url"], declared={"COPILOT_ROUTER": "on"}).describe()
    assert described["reports_retrieved"] is False and described["companies"] == ["AMD", "NVDA"]
    assert described["server"]["ai_model"] == "ollama:qwen3:latest" and described["declared"] == {"COPILOT_ROUTER": "on"}


def test_earlier_turns_are_sent_as_question_answer_pairs():
    history = [{"role": "user", "content": "Where is NVIDIA headquartered?"},
               {"role": "assistant", "content": "Santa Clara."}]
    assert history_turns(history) == [{"question": "Where is NVIDIA headquartered?", "answer": "Santa Clara.", "companies": []}]
    assert history_turns([{"role": "assistant", "content": "orphan"}]) == []


def test_the_request_carries_history_and_the_passage_limit(server):
    CitewiseAdapter(server["url"]).query("And employees?", history=[{"role": "user", "content": "q"},
                                                                    {"role": "assistant", "content": "a"}], k=8)
    assert server["posts"][0] == {"question": "And employees?", "limit": 8,
                                  "history": [{"question": "q", "answer": "a", "companies": []}]}


def test_the_rag_project_token_is_never_sent(server, monkeypatch):
    monkeypatch.setenv("RAG_API_TOKEN", "secret-token")
    adapter = CitewiseAdapter(server["url"], token="another")
    adapter.query("Where is AMD headquartered?")
    assert adapter.token is None and not any("Authorization" in h for h in server["headers"])


def test_a_refusal_is_recorded_as_an_abstention(server):
    server["script"] = (200, {**COPILOT, "refused": True, "sources": [], "answer": "That is outside what this app covers."})
    response = CitewiseAdapter(server["url"]).query("Will it rise?")
    assert response.abstained is True and response.citations == []


def test_a_reply_missing_fields_is_an_adapter_error(server):
    server["script"] = (200, {"answer": "x"})
    with pytest.raises(AdapterError, match="unexpected reply"):
        CitewiseAdapter(server["url"]).query("Where is AMD headquartered?")


def test_a_server_error_is_an_adapter_error(server):
    server["script"] = (500, {"error": "boom"})
    with pytest.raises(AdapterError, match="HTTP 500"):
        CitewiseAdapter(server["url"]).query("Where is AMD headquartered?")


def test_a_run_against_the_adapter_scores_citations_but_not_retrieval(server, tmp_path):
    golden = {"schema_version": 1, "golden_version": "t-1.0.0", "target": "citewise",
              "corpus": {"name": "t", "documents": {"AMD 10-K filed 2026-02-04": "0" * 64}},
              "items": [{"id": "amd-hq", "split": "heldout", "category": "factual", "question": "Where is AMD headquartered?",
                         "expected_abstain": False,
                         "evidence": [{"anchor": "headquarters are located in Santa Clara",
                                       "passages": [{"doc_id": "AMD 10-K filed 2026-02-04",
                                                     "text": "Our headquarters are located in Santa Clara, California"}]}]}]}
    run = runner.run_golden(golden, CitewiseAdapter(server["url"]))
    assert run["target"]["describe"]["reports_retrieved"] is False
    overall = scoring.score_run(run, golden)["summary"]["overall"]
    assert overall["retrieval"]["n"] == 0
    assert overall["citations"]["evidence"]["all_cited"] == 1 and overall["citations"]["with_dangling_marker"] == 0
    assert overall["citations"]["source_precision"]["mean"] == 1.0
