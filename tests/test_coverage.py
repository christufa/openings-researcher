from openings_research.contracts import Source
from openings_research.coverage import coverage_report, gap_records


def test_coverage_uses_published_unique_claims_and_keeps_sides_separate():
    claim = {"claim_id": "a", "category": "plan", "side": "white", "position_id": None}
    report = coverage_report("Italian Game", [claim, claim], [], [], [], {}, {})
    assert report["published_claims"] == 1
    topics = {(t["category"], t["side"]): t for t in report["topics"]}
    assert topics["plan", "white"]["status"] == "present"
    assert topics["plan", "black"]["status"] == "missing"
    assert any(g["topic"] == "position_context" for g in report["gaps"])
    assert report["branch_completeness"] == "not_assessed"
    assert report["source_independence"] == "not_assessed"


def test_both_side_claims_cover_both_slots_and_urls_are_deduplicated():
    claim = {"claim_id": "a", "category": "pawn_structure", "side": "both", "position_id": "position"}
    sources = [
        Source(source_version_id=s, url="https://example.org/article", title="s", content="s")
        for s in ("a", "b")
    ]
    report = coverage_report(
        "Italian Game",
        [claim],
        [{"line_id": "l"}, {"line_id": "l"}],
        [{"source_version_id": "a"}, {"source_version_id": "b"}],
        sources,
        {},
        {},
    )
    assert report["source_urls_used"] == 1
    assert report["published_lines"] == 1
    assert not any(
        g["topic"] in ("pawn_structure", "position_context", "opening_lines") for g in report["gaps"]
    )
    assert any(g["topic"] == "source_diversity" for g in report["gaps"])
    assert gap_records("r", "o", report) == gap_records("r", "o", report)
    assert all(r["query"].startswith("Italian Game") for r in gap_records("r", "o", report))
