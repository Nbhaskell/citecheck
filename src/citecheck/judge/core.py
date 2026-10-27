"""The judge: asks a local model the questions in prompts.py about one answer and returns structured verdicts.

For each answer the judge decides, in order:
  1. abstention: always.
  2. faithfulness: unless the answer abstained (it has no claims to check), against the retrieved passages or, when the
     target does not report them, the sources the answer cited.
  3. correctness: only for questions the corpus answers and that have a reference answer, including when the answer
     abstained (a refusal is then incorrect).
A call that fails (model unreachable, reply not matching the schema) gives a verdict of None and an error message; it
never stops a scoring pass, and failures are never cached.
"""
import json

from ..metrics import citations
from ..models import TargetResponse
from . import prompts
from .cache import JudgeCache, NoCache, cache_key
from .client import JudgeError, OllamaClient

DEFAULT_MODEL = "qwen3:8b"
VERDICTS = {"abstention": prompts.ABSTENTION, "faithfulness": prompts.FAITHFULNESS, "correctness": prompts.CORRECTNESS,
            "citation": prompts.FAITHFULNESS}
DETAIL_FIELD = {"abstention": "reasoning", "faithfulness": "unsupported_claims", "correctness": "reasoning",
                "citation": "reasoning"}


def passages_for(response: TargetResponse) -> list[str]:
    """What an answer is checked against for faithfulness: the passages the target retrieved, or, for a target that does
    not report them, the excerpts of the sources it cited."""
    retrieved = [c.text for c in response.retrieved]
    return retrieved or [c.text for c in response.citations if c.text]


class Judge:
    def __init__(self, client: OllamaClient | None = None, model: str = DEFAULT_MODEL, cache: JudgeCache | NoCache | None = None):
        self.client = client or OllamaClient()
        self.model = model
        self.cache = JudgeCache() if cache is None else cache
        self._digest: str | None = None
        self.calls = 0  # replies that came from the model
        self.cache_hits = 0

    @property
    def digest(self) -> str:
        if self._digest is None:
            self._digest = self.client.model_digest(self.model)
        return self._digest

    def config(self) -> dict:
        """What identifies this judge; saved with every score that uses it."""
        return {"model": self.model, "model_digest": self.digest, "prompt_version": prompts.version_label(),
                "prompt_versions": dict(prompts.PROMPT_VERSIONS), **self.client.options()}

    def verdict(self, kind: str, **fields) -> dict:
        """One judge call. Returns {"verdict", <detail field>, "cached", "error"}; verdict is None on failure."""
        detail = DETAIL_FIELD[kind]
        failed = {"verdict": None, detail: None, "cached": False}
        messages = prompts.messages(kind, **fields)
        key = cache_key(kind=kind, model=self.model, digest=self.digest, prompt_version=prompts.PROMPT_VERSIONS[kind],
                        options=self.client.options(), messages=messages, schema=prompts.SCHEMAS[kind])
        reply = self.cache.get(key)
        cached = reply is not None
        try:
            if reply is None:
                reply = self.client.chat(self.model, messages, prompts.SCHEMAS[kind])
            parsed = self._parse(kind, reply)
        except JudgeError as e:
            return {**failed, "error": str(e)}
        if cached:
            self.cache_hits += 1
        else:
            self.calls += 1
            self.cache.put(key, reply)
        return {"verdict": parsed["verdict"], detail: parsed[detail], "cached": cached, "error": None}

    @staticmethod
    def _parse(kind: str, reply: str) -> dict:
        try:
            data = json.loads(reply)
        except json.JSONDecodeError as e:
            raise JudgeError(f"reply is not JSON: {reply[:80]!r}") from e
        detail = DETAIL_FIELD[kind]
        if not isinstance(data, dict) or data.get("verdict") not in VERDICTS[kind] or detail not in data:
            raise JudgeError(f"reply does not match the {kind} schema: {reply[:120]!r}")
        if kind == "faithfulness" and not (isinstance(data[detail], list) and all(isinstance(c, str) for c in data[detail])):
            raise JudgeError(f"unsupported_claims is not a list of strings: {reply[:120]!r}")
        return data

    def judge_item(self, item: dict, response: TargetResponse, history=()) -> dict:
        """Verdicts for one answer to one golden-set item. Keys present: abstention, and where they apply,
        faithfulness and correctness."""
        question, answer = item["question"], response.answer
        out = {"abstention": self.verdict("abstention", question=question, answer=answer, history=history)}
        abstained = out["abstention"]["verdict"] == "abstained"
        if not abstained:
            out["faithfulness"] = self.verdict("faithfulness", question=question, answer=answer, history=history,
                                               passages=passages_for(response))
        # a refusal to answer an answerable question must count against correctness, so it is judged too
        if not item["expected_abstain"] and item.get("reference_answer"):
            out["correctness"] = self.verdict("correctness", question=question, answer=answer, history=history,
                                              reference=item["reference_answer"])
        return out

    def judge_citations(self, response: TargetResponse, history=()) -> list[dict]:
        """One verdict per sentence of the answer that carries markers, on whether the sources cited for it support it.
        A sentence whose markers match no listed source with an excerpt cannot be judged on those; it is reported with
        verdict None and the markers that were missing, and is judged on the sources that are there when any are."""
        out = []
        for unit in citations.claim_units(response.answer, response.citations):
            result = {"sentence": unit["sentence"], "markers": unit["markers"], "missing": unit["missing"]}
            if unit["sources"]:
                result.update(self.verdict("citation", statement=unit["sentence"], previous=unit["previous"],
                                           cited=unit["sources"], history=history))
            else:
                result.update({"verdict": None, "reasoning": None, "cached": False, "error": "no cited source to judge against"})
            out.append(result)
        return out
