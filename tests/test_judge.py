import json

import pytest

from citecheck import cli, scoring
from citecheck.judge import Judge, JudgeCache, JudgeError, NoCache, OllamaClient, prompts
from citecheck.metrics import answer as answer_metrics
from citecheck.models import RetrievedChunk, TargetResponse

from test_runner import make_golden, mock, response
from citecheck import runner


class FakeClient:
    """Stands in for OllamaClient: replies come from `script(kind, user_text)` and every call is recorded."""

    def __init__(self, script=None):
        self.script = script or self.default
        self.calls = []

    @staticmethod
    def default(kind, user_text):
        if kind == "abstention":
            return {"reasoning": "r", "verdict": "abstained" if "I don't know" in user_text else "answered"}
        if kind == "faithfulness":
            return {"unsupported_claims": [], "verdict": "supported"}
        return {"reasoning": "r", "verdict": "correct"}

    def options(self):
        return {"temperature": 0, "seed": 0, "num_ctx": 8192, "think": False}

    def model_digest(self, model):
        return "d" * 64

    def chat(self, model, messages, schema):
        kind = next(k for k, s in prompts.SCHEMAS.items() if s == schema)
        self.calls.append({"kind": kind, "model": model, "messages": messages})
        reply = self.script(kind, messages[1]["content"])
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply)


def judge_with(script=None, cache=None):
    client = FakeClient(script)
    return Judge(client, model="m", cache=NoCache() if cache is None else cache), client


ITEM = {"id": "bath", "question": "How much is a bath?", "expected_abstain": False,
        "reference_answer": "A bath is $50.00.", "evidence": []}


def chunks(*texts):
    return [RetrievedChunk("doc.md", text, rank) for rank, text in enumerate(texts, 1)]


# --- prompts -----------------------------------------------------------------------------------------------------

def test_prompts_carry_what_each_verdict_needs():
    base = dict(question="How much is a bath?", answer="It is $50.")
    abstention = prompts.messages("abstention", **base)[1]["content"]
    assert "<answer>\nIt is $50.\n</answer>" in abstention and "reference" not in abstention
    faithfulness = prompts.messages("faithfulness", passages=["Bath: $50.00", "Nail trim: $30.00"], **base)[1]["content"]
    assert "[1] Bath: $50.00" in faithfulness and "[2] Nail trim: $30.00" in faithfulness
    correctness = prompts.messages("correctness", reference="A bath is $50.00.", **base)[1]["content"]
    assert "<reference_answer>\nA bath is $50.00.\n</reference_answer>" in correctness


def test_a_follow_up_is_judged_with_its_earlier_conversation():
    history = [{"role": "user", "content": "How much is a bath?"}, {"role": "assistant", "content": "$50."}]
    text = prompts.messages("correctness", question="And nails?", answer="$30.", reference="$30.",
                            history=history)[1]["content"]
    assert text.index("user: How much is a bath?") < text.index("<question>")


def test_every_schema_puts_the_explanation_before_the_verdict():
    for schema in prompts.SCHEMAS.values():
        assert list(schema["properties"])[-1] == "verdict"
        assert schema["required"][-1] == "verdict"


# --- verdicts, cache, failures -----------------------------------------------------------------------------------

def test_a_verdict_is_parsed_and_returned_with_its_explanation():
    judge, _ = judge_with(lambda kind, text: {"unsupported_claims": ["30 days"], "verdict": "partly_supported"})
    result = judge.verdict("faithfulness", question="q", answer="a", passages=["p"])
    assert result == {"verdict": "partly_supported", "unsupported_claims": ["30 days"], "cached": False, "error": None}


def test_a_repeated_call_comes_from_the_cache(tmp_path):
    judge, client = judge_with(cache=JudgeCache(tmp_path))
    first = judge.verdict("abstention", question="q", answer="a")
    second = judge.verdict("abstention", question="q", answer="a")
    assert (first["cached"], second["cached"]) == (False, True)
    assert len(client.calls) == 1 and (judge.calls, judge.cache_hits) == (1, 1)


def test_the_cache_misses_when_the_model_the_prompt_or_the_text_changes(tmp_path, monkeypatch):
    judge, client = judge_with(cache=JudgeCache(tmp_path))
    judge.verdict("abstention", question="q", answer="a")
    judge.verdict("abstention", question="q", answer="different")
    other_model = Judge(client, model="other", cache=JudgeCache(tmp_path))
    other_model.verdict("abstention", question="q", answer="a")
    monkeypatch.setattr(prompts, "PROMPT_VERSION", "2")
    judge.verdict("abstention", question="q", answer="a")
    assert len(client.calls) == 4


@pytest.mark.parametrize("reply", [
    "not json", "[]", {"verdict": "maybe", "reasoning": "r"}, {"verdict": "answered"},
    {"verdict": "supported", "unsupported_claims": "none"},
])
def test_an_unusable_reply_is_an_error_not_a_verdict_and_is_not_cached(reply, tmp_path):
    judge, client = judge_with(lambda kind, text: reply, cache=JudgeCache(tmp_path))
    kind = "faithfulness" if isinstance(reply, dict) and "unsupported_claims" in reply else "abstention"
    result = judge.verdict(kind, question="q", answer="a", passages=["p"])
    assert result["verdict"] is None and result["error"]
    assert list(tmp_path.glob("*.json")) == []


def test_a_model_failure_is_recorded_and_does_not_raise():
    judge, _ = judge_with(lambda kind, text: JudgeError("timed out"))
    result = judge.verdict("correctness", question="q", answer="a", reference="r")
    assert result["verdict"] is None and result["error"] == "timed out"


def test_the_config_names_the_model_its_digest_and_the_prompt_version():
    judge, _ = judge_with()
    assert judge.config() == {"model": "m", "model_digest": "d" * 64, "prompt_version": prompts.PROMPT_VERSION,
                              "temperature": 0, "seed": 0, "num_ctx": 8192, "think": False}


# --- what is judged for which answer -----------------------------------------------------------------------------

def test_an_answerable_question_gets_all_three_verdicts_and_sees_the_retrieved_passages():
    judge, client = judge_with()
    out = judge.judge_item(ITEM, TargetResponse(answer="$50.", retrieved=chunks("Bath: $50.00")))
    assert set(out) == {"abstention", "faithfulness", "correctness"}
    faithfulness_call = next(c for c in client.calls if c["kind"] == "faithfulness")
    assert "[1] Bath: $50.00" in faithfulness_call["messages"][1]["content"]


def test_an_abstained_answer_is_not_checked_for_faithfulness():
    judge, client = judge_with()
    item = {**ITEM, "expected_abstain": True, "reference_answer": "The documents do not say."}
    out = judge.judge_item(item, TargetResponse(answer="I don't know."))
    assert set(out) == {"abstention"} and [c["kind"] for c in client.calls] == ["abstention"]


def test_a_refusal_to_answer_an_answerable_question_is_still_judged_for_correctness():
    judge, client = judge_with()
    out = judge.judge_item(ITEM, TargetResponse(answer="I don't know."))
    assert set(out) == {"abstention", "correctness"}


def test_an_unanswerable_question_is_not_judged_for_correctness():
    judge, _ = judge_with()
    item = {**ITEM, "expected_abstain": True, "reference_answer": "The documents do not say."}
    out = judge.judge_item(item, TargetResponse(answer="Yes, we do."))
    assert set(out) == {"abstention", "faithfulness"}


def test_an_item_without_a_reference_answer_is_not_judged_for_correctness():
    judge, _ = judge_with()
    out = judge.judge_item({**ITEM, "reference_answer": ""}, TargetResponse(answer="$50."))
    assert "correctness" not in out


# --- metrics -----------------------------------------------------------------------------------------------------

def judged(abstention="answered", faithfulness=None, correctness=None, error=None):
    out = {"abstention": {"verdict": abstention, "error": None}}
    if faithfulness is not None or abstention != "abstained":
        out["faithfulness"] = {"verdict": faithfulness, "error": error}
    if correctness is not None:
        out["correctness"] = {"verdict": correctness, "error": None}
    return out


def test_summary_counts_verdicts_and_averages_with_partial_credit():
    entries = [
        {"expected_abstain": False, "judged": judged("answered", "supported", "correct")},
        {"expected_abstain": False, "judged": judged("answered", "partly_supported", "partly_correct")},
        {"expected_abstain": False, "judged": judged("abstained")},
        {"expected_abstain": True, "judged": judged("abstained")},
        {"expected_abstain": True, "judged": judged("answered", "unsupported")},
    ]
    s = answer_metrics.summarize(entries)
    assert s["faithfulness"] == {"n": 3, "supported": 1, "partly_supported": 1, "unsupported": 1, "score": 0.5}
    assert s["correctness"] == {"n": 2, "correct": 1, "partly_correct": 1, "incorrect": 0, "score": 0.75}
    assert s["abstention"]["answerable"] == {"n": 3, "abstained": 1, "answered": 2, "partly_answered": 0}
    assert s["abstention"]["unanswerable"] == {"n": 2, "abstained": 1, "answered": 1, "partly_answered": 0}


def test_a_failed_verdict_is_counted_as_an_error_and_left_out_of_the_average():
    entries = [{"expected_abstain": False, "judged": judged("answered", "supported", "correct")},
               {"expected_abstain": False, "judged": judged("answered", None, "correct", error="timed out")}]
    s = answer_metrics.summarize(entries)
    assert s["judge_errors"] == 1 and s["faithfulness"]["n"] == 1 and s["faithfulness"]["score"] == 1.0


def test_an_empty_summary_has_no_scores():
    s = answer_metrics.summarize([])
    assert s["faithfulness"]["score"] is None and s["correctness"]["score"] is None


# --- scoring with a judge ----------------------------------------------------------------------------------------

def test_score_run_without_a_judge_has_no_answer_section():
    run = runner.run_golden(make_golden(), mock())
    scores = scoring.score_run(run, make_golden())
    assert scores["config"]["judge"] is None and "answer" not in scores["summary"]["overall"]
    assert scores["scores_version"] == 4


def test_score_run_with_a_judge_reports_answer_quality_by_split_and_category():
    golden = make_golden()
    for item in golden["items"]:
        item["reference_answer"] = "ref"
    run = runner.run_golden(golden, mock())
    judge, _ = judge_with()
    scores = scoring.score_run(run, golden, judge=judge)
    overall = scores["summary"]["overall"]["answer"]
    assert overall["judged"] == 3 and overall["abstention"]["unanswerable"]["abstained"] == 1
    assert overall["correctness"]["n"] == 2  # the unanswerable item has no correctness verdict
    assert scores["summary"]["by_category"]["follow_up"]["answer"]["judged"] == 1
    assert scores["config"]["judge"]["model"] == "m"
    assert "answer quality, judged by m" in scoring.format_report(scores)


def test_a_follow_up_reaches_the_judge_with_its_recorded_history():
    golden = make_golden()
    run = runner.run_golden(golden, mock())
    judge, client = judge_with()
    scoring.score_run(run, golden, judge=judge)
    follow_up_calls = [c["messages"][1]["content"] for c in client.calls if "And nails?" in c["messages"][1]["content"]]
    assert follow_up_calls and all("user: How much is a bath?" in text for text in follow_up_calls)


def test_answers_that_errored_are_not_judged():
    golden = make_golden()
    run = runner.run_golden(golden, mock(**{"Do you take cats?": response("x")}))
    run["records"][2]["response"]["error"] = "timed out"
    judge, client = judge_with()
    scores = scoring.score_run(run, golden, judge=judge)
    assert scores["summary"]["overall"]["answer"]["judged"] == 2
    assert all("Do you take cats?" not in c["messages"][1]["content"] for c in client.calls)


# --- client ------------------------------------------------------------------------------------------------------

def test_the_client_asks_for_schema_shaped_json(monkeypatch):
    sent = {}

    def fake_request(self, method, path, body=None):
        sent.update(method=method, path=path, body=body)
        return {"message": {"content": '{"verdict": "answered", "reasoning": "r"}'}}

    monkeypatch.setattr(OllamaClient, "_request", fake_request)
    reply = OllamaClient(seed=7, think=False).chat("qwen3:8b", [{"role": "user", "content": "x"}], prompts.SCHEMAS["abstention"])
    assert json.loads(reply)["verdict"] == "answered"
    body = sent["body"]
    assert sent["path"] == "/api/chat" and body["stream"] is False and body["think"] is False
    assert body["format"] == prompts.SCHEMAS["abstention"]
    assert body["options"]["temperature"] == 0 and body["options"]["seed"] == 7


def test_the_judge_model_reasons_before_answering_unless_told_not_to():
    assert OllamaClient().think is True and OllamaClient(think=False).think is False
    assert OllamaClient().options()["think"] is True


def test_the_client_finds_a_models_digest_and_reports_a_missing_model(monkeypatch):
    monkeypatch.setattr(OllamaClient, "_request", lambda self, m, p, b=None: {"models": [{"name": "qwen3:8b", "digest": "abc"}]})
    assert OllamaClient().model_digest("qwen3:8b") == "abc"
    with pytest.raises(JudgeError, match="not installed"):
        OllamaClient().model_digest("llama")


def test_score_cli_stops_early_when_the_judge_model_is_missing(tmp_path, monkeypatch, capsys):
    run = runner.run_golden(make_golden(), mock())
    run_path = runner.save_run(run, tmp_path)
    golden_path = tmp_path / "golden.json"
    golden_path.write_text(json.dumps(make_golden()), encoding="utf-8")
    monkeypatch.setattr(OllamaClient, "_request", lambda self, m, p, b=None: {"models": []})
    code = cli.main(["score", str(run_path), "--golden", str(golden_path), "--judge", "--no-cache"])
    assert code == 1 and "cannot use the judge" in capsys.readouterr().out
    assert not list(tmp_path.glob("*.scores.json"))


def test_a_target_that_reports_no_passages_is_judged_against_the_sources_it_cited():
    from citecheck.models import Citation
    judge, client = judge_with()
    response = TargetResponse(answer="A bath is $50.", citations=[Citation("doc", marker="1", text="- Bath: $50.00"),
                                                                  Citation("doc", marker="2", text=None)])
    judge.judge_item(ITEM, response)
    faithfulness_call = next(c for c in client.calls if c["kind"] == "faithfulness")
    assert "[1] - Bath: $50.00" in faithfulness_call["messages"][1]["content"]
    assert "(no passages)" not in faithfulness_call["messages"][1]["content"]
