import os
import logging
import time
from openai import OpenAI
from models import QueriesResponse, OpeningReport
from search import search_web
from lichess import find_opening, get_variations, get_explorer_data, get_game_pgn

log = logging.getLogger(__name__)

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


def generate_queries(opening_name: str) -> list[str]:
    prompt = f"""You are a chess research query generator.

Generate 8 specific search queries to comprehensively research the {opening_name} chess opening:
1. General overview, history, and origins
2. Strategic concepts and key ideas
3. White's plans, attacking ideas, and typical piece maneuvers
4. Black's plans, counterplay, and defensive resources
5. Common mistakes, traps, and tactical motifs
6. Pawn structure analysis and endgame characteristics
7. Famous games and notable grandmasters who championed this opening
8. Key sub-variations and modern theoretical developments"""

    response = _client.beta.chat.completions.parse(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=QueriesResponse,
        temperature=0.3,
    )
    result = response.choices[0].message.parsed
    if result is None:
        suffixes = ["overview history", "strategic ideas", "white plans", "black plans",
                    "traps tactics", "pawn structure", "famous games grandmasters", "variations theory"]
        return [f"{opening_name} chess {s}" for s in suffixes]
    return result.queries


def synthesize(opening_name: str, context: str, lichess_entry: dict | None) -> dict:
    lichess_hint = ""
    if lichess_entry:
        lichess_hint = (
            f"\nVerified ECO data: {lichess_entry.get('eco', '')} — "
            f"{lichess_entry.get('name', opening_name)}\n"
            f"Main line moves: {lichess_entry.get('pgn', '')}\n"
        )

    prompt = f"""You are an expert chess coach and opening theorist.

Using the context below, create a comprehensive structured coaching report for the {opening_name} chess opening.
{lichess_hint}
Guidelines:
- ideas, white_plans, black_plans, common_mistakes: 5 bullet points each
- pawn_structures: 3-5 bullet points
- study_advice: 3-5 bullet points
- notable_players: 3-8 grandmasters known for playing or developing this opening
- eco_code: the ECO classification (e.g. C65, B90, D30); use the verified data above if provided
- moves: the main line in algebraic notation (e.g. "1. e4 e5 2. Nf3 Nc6 3. Bb5"); use verified data if provided
- Do NOT invent facts not supported by the context or verified ECO data

CONTEXT:
{context}"""

    response = _client.beta.chat.completions.parse(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=OpeningReport,
        temperature=0.3,
    )
    result = response.choices[0].message.parsed
    if result is None:
        log.warning(f"Structured output returned None for {opening_name}")
        return {"error": "Failed to parse model output"}
    return result.model_dump()


def _build_explorer_stats(explorer: dict) -> dict | None:
    white = explorer.get("white", 0)
    draws = explorer.get("draws", 0)
    black = explorer.get("black", 0)
    total = white + draws + black
    if total == 0:
        return None
    return {
        "white_wins_pct": round(white / total * 100, 1),
        "draws_pct": round(draws / total * 100, 1),
        "black_wins_pct": round(black / total * 100, 1),
        "total_games": total,
    }


def _build_famous_games(top_games: list[dict], pgn_limit: int = 3) -> list[dict]:
    games = []
    for i, game in enumerate(top_games):
        game_id = game.get("id", "")
        winner = game.get("winner")
        result_str = "1-0" if winner == "white" else ("0-1" if winner == "black" else "1/2-1/2")
        pgn = get_game_pgn(game_id) if game_id and i < pgn_limit else None
        games.append({
            "white": game.get("white", {}).get("name", "Unknown"),
            "white_rating": game.get("white", {}).get("rating"),
            "black": game.get("black", {}).get("name", "Unknown"),
            "black_rating": game.get("black", {}).get("rating"),
            "year": game.get("year"),
            "month": game.get("month", ""),
            "result": result_str,
            "lichess_url": f"https://lichess.org/{game_id}" if game_id else "",
            "pgn": pgn or "",
        })
        if game_id and i < pgn_limit:
            time.sleep(0.3)
    return games


class OpeningResearchAgent:
    def __init__(self, request_delay: float = 1.0, context_chunks: int = 15):
        self.request_delay = request_delay
        self.context_chunks = context_chunks

    def run(self, opening_name: str) -> dict:
        # 1. Lichess ECO lookup
        lichess_entry = find_opening(opening_name)
        if lichess_entry:
            log.debug(f"Lichess ECO match: {lichess_entry['name']} ({lichess_entry['eco']})")
            canonical_name = lichess_entry["name"]
        else:
            log.debug(f"No Lichess ECO match for: {opening_name}")
            canonical_name = opening_name

        variations = get_variations(canonical_name)

        # 2. Opening Explorer: stats + famous games
        explorer_stats = None
        famous_games = []
        epd = lichess_entry and (lichess_entry.get("epd") or lichess_entry.get("fen"))
        if epd:
            explorer = get_explorer_data(epd, top_games=5)
            if explorer:
                explorer_stats = _build_explorer_stats(explorer)
                famous_games = _build_famous_games(explorer.get("topGames", []))

        # 3. Web search: content + article links
        queries = generate_queries(opening_name)
        log.debug(f"Queries: {queries}")

        all_content: list[str] = []
        all_articles: list[dict] = []
        seen_urls: set[str] = set()

        for q in queries:
            chunks, articles = search_web(q)
            all_content.extend(chunks)
            for article in articles:
                url = article.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_articles.append(article)
            time.sleep(self.request_delay / len(queries))

        # 4. LLM synthesis
        context = "\n\n".join(all_content[: self.context_chunks])
        result = synthesize(opening_name, context, lichess_entry)

        # 5. Override eco/moves with ground-truth Lichess data
        if lichess_entry:
            result["eco_code"] = lichess_entry.get("eco", result.get("eco_code", ""))
            result["moves"] = lichess_entry.get("pgn", result.get("moves", ""))

        # 6. Attach structured data from Lichess + Tavily
        result["variations"] = variations
        result["article_links"] = all_articles[:20]
        result["famous_games"] = famous_games
        result["explorer_stats"] = explorer_stats

        return result
