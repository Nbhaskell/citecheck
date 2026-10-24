from collections.abc import Sequence

from ..models import TargetResponse
from .base import AdapterError


class MockAdapter:
    """Answers from a fixed {question: TargetResponse} table, for tests. Remembers every call it received."""

    name = "mock"

    def __init__(self, responses: dict[str, TargetResponse], settings: dict | None = None):
        self.responses = responses
        self.settings = settings or {}
        self.calls: list[dict] = []

    def describe(self) -> dict:
        return dict(self.settings)

    def query(self, question: str, *, history: Sequence[dict] = (), k: int | None = None) -> TargetResponse:
        self.calls.append({"question": question, "history": list(history), "k": k})
        if question not in self.responses:
            raise AdapterError(f"mock has no response for {question!r}")
        return self.responses[question]
