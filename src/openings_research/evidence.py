"""Give agents passage IDs; resolve citations from immutable source text in code."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, create_model

from .contracts import AgentOutput, ClaimCandidate, Contract, LineCandidate, Source

EVIDENCE_INDEX_VERSION = "source-passages-v1"
MAX_PASSAGE_CHARS = 1200
MAX_PASSAGES = 500


@dataclass(frozen=True)
class Passage:
    passage_id: str
    source_version_id: str
    start: int
    end: int
    text: str

    def manifest(self) -> dict:
        return {
            "passage_id": self.passage_id,
            "source_version_id": self.source_version_id,
            "start": self.start,
            "end": self.end,
        }


def index_passages(sources: list[Source]) -> list[Passage]:
    """Deterministic, bounded chunks retaining the original Unicode/Markdown bytes as text.

    Offsets are Python Unicode character offsets, not byte offsets. Prefer
    paragraph/newline boundaries in the latter half of a chunk, then a space.
    Never normalize quotes, whitespace, Markdown, or move notation.
    """
    unique = {}
    for source in sources:
        if source.source_version_id in unique and unique[source.source_version_id] != source:
            raise ValueError("Conflicting contents for the same source version")
        unique[source.source_version_id] = source
    passages = []
    for source_id, source in sorted(unique.items()):
        start = 0
        while start < len(source.content):
            end = min(start + MAX_PASSAGE_CHARS, len(source.content))
            if end < len(source.content):
                for separator in ("\n\n", "\n", " "):
                    boundary = source.content.rfind(separator, start + MAX_PASSAGE_CHARS // 2, end)
                    if boundary >= 0:
                        end = boundary + len(separator)
                        break
            text = source.content[start:end]
            if text.strip():
                passages.append(Passage(f"p{len(passages) + 1:04d}", source_id, start, end, text))
                if len(passages) > MAX_PASSAGES:
                    raise ValueError("Too many source passages; split this research task")
            start = end
    if not passages:
        raise ValueError("No nonempty source passages available")
    return passages


def reference_schema(passages: list[Passage]) -> type[BaseModel]:
    """Only IDs provided to this request are legal in the provider output schema."""
    ids = tuple(p.passage_id for p in passages)
    if not ids or len(ids) != len(set(ids)) or len(ids) > MAX_PASSAGES:
        raise ValueError("Invalid passage catalog")
    reference = create_model(
        "PassageReference",
        __base__=Contract,
        passage_id=(Literal[ids], ...),
        relation=(Literal["supports", "disputes"], ...),
    )
    line = create_model(
        "ReferencedLine", __base__=LineCandidate, evidence=(list[reference], Field(min_length=1))
    )
    claim = create_model(
        "ReferencedClaim", __base__=ClaimCandidate, evidence=(list[reference], Field(min_length=1))
    )
    return create_model(
        "ReferencedOutput", __base__=AgentOutput, lines=(list[line], ...), claims=(list[claim], ...)
    )


def resolve_references(output: BaseModel, passages: list[Passage]) -> AgentOutput:
    by_id = {p.passage_id: p for p in passages}
    if len(by_id) != len(passages):
        raise ValueError("Duplicate passage IDs")
    # Validate at the boundary too: never silently drop or guess an invalid citation.
    data = reference_schema(passages).model_validate(output.model_dump()).model_dump()
    for candidate in data["lines"] + data["claims"]:
        evidence = []
        for reference in candidate["evidence"]:
            passage = by_id[reference["passage_id"]]
            evidence.append(
                {
                    "source_version_id": passage.source_version_id,
                    "excerpt": passage.text,
                    "relation": reference["relation"],
                }
            )
        candidate["evidence"] = evidence
    return AgentOutput.model_validate(data)
