import io
import csv
import logging
import requests
from functools import lru_cache

log = logging.getLogger(__name__)

_ECO_TSV_URLS = [
    "https://raw.githubusercontent.com/lichess-org/chess-openings/master/a.tsv",
    "https://raw.githubusercontent.com/lichess-org/chess-openings/master/b.tsv",
    "https://raw.githubusercontent.com/lichess-org/chess-openings/master/c.tsv",
    "https://raw.githubusercontent.com/lichess-org/chess-openings/master/d.tsv",
    "https://raw.githubusercontent.com/lichess-org/chess-openings/master/e.tsv",
]
_EXPLORER_URL = "https://explorer.lichess.ovh/masters"
_GAME_EXPORT_URL = "https://lichess.org/game/export/{}"
_MASTER_PGN_URL = "https://explorer.lichess.ovh/masters/pgn/{}"


@lru_cache(maxsize=1)
def _load_eco_db() -> list[dict]:
    rows = []
    for url in _ECO_TSV_URLS:
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            reader = csv.DictReader(io.StringIO(r.text), delimiter="\t")
            rows.extend(list(reader))
        except Exception as e:
            log.warning(f"ECO fetch failed {url}: {e}")
    log.info(f"ECO database: {len(rows)} entries loaded")
    return rows


def _word_overlap(query: str, name: str) -> float:
    """Fraction of query words found in name (case-insensitive, punctuation-tolerant)."""
    def tokenize(s: str) -> set[str]:
        return set(s.lower().replace(":", "").replace(",", "").replace("'", "").split())
    q = tokenize(query)
    n = tokenize(name)
    return len(q & n) / len(q) if q else 0.0


def find_opening(name: str) -> dict | None:
    """Find the best ECO entry for an opening name. Prefers shorter (more general) matches."""
    db = _load_eco_db()
    best, best_score, best_len = None, 0.0, float("inf")
    for entry in db:
        score = _word_overlap(name, entry["name"])
        entry_len = len(entry["name"].split())
        if score > best_score or (score == best_score and entry_len < best_len):
            best_score = score
            best = entry
            best_len = entry_len
    return best if best_score >= 0.6 else None


def get_variations(canonical_name: str, limit: int = 12) -> list[dict]:
    """Return named sub-variations of an opening using the ECO database."""
    db = _load_eco_db()
    prefix_colon = canonical_name.lower() + ":"
    prefix_comma = canonical_name.lower() + ","
    results = []
    for entry in db:
        entry_lower = entry["name"].lower()
        if entry_lower == canonical_name.lower():
            continue
        if entry_lower.startswith(prefix_colon) or entry_lower.startswith(prefix_comma):
            sep = ":" if entry_lower.startswith(prefix_colon) else ","
            var_part = entry["name"].split(sep, 1)[1].strip()
            results.append({
                "name": var_part,
                "eco": entry["eco"],
                "moves": entry["pgn"],
            })
    return results[:limit]


def get_explorer_data(epd: str, top_games: int = 5) -> dict | None:
    """Query the Lichess masters opening explorer for a position."""
    try:
        r = requests.get(
            _EXPLORER_URL,
            params={"fen": epd, "topGames": top_games, "moves": 15},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"Explorer API failed for epd={epd!r}: {e}")
        return None


def get_game_pgn(game_id: str) -> str | None:
    """Fetch PGN for a game — tries Lichess game export first, then masters PGN endpoint."""
    headers = {"Accept": "application/x-chess-pgn"}
    urls = [
        (_GAME_EXPORT_URL.format(game_id),
         {"clocks": "false", "evals": "false", "opening": "false"}),
        (_MASTER_PGN_URL.format(game_id), {}),
    ]
    for url, params in urls:
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            if r.status_code == 200 and r.text.strip():
                return r.text.strip()
            log.debug(f"PGN fetch {url} → {r.status_code}")
        except Exception as e:
            log.debug(f"PGN fetch error {url}: {e}")
    log.warning(f"Could not fetch PGN for game {game_id}")
    return None
