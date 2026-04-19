# Openings Researcher

Researches chess openings using web search and produces structured coaching reports via OpenAI structured outputs.

## Setup

```bash
pip install openai tavily-python pydantic requests
export OPENAI_API_KEY=...
export TAVILY_API_KEY=...
```

## Usage

**Research all openings from a JSON list:**
```bash
python main.py --openings-file openings.json --data-dir ./data
```

**Research a single opening:**
```bash
python main.py --opening "Sicilian Defense"
```

**All options:**
```
--opening NAME          Research a single opening by name
--openings-file PATH    JSON file with a list of opening names (default: openings.json)
--data-dir PATH         Output directory for JSON reports (default: ./data)
--request-delay SECS    Delay between requests in seconds (default: 1.0)
--log-level LEVEL       DEBUG | INFO | WARNING | ERROR (default: INFO)
```

## Output

Each opening is saved as `<slug>.json` in `--data-dir`. A `_manifest.json` summary is written after a batch run.

```json
{
  "opening": "Ruy Lopez (Spanish Opening)",
  "eco_code": "C60",
  "moves": "1. e4 e5 2. Nf3 Nc6 3. Bb5",
  "summary": "...",
  "ideas": ["..."],
  "white_plans": ["..."],
  "black_plans": ["..."],
  "common_mistakes": ["..."],
  "pawn_structures": ["..."],
  "study_advice": ["..."],
  "notable_players": ["Magnus Carlsen", "Bobby Fischer", "..."],
  "variations": [
    { "name": "Berlin Defense", "eco": "C65", "moves": "1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6" },
    { "name": "Morphy Defense", "eco": "C78", "moves": "..." }
  ],
  "article_links": [
    { "title": "Ruy Lopez Guide", "url": "https://...", "description": "..." }
  ],
  "famous_games": [
    {
      "white": "Fischer, R", "white_rating": 2785,
      "black": "Spassky, B", "black_rating": 2660,
      "year": 1972, "result": "1-0",
      "lichess_url": "https://lichess.org/...",
      "pgn": "[Event ...] 1. e4 e5 ..."
    }
  ],
  "explorer_stats": {
    "white_wins_pct": 35.2,
    "draws_pct": 37.1,
    "black_wins_pct": 27.7,
    "total_games": 198432
  },
  "_meta": { "opening": "Ruy Lopez", "slug": "ruy_lopez" }
}
```

### Data sources

| Field | Source |
|---|---|
| `eco_code`, `moves` | Lichess ECO database (ground truth), LLM fallback |
| `variations` | Lichess ECO database |
| `explorer_stats` | Lichess Masters Opening Explorer |
| `famous_games` + `pgn` | Lichess Masters Explorer + game export API |
| `article_links` | Tavily web search results |
| All text fields | OpenAI structured output (GPT-4.1-mini) |

## HTML Reports

Render any opening JSON as a self-contained HTML page:

```bash
python render_html.py data/ruy_lopez.json
# → data/ruy_lopez.html

python render_html.py data/ruy_lopez.json -o reports/ruy_lopez.html
```

The HTML report includes all fields in a structured layout:
- ECO code, main-line moves, and summary in a dark header
- Masters database win/draw/loss bars (from Lichess explorer)
- Notable players as tags
- Side-by-side cards: White plans vs Black plans, Key ideas vs Common mistakes, Pawn structures vs Study advice
- Variations table (ECO code, name, full move sequence)
- Famous games with expandable PGN and Lichess links
- Article links with descriptions

No external dependencies — the HTML file is fully self-contained.

## File Structure

```
├── main.py          # CLI entry point
├── agent.py         # Orchestration: Lichess + web search + LLM synthesis
├── lichess.py       # ECO database, Opening Explorer, game PGN fetching
├── search.py        # Tavily web search (returns content + article refs)
├── models.py        # Pydantic schemas for OpenAI structured outputs
├── render_html.py   # Renders a JSON report as a self-contained HTML page
└── openings.json    # List of opening names to research
```
