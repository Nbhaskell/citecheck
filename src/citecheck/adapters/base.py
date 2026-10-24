from collections.abc import Sequence
from typing import Protocol

from ..models import TargetResponse


class AdapterError(Exception):
    """The target could not answer (unreachable, timed out, refused). The runner records the message and carries on."""


class TargetAdapter(Protocol):
    name: str

    def describe(self) -> dict:
        """The target's settings as far as it can report them (models, chunking, top-k...). Saved with every run, so two
        runs can be told apart later. Must be JSON-serializable and must not contain secrets."""
        ...

    def query(self, question: str, *, history: Sequence[dict] = (), k: int | None = None) -> TargetResponse:
        """Ask one question. history is earlier turns as {"role": "user"|"assistant", "content": str}, oldest first.
        k is how many passages to retrieve, where the target lets a caller choose; targets that cannot ignore it.
        Raise AdapterError when no answer could be obtained."""
        ...
