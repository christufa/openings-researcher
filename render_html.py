#!/usr/bin/env python3
"""Render a single opening JSON report as a self-contained HTML page.

Usage:
    python render_html.py ruy_lopez.json
    python render_html.py ruy_lopez.json -o ruy_lopez.html
    python render_html.py data/ruy_lopez.json -o reports/ruy_lopez.html
"""

import argparse
import json
from html import escape
from pathlib import Path


# ── helpers ──────────────────────────────────────────────────────────────────

def h(text: str) -> str:
    return escape(str(text))


def bullet_list(items: list[str]) -> str:
    if not items:
        return "<p class='empty'>—</p>"
    return "<ul>" + "".join(f"<li>{h(i)}</li>" for i in items) + "</ul>"


def stat_bar(label: str, pct: float, color: str) -> str:
    return f"""
      <div class="bar-row">
        <span class="bar-label">{h(label)}</span>
        <div class="bar-track">
          <div class="bar-fill" style="width:{pct}%;background:{color}"></div>
        </div>
        <span class="bar-pct">{pct}%</span>
      </div>"""


# ── section builders ─────────────────────────────────────────────────────────

def build_plans(data: dict) -> str:
    return f"""
    <section class="card two-col">
      <div class="col col-white">
        <h2>⬜ White's Plans</h2>
        {bullet_list(data.get("white_plans", []))}
      </div>
      <div class="col col-black">
        <h2>⬛ Black's Plans</h2>
        {bullet_list(data.get("black_plans", []))}
      </div>
    </section>"""


def build_ideas_mistakes(data: dict) -> str:
    return f"""
    <section class="card two-col">
      <div class="col col-ideas">
        <h2>💡 Key Ideas</h2>
        {bullet_list(data.get("ideas", []))}
      </div>
      <div class="col col-mistakes">
        <h2>⚠️ Common Mistakes</h2>
        {bullet_list(data.get("common_mistakes", []))}
      </div>
    </section>"""


def build_structures_advice(data: dict) -> str:
    return f"""
    <section class="card two-col">
      <div class="col col-pawns">
        <h2>♟ Pawn Structures</h2>
        {bullet_list(data.get("pawn_structures", []))}
      </div>
      <div class="col col-study">
        <h2>📚 Study Advice</h2>
        {bullet_list(data.get("study_advice", []))}
      </div>
    </section>"""


def build_stats(stats: dict | None) -> str:
    if not stats:
        return ""
    total = f"{stats['total_games']:,}"
    return f"""
    <section class="card stats-card">
      <h2>Masters Database <span class="subtitle">({total} games)</span></h2>
      {stat_bar("White wins", stats['white_wins_pct'], "#f0d9b5")}
      {stat_bar("Draws",      stats['draws_pct'],      "#9e9e9e")}
      {stat_bar("Black wins", stats['black_wins_pct'], "#b58863")}
    </section>"""


def build_players(players: list[str]) -> str:
    if not players:
        return ""
    tags = "".join(f'<span class="tag">{h(p)}</span>' for p in players)
    return f"""
    <section class="card">
      <h2>🏆 Notable Players</h2>
      <div class="tags">{tags}</div>
    </section>"""


def build_variations(variations: list[dict]) -> str:
    if not variations:
        return ""
    rows = "".join(f"""
      <tr>
        <td><span class="eco-pill">{h(v.get('eco',''))}</span></td>
        <td>{h(v.get('name',''))}</td>
        <td class="moves-cell">{h(v.get('moves',''))}</td>
      </tr>""" for v in variations)
    return f"""
    <section class="card">
      <h2>🔀 Variations <span class="subtitle">({len(variations)} from ECO database)</span></h2>
      <div class="table-wrap">
        <table class="var-table">
          <thead><tr><th>ECO</th><th>Variation</th><th>Moves</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </section>"""


def build_games(games: list[dict]) -> str:
    if not games:
        return ""
    cards = ""
    for g in games:
        result = g.get("result", "?")
        result_cls = (
            "res-white" if result == "1-0" else
            "res-black" if result == "0-1" else
            "res-draw"
        )
        wr = f" <span class='rating'>({g['white_rating']})</span>" if g.get("white_rating") else ""
        br = f" <span class='rating'>({g['black_rating']})</span>" if g.get("black_rating") else ""
        url = g.get("lichess_url", "")
        link = f'<a class="lichess-link" href="{h(url)}" target="_blank">View on Lichess ↗</a>' if url else ""
        pgn_block = ""
        if g.get("pgn"):
            pgn_block = f'<details class="pgn-details"><summary>Show PGN</summary><pre class="pgn">{h(g["pgn"])}</pre></details>'
        cards += f"""
      <div class="game-card">
        <div class="game-header">
          <div class="game-players">
            <span class="player player-white">⬜ {h(g.get('white','?'))}{wr}</span>
            <span class="vs">vs</span>
            <span class="player player-black">⬛ {h(g.get('black','?'))}{br}</span>
          </div>
          <span class="game-result {result_cls}">{h(result)}</span>
        </div>
        <div class="game-meta">{h(g.get('year','?'))} &nbsp;{link}</div>
        {pgn_block}
      </div>"""
    return f"""
    <section class="card">
      <h2>♛ Famous Games</h2>
      {cards}
    </section>"""


def build_links(links: list[dict]) -> str:
    if not links:
        return ""
    items = ""
    for a in links:
        desc = f'<p class="link-desc">{h(a["description"])}</p>' if a.get("description") else ""
        items += f"""
      <li>
        <a href="{h(a['url'])}" target="_blank">{h(a['title'])}</a>
        {desc}
      </li>"""
    return f"""
    <section class="card">
      <h2>🔗 Articles &amp; Resources <span class="subtitle">({len(links)})</span></h2>
      <ul class="link-list">{items}</ul>
    </section>"""


# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #f4f1ec;
  color: #2c2c2c;
  line-height: 1.6;
}

/* ── header ── */
.site-header {
  background: #1b1b2e;
  color: #fff;
  padding: 2.5rem 2rem 2rem;
}
.header-inner { max-width: 900px; margin: 0 auto; }
.eco-badge {
  display: inline-block;
  background: #c9a84c;
  color: #1b1b2e;
  font-weight: 700;
  font-size: .8rem;
  letter-spacing: .08em;
  padding: .2rem .55rem;
  border-radius: 4px;
  margin-bottom: .6rem;
}
.header-inner h1 {
  font-size: 2.4rem;
  font-weight: 800;
  letter-spacing: -.02em;
  line-height: 1.1;
}
.moves-line {
  margin-top: .7rem;
  font-family: "Courier New", monospace;
  font-size: .95rem;
  color: #c9b37a;
  letter-spacing: .03em;
}
.summary-section {
  background: #252540;
  color: #d8d4cc;
  padding: 1.4rem 2rem;
  border-bottom: 3px solid #c9a84c;
}
.summary-section p { max-width: 900px; margin: 0 auto; font-size: 1rem; }

/* ── layout ── */
main { max-width: 900px; margin: 2rem auto; padding: 0 1rem; }

.card {
  background: #fff;
  border-radius: 10px;
  padding: 1.5rem 1.75rem;
  margin-bottom: 1.5rem;
  box-shadow: 0 1px 4px rgba(0,0,0,.08);
}

.card h2 {
  font-size: 1.05rem;
  font-weight: 700;
  margin-bottom: 1rem;
  color: #1b1b2e;
  display: flex;
  align-items: baseline;
  gap: .4rem;
}
.subtitle { font-weight: 400; font-size: .85rem; color: #777; }

.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
@media (max-width: 600px) { .two-col { grid-template-columns: 1fr; } }

.col { }
.col h2 { font-size: .95rem; }

.col-white  { border-left: 4px solid #f0d9b5; padding-left: .9rem; }
.col-black  { border-left: 4px solid #b58863; padding-left: .9rem; }
.col-ideas  { border-left: 4px solid #4caf50; padding-left: .9rem; }
.col-mistakes { border-left: 4px solid #e53935; padding-left: .9rem; }
.col-pawns  { border-left: 4px solid #c9a84c; padding-left: .9rem; }
.col-study  { border-left: 4px solid #7c4dff; padding-left: .9rem; }

ul { padding-left: 1.2rem; }
li { margin-bottom: .4rem; font-size: .93rem; }
.empty { color: #aaa; font-style: italic; font-size: .9rem; }

/* ── stat bars ── */
.bar-row {
  display: flex;
  align-items: center;
  gap: .75rem;
  margin-bottom: .5rem;
}
.bar-label { width: 80px; font-size: .85rem; color: #555; flex-shrink: 0; }
.bar-track {
  flex: 1;
  background: #eee;
  border-radius: 6px;
  height: 14px;
  overflow: hidden;
}
.bar-fill { height: 100%; border-radius: 6px; transition: width .4s; }
.bar-pct { width: 38px; text-align: right; font-size: .85rem; font-weight: 600; color: #333; }

/* ── tags ── */
.tags { display: flex; flex-wrap: wrap; gap: .45rem; }
.tag {
  background: #f0ece2;
  border: 1px solid #d8cebc;
  color: #4a3c28;
  font-size: .83rem;
  font-weight: 600;
  padding: .25rem .65rem;
  border-radius: 20px;
}

/* ── variations table ── */
.table-wrap { overflow-x: auto; }
.var-table { width: 100%; border-collapse: collapse; font-size: .88rem; }
.var-table th {
  text-align: left;
  padding: .5rem .7rem;
  background: #f7f4ef;
  border-bottom: 2px solid #e0d8cc;
  font-size: .8rem;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: #666;
}
.var-table td { padding: .5rem .7rem; border-bottom: 1px solid #f0ece4; vertical-align: top; }
.var-table tr:last-child td { border-bottom: none; }
.var-table tr:hover td { background: #faf8f4; }
.eco-pill {
  display: inline-block;
  background: #1b1b2e;
  color: #c9a84c;
  font-size: .75rem;
  font-weight: 700;
  padding: .15rem .45rem;
  border-radius: 4px;
  font-family: monospace;
}
.moves-cell { font-family: "Courier New", monospace; font-size: .82rem; color: #555; }

/* ── games ── */
.game-card {
  border: 1px solid #e8e2d8;
  border-radius: 8px;
  padding: 1rem 1.2rem;
  margin-bottom: 1rem;
  background: #fdfcfa;
}
.game-card:last-child { margin-bottom: 0; }
.game-header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.game-players { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }
.player { font-weight: 600; font-size: .92rem; }
.vs { color: #aaa; font-size: .8rem; }
.rating { font-weight: 400; color: #888; font-size: .82rem; }
.game-result {
  font-weight: 800;
  font-size: .95rem;
  padding: .2rem .55rem;
  border-radius: 5px;
  flex-shrink: 0;
}
.res-white { background: #f0d9b5; color: #5a3e00; }
.res-black { background: #b58863; color: #fff; }
.res-draw  { background: #e0e0e0; color: #555; }
.game-meta { margin-top: .4rem; font-size: .83rem; color: #888; }
.lichess-link { color: #7c4dff; text-decoration: none; font-weight: 600; margin-left: .3rem; }
.lichess-link:hover { text-decoration: underline; }
.pgn-details { margin-top: .75rem; }
.pgn-details summary {
  cursor: pointer;
  font-size: .83rem;
  color: #7c4dff;
  font-weight: 600;
  user-select: none;
}
.pgn {
  margin-top: .5rem;
  background: #1b1b2e;
  color: #c9b37a;
  font-family: "Courier New", monospace;
  font-size: .78rem;
  padding: .9rem 1rem;
  border-radius: 6px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.5;
}

/* ── article links ── */
.link-list { list-style: none; padding: 0; }
.link-list li { padding: .6rem 0; border-bottom: 1px solid #f0ece4; }
.link-list li:last-child { border-bottom: none; }
.link-list a { color: #1a6fc4; font-weight: 600; font-size: .93rem; text-decoration: none; }
.link-list a:hover { text-decoration: underline; }
.link-desc { font-size: .82rem; color: #777; margin-top: .2rem; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }

footer {
  text-align: center;
  padding: 2rem 1rem;
  font-size: .8rem;
  color: #aaa;
}
"""

# ── main renderer ─────────────────────────────────────────────────────────────

def render(data: dict) -> str:
    opening = data.get("opening", "Unknown Opening")
    eco     = data.get("eco_code", "")
    moves   = data.get("moves", "")
    summary = data.get("summary", "")

    eco_html   = f'<div class="eco-badge">{h(eco)}</div>' if eco else ""
    moves_html = f'<div class="moves-line">{h(moves)}</div>' if moves else ""

    body = "\n".join([
        build_stats(data.get("explorer_stats")),
        build_players(data.get("notable_players", [])),
        build_plans(data),
        build_ideas_mistakes(data),
        build_structures_advice(data),
        build_variations(data.get("variations", [])),
        build_games(data.get("famous_games", [])),
        build_links(data.get("article_links", [])),
    ])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{h(opening)}</title>
  <style>{CSS}</style>
</head>
<body>

<header class="site-header">
  <div class="header-inner">
    {eco_html}
    <h1>{h(opening)}</h1>
    {moves_html}
  </div>
</header>

<div class="summary-section">
  <p>{h(summary)}</p>
</div>

<main>
  {body}
</main>

<footer>Generated by openings-researcher</footer>

</body>
</html>"""


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render an opening JSON report as a self-contained HTML page."
    )
    parser.add_argument("input", metavar="FILE", help="Path to the opening JSON file.")
    parser.add_argument(
        "-o", "--output",
        metavar="FILE",
        help="Output HTML path (default: same name as input with .html extension).",
    )
    args = parser.parse_args()

    src = Path(args.input)
    dst = Path(args.output) if args.output else src.with_suffix(".html")

    data = json.loads(src.read_text(encoding="utf-8"))
    html = render(data)
    dst.write_text(html, encoding="utf-8")
    print(f"Rendered -> {dst}")


if __name__ == "__main__":
    main()
