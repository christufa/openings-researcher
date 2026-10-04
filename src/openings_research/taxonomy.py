"""Project-defined categories shared by extraction, review and coverage planning."""

from typing import Literal

ClaimCategory = Literal[
    "plan",
    "pawn_break",
    "maneuver",
    "tactic",
    "mistake",
    "move_order",
    "assessment",
    "pawn_structure",
    "endgame",
]

CATEGORY_DESCRIPTIONS = {
    "plan": "A strategic objective or multi-step plan, not just an isolated tactical move.",
    "pawn_break": "A pawn advance or pawn capture intended to challenge a pawn chain or open lines. A piece sacrifice is not a pawn break.",
    "maneuver": "Piece development, placement or a multi-move piece route without an immediate forcing combination.",
    "tactic": "A concrete threat, combination, sacrifice or tactical motif, including speculative piece sacrifices.",
    "mistake": "An explicitly identified error, why it fails, and/or how the opponent exploits it.",
    "move_order": "A sequence, branch definition, transposition or dependency on the order of moves.",
    "assessment": "An evaluation or practical suitability judgment, such as whether a gambit is sound or risky.",
    "pawn_structure": "A description of pawn formations and their strategic consequences, rather than a particular pawn break.",
    "endgame": "An opening's resulting endgame features or endgame plans explicitly supported by the source.",
}
TAXONOMY_VERSION = "opening-topics-v2"
TAXONOMY_PROMPT = "\n".join(f"- {name}: {description}" for name, description in CATEGORY_DESCRIPTIONS.items())
