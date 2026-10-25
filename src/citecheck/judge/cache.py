"""Disk cache for judge replies.

One small JSON file per call, named by a hash of everything that shapes the reply (model and its digest, prompt version,
messages, schema, sampling options). Changing any of them is a miss, so a stale verdict is never reused; an unchanged call
is free, which is what lets `score` be re-run without asking the judge again.
"""
import hashlib
import json
from pathlib import Path

DEFAULT_DIR = Path(".cache") / "judge"


def cache_key(**parts) -> str:
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class JudgeCache:
    def __init__(self, directory=DEFAULT_DIR):
        self.directory = Path(directory)

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> str | None:
        try:
            return json.loads(self._path(key).read_text(encoding="utf-8"))["reply"]
        except (OSError, ValueError, KeyError):
            return None

    def put(self, key: str, reply: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path(key).write_text(json.dumps({"reply": reply}, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


class NoCache:
    """Same interface, stores nothing."""

    def get(self, key: str) -> str | None:
        return None

    def put(self, key: str, reply: str) -> None:
        pass
