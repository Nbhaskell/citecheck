"""What an adapter returns. Every target system is mapped onto these shapes, so metrics never see a target's own format."""
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class RetrievedChunk:
    doc_id: str
    text: str
    rank: int  # 1 = the target's best match, in the order the target ranked them
    score: float | None = None  # the target's own number; its meaning and direction are target-specific
    section: str = ""
    page: int | None = None


@dataclass(frozen=True)
class Citation:
    doc_id: str
    marker: str | None = None  # the "[2]" style label in the answer text, for targets that cite inline
    text: str | None = None  # the cited excerpt, when the target gives one
    page: int | None = None


@dataclass
class TargetResponse:
    answer: str = ""
    retrieved: list[RetrievedChunk] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    abstained: bool | None = None  # None: the target does not say, a later step decides from the answer text
    latency_s: float | None = None
    error: str | None = None
    raw: dict = field(default_factory=dict)  # target fields that have no home above

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TargetResponse":
        return cls(
            answer=data.get("answer", ""),
            retrieved=[RetrievedChunk(**c) for c in data.get("retrieved", [])],
            citations=[Citation(**c) for c in data.get("citations", [])],
            abstained=data.get("abstained"),
            latency_s=data.get("latency_s"),
            error=data.get("error"),
            raw=data.get("raw", {}),
        )
