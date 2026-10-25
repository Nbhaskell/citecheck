"""A small client for Ollama's chat API, used only by the judge.

Plain urllib, like the target adapter, so the judge adds no dependency. Requests ask for a JSON reply that matches a
schema (Ollama's structured output), with temperature 0 and a fixed seed and context size, so the same prompt gives the
same verdict on the same model. The model reasons before answering by default (DEFAULT_THINK): with it off, the judge
flagged most good answers as unsupported (see the README's calibration section).
"""
import json
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_THINK = True  # the model reasons before answering; changes verdicts, so it is saved with every score
NUM_CTX = 8192  # the longest judge prompt (a question, 4-6 passages and an answer) is well under this


class JudgeError(Exception):
    """The judge model could not be reached or did not return a usable reply."""


class OllamaClient:
    def __init__(self, url: str = DEFAULT_URL, timeout: float = 600.0, seed: int = 0, think: bool = DEFAULT_THINK):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.seed = seed
        self.think = think

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.url + path, data=data, method=method,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read().decode("utf-8")).get("error", "")
            except Exception:
                detail = ""
            raise JudgeError(f"HTTP {e.code} from {path}: {detail}".rstrip(": ")) from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            raise JudgeError(f"{type(e).__name__} calling {self.url}{path}: {e}") from e

    def options(self) -> dict:
        """Everything that shapes a reply besides the prompt; part of the cache key and saved with the scores."""
        return {"temperature": 0, "seed": self.seed, "num_ctx": NUM_CTX, "think": self.think}

    def model_digest(self, model: str) -> str:
        """Content digest of the installed model, so a changed model under the same name is noticed."""
        for entry in self._request("GET", "/api/tags").get("models", []):
            if model in (entry.get("name"), entry.get("model")):
                return entry["digest"]
        raise JudgeError(f"model {model!r} is not installed in Ollama at {self.url}")

    def chat(self, model: str, messages: list[dict], schema: dict) -> str:
        """One reply, as the JSON text the model produced."""
        reply = self._request("POST", "/api/chat", {
            "model": model, "messages": messages, "stream": False, "think": self.think, "format": schema,
            "options": {"temperature": 0, "seed": self.seed, "num_ctx": NUM_CTX}, "keep_alive": "10m"})
        content = reply.get("message", {}).get("content")
        if not content:
            raise JudgeError(f"empty reply from {model}")
        return content
