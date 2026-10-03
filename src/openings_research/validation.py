"""Mechanical checks only: matching evidence is not proof of a prose claim."""

import chess

from .contracts import ClaimCandidate, LineCandidate, Source, position_record, stable_id


def validate_candidate(candidate: LineCandidate | ClaimCandidate, sources: list[Source]) -> dict:
    by_id = {s.source_version_id: s for s in sources}
    for evidence in candidate.evidence:
        source = by_id.get(evidence.source_version_id)
        if source is None:
            raise ValueError("Evidence references a source outside this run")
        if not evidence.excerpt.strip() or evidence.excerpt not in source.content:
            raise ValueError("Evidence excerpt is not present verbatim in the source")
    if not any(e.relation == "supports" for e in candidate.evidence):
        raise ValueError("At least one supporting evidence reference is required")

    if isinstance(candidate, ClaimCandidate):
        position = position_record(chess.Board(candidate.position_fen)) if candidate.position_fen else None
        return {"position": position, "review_status": "unreviewed"}

    board = chess.Board(candidate.start_fen)
    positions = [position_record(board)]
    moves = []
    uci_moves = []
    for san in candidate.moves_san:
        move = board.parse_san(san)
        if move not in board.legal_moves:
            raise ValueError("Illegal move or null move")
        normalized_san = board.san(move)
        before = positions[-1]["position_id"]
        board.push(move)
        after = position_record(board)
        positions.append(after)
        uci_moves.append(move.uci())
        moves.append(
            {
                "move_id": stable_id(before, move.uci()),
                "from_position_id": before,
                "to_position_id": after["position_id"],
                "uci": move.uci(),
                "san": normalized_san,
            }
        )
    return {
        "line_id": stable_id(positions[0]["position_id"], uci_moves),
        "positions": positions,
        "moves": moves,
        "moves_uci": uci_moves,
        "review_status": "unreviewed",
    }
