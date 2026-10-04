"""Presence-based coverage diagnostics, not a claim of theoretical completeness."""

from urllib.parse import urlsplit

from .contracts import Source, stable_id
from .taxonomy import CATEGORY_DESCRIPTIONS

COVERAGE_VERSION = "topic-side-presence-v1"
PRIORITY = {
    "plan": 1,
    "mistake": 1,
    "pawn_break": 2,
    "pawn_structure": 2,
    "maneuver": 2,
    "tactic": 2,
    "move_order": 2,
    "assessment": 3,
    "endgame": 3,
}


def coverage_report(
    opening: str,
    claims: list[dict],
    lines: list[dict],
    evidence: list[dict],
    sources: list[Source],
    validation_counts: dict,
    review_counts: dict,
) -> dict:
    # Multiple citations of one claim do not increase its topic coverage.
    unique_claims = {c["claim_id"]: c for c in claims}.values()
    unique_lines = {line["line_id"] for line in lines}
    source_lookup = {s.source_version_id: s for s in sources}
    used_ids = {e["source_version_id"] for e in evidence}
    urls = {source_lookup[s].url for s in used_ids if s in source_lookup}
    hosts = {urlsplit(url).hostname for url in urls if url.startswith(("http://", "https://"))}
    topics = []
    gaps = []
    for category in CATEGORY_DESCRIPTIONS:
        for side in ("white", "black"):
            count = sum(c["category"] == category and c["side"] in (side, "both") for c in unique_claims)
            topics.append(
                {
                    "category": category,
                    "side": side,
                    "claims": count,
                    "status": "present" if count else "missing",
                }
            )
            if not count:
                gaps.append(
                    {
                        "topic": category,
                        "side": side,
                        "priority": PRIORITY[category],
                        "reason": "No published model-reviewed claim covers this topic and side.",
                        "query": f"{opening} chess {side} {category.replace('_', ' ')} examples",
                    }
                )
    positioned = sum(c["position_id"] is not None for c in unique_claims)
    if not positioned:
        gaps.append(
            {
                "topic": "position_context",
                "side": "both",
                "priority": 1,
                "reason": "No published claim is anchored to a valid board position.",
                "query": f"{opening} critical positions plans annotated move sequences",
            }
        )
    if len(urls) < 2:
        gaps.append(
            {
                "topic": "source_diversity",
                "side": "both",
                "priority": 2,
                "reason": "Published evidence uses fewer than two source URLs; corroboration is limited.",
                "query": f"{opening} annotated opening theory alternative analysis",
            }
        )
    if not unique_lines:
        gaps.append(
            {
                "topic": "opening_lines",
                "side": "both",
                "priority": 1,
                "reason": "No source-supported, model-reviewed lines are published.",
                "query": f"{opening} main lines variations move orders",
            }
        )
    # A handful of line names cannot establish coverage of an opening family.
    gaps.append(
        {
            "topic": "branch_benchmark",
            "side": "both",
            "priority": 2,
            "reason": "No curated list of required branches is configured; branch completeness is unknown.",
            "query": f"{opening} major variations opening classification ECO",
        }
    )
    return {
        "coverage_version": COVERAGE_VERSION,
        "opening": opening,
        "published_claims": len(list(unique_claims)),
        "published_lines": len(unique_lines),
        "positioned_claims": positioned,
        "source_urls_used": len(urls),
        "source_hosts_used": len(hosts),
        "source_independence": "not_assessed",
        "branch_completeness": "not_assessed",
        "topics": topics,
        "validation_counts": validation_counts,
        "review_counts": review_counts,
        "gaps": sorted(gaps, key=lambda g: (g["priority"], g["topic"], g["side"])),
        "scope": "Topic presence in this run's published snapshot; not theoretical completeness or human verification.",
    }


def gap_records(run_id: str, opening_id: str, report: dict) -> list[dict]:
    return [
        {
            **gap,
            "gap_id": stable_id(run_id, gap["topic"], gap["side"]),
            "run_id": run_id,
            "opening_id": opening_id,
            "status": "open",
        }
        for gap in report["gaps"]
    ]
