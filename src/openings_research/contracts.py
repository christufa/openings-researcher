"""Versioned agent boundary. No Spark or provider clients belong here."""

import hashlib
import json
from typing import Literal

import chess
from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "1"
POSITION_VERSION = "standard-legal-ep-v1"


def stable_id(*parts: object) -> str:
    encoded = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(Contract):
    source_version_id: str
    url: str
    title: str
    content: str


class Evidence(Contract):
    source_version_id: str
    excerpt: str = Field(min_length=1)
    relation: Literal["supports", "disputes"]


class LineCandidate(Contract):
    name: str = Field(min_length=1)
    start_fen: str
    moves_san: list[str] = Field(min_length=1, max_length=100)
    evidence: list[Evidence] = Field(min_length=1)


class ClaimCandidate(Contract):
    text: str = Field(min_length=1)
    category: Literal["plan", "pawn_break", "maneuver", "tactic", "mistake", "move_order", "assessment"]
    side: Literal["white", "black", "both"]
    position_fen: str | None
    evidence: list[Evidence] = Field(min_length=1)


class AgentOutput(Contract):
    lines: list[LineCandidate]
    claims: list[ClaimCandidate]
    unresolved_questions: list[str]


class ResearchInput(Contract):
    opening: str
    sources: list[Source]
    existing_claims: list[str] = Field(default_factory=list)


def position_record(board: chess.Board) -> dict:
    if not board.is_valid() or board.chess960:
        raise ValueError("Only valid standard-chess positions are supported")
    normalized = " ".join(board.fen(en_passant="legal").split()[:4])
    return {
        "position_id": stable_id(POSITION_VERSION, normalized),
        "normalized_fen": normalized,
        "identity_version": POSITION_VERSION,
    }
