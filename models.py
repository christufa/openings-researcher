from pydantic import BaseModel


class QueriesResponse(BaseModel):
    queries: list[str]


class OpeningReport(BaseModel):
    opening: str
    eco_code: str       # e.g. "C65" — LLM fills from context, Lichess overrides
    moves: str          # main line e.g. "1. e4 e5 2. Nf3 Nc6 3. Bb5"
    summary: str
    ideas: list[str]
    white_plans: list[str]
    black_plans: list[str]
    common_mistakes: list[str]
    pawn_structures: list[str]
    study_advice: list[str]
    notable_players: list[str]  # GMs who championed or developed this opening
