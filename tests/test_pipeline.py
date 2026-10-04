import copy
import json

import chess
import pytest

from openings_research.agents import Extraction, FixtureAgent
from openings_research.collectors import FixtureCollector
from openings_research.contracts import (
    AgentOutput,
    Evidence,
    LineCandidate,
    Source,
    position_record,
)
from openings_research.pipeline import STAGES, NoValidCandidatesError, Pipeline, provenance_config
from openings_research.review import FixtureReviewer, ReviewDecision, ReviewExtraction, ReviewOutput
from openings_research.schema import KEYS
from openings_research.validation import validate_candidate


class MemoryStore:
    def __init__(self):
        self.tables = {}
        self.fail_table = None

    def upsert(self, table, rows):
        if self.fail_table == table:
            raise RuntimeError("Simulated interrupted write")
        target = self.tables.setdefault(table, {})
        for row in rows:
            target[row[KEYS[table]]] = copy.deepcopy(row)

    def read(self, table, **filters):
        return [
            copy.deepcopy(r)
            for r in self.tables.get(table, {}).values()
            if all(r.get(k) == v for k, v in filters.items())
        ]

    def sources_for_run(self, run_id):
        result = []
        for link in self.read("run_sources", run_id=run_id):
            version = self.read("source_versions", source_version_id=link["source_version_id"])[0]
            source = self.read("sources", source_id=version["source_id"])[0]
            result.append(
                {
                    "source_version_id": version["source_version_id"],
                    "url": source["url"],
                    "title": version["title"],
                    "content": version["content"],
                }
            )
        return result


def config(**overrides):
    return provenance_config(
        **(
            {
                "opening": "__smoke_italian__",
                "mode": "refresh",
                "source_run_id": "",
                "agent": "fixture",
                "model": "fixture",
                "code_version": "test",
            }
            | overrides
        )
    )


def execute_all(pipeline, agent=None):
    for stage in STAGES:
        pipeline.execute(
            stage, collector=FixtureCollector(), agent=agent or FixtureAgent(), reviewer=FixtureReviewer()
        )


def test_transpositions_share_identity_but_castling_and_turn_matter():
    first = chess.Board()
    second = chess.Board()
    for san in ["Nf3", "Nf6", "g3", "g6"]:
        first.push_san(san)
    for san in ["g3", "g6", "Nf3", "Nf6"]:
        second.push_san(san)
    assert position_record(first) == position_record(second)
    second.turn = not second.turn
    assert position_record(first) != position_record(second)
    board = chess.Board()
    original = position_record(board)
    board.castling_rights = 0
    assert position_record(board) != original


def test_normalizes_nonlegal_en_passant_and_counters():
    board = chess.Board()
    board.push_san("e4")
    alternate = chess.Board(board.fen(en_passant="fen"))
    alternate.ep_square = None
    alternate.fullmove_number = 12
    alternate.halfmove_clock = 8
    assert position_record(board) == position_record(alternate)


def test_legal_en_passant_is_part_of_identity():
    board = chess.Board()
    for san in ["e4", "a6", "e5", "d5"]:
        board.push_san(san)
    original = position_record(board)
    board.ep_square = None
    assert original != position_record(board)


@pytest.mark.parametrize("moves", [["e5"], ["--"], ["e4", "e4"]])
def test_rejects_illegal_or_null_moves(moves):
    source = Source(source_version_id="s", url="fixture://s", title="s", content="test evidence")
    line = LineCandidate(
        name="test",
        start_fen=chess.STARTING_FEN,
        moves_san=moves,
        evidence=[Evidence(source_version_id="s", excerpt=source.content, relation="supports")],
    )
    with pytest.raises(ValueError):
        validate_candidate(line, [source])


@pytest.mark.parametrize("source_id,excerpt", [("missing", "e4"), ("s", "invented"), ("s", " ")])
def test_rejects_untraceable_evidence(source_id, excerpt):
    source = Source(source_version_id="s", url="fixture://s", title="s", content="e4")
    line = LineCandidate(
        name="test",
        start_fen=chess.STARTING_FEN,
        moves_san=["e4"],
        evidence=[Evidence(source_version_id=source_id, excerpt=excerpt, relation="supports")],
    )
    with pytest.raises(ValueError):
        validate_candidate(line, [source])


def test_pipeline_repairs_without_duplicate_records_or_repeated_agent_calls():
    store = MemoryStore()
    pipeline = Pipeline(store, "run1", config())
    execute_all(pipeline)
    counts = {t: len(rows) for t, rows in store.tables.items()}
    execute_all(pipeline, agent=object())
    assert counts == {t: len(rows) for t, rows in store.tables.items()}
    assert store.read("research_runs")[0]["status"] == "completed"
    assert len(store.read("positions")) == 6
    assert store.read("claims")[0]["review_status"] == "fixture_reviewed"


def test_reextract_reuses_exact_sources_and_deduplicates_chess_entities():
    store = MemoryStore()
    execute_all(Pipeline(store, "run1", config()))
    pipeline = Pipeline(store, "run2", config(mode="reextract", source_run_id="run1"))
    pipeline.execute("collect", collector=object())
    for stage in STAGES[1:]:
        pipeline.execute(stage, agent=FixtureAgent(), reviewer=FixtureReviewer())
    assert len(store.read("source_versions")) == 1
    assert len(store.read("positions")) == 6
    assert len(store.read("lines")) == 1
    assert len(store.read("claims")) == 2
    assert store.sources_for_run("run1") == store.sources_for_run("run2")


def test_interrupted_publication_is_not_completed_and_can_be_repaired():
    store = MemoryStore()
    pipeline = Pipeline(store, "run1", config())
    for stage in STAGES[:-1]:
        pipeline.execute(
            stage, collector=FixtureCollector(), agent=FixtureAgent(), reviewer=FixtureReviewer()
        )
    store.fail_table = "claims"
    with pytest.raises(RuntimeError):
        pipeline.execute("publish")
    assert store.read("research_runs")[0]["status"] == "failed"
    assert store.read("research_runs")[0]["completed_at"] is None
    store.fail_table = None
    pipeline.execute("publish")
    assert store.read("research_runs")[0]["status"] == "completed"
    assert len(store.read("opening_lines")) == 1


def test_changed_agent_requires_a_new_run_id():
    store = MemoryStore()
    execute_all(Pipeline(store, "run1", config()))
    with pytest.raises(ValueError, match="configuration changed"):
        Pipeline(store, "run1", config(model="other")).execute("extract")


def test_reextract_rejects_unrelated_opening():
    store = MemoryStore()
    execute_all(Pipeline(store, "run1", config()))
    with pytest.raises(ValueError, match="different opening"):
        Pipeline(
            store, "run2", config(opening="French Defense", mode="reextract", source_run_id="run1")
        ).execute("collect")


def test_empty_agent_output_is_not_published():
    class EmptyAgent:
        def extract(self, request):
            return Extraction(AgentOutput(lines=[], claims=[], unresolved_questions=["No evidence"]), "{}")

    store = MemoryStore()
    pipeline = Pipeline(store, "run1", config())
    pipeline.execute("collect", collector=FixtureCollector())
    with pytest.raises(ValueError, match="no candidates"):
        pipeline.execute("extract", agent=EmptyAgent())
    assert store.read("research_runs")[0]["status"] == "failed"
    assert json.loads(store.read("agent_outputs")[0]["output_json"])["unresolved_questions"]


def test_invalid_candidates_are_retained_but_not_published():
    class BadAgent(FixtureAgent):
        def extract(self, request):
            result = super().extract(request)
            result.output.lines[0].moves_san = ["e5"]
            return result

    store = MemoryStore()
    execute_all(Pipeline(store, "run1", config()), agent=BadAgent())
    assert len(store.read("candidate_records")) == 2
    assert len(store.read("validation_results", valid=False)) == 1
    assert not store.read("lines")
    assert len(store.read("claims")) == 1


def test_all_rejected_batch_reports_counts_and_cannot_publish(capsys):
    class ParaphrasingAgent(FixtureAgent):
        def extract(self, request):
            result = super().extract(request)
            for candidate in result.output.lines + result.output.claims:
                candidate.evidence[0].excerpt = "A paraphrase, not an exact passage."
            return result

    store = MemoryStore()
    pipeline = Pipeline(store, "rejected", config())
    for stage in STAGES[:-1]:
        pipeline.execute(
            stage, collector=FixtureCollector(), agent=ParaphrasingAgent(), reviewer=FixtureReviewer()
        )
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert next(e for e in events if e["event"] == "validation_summary") == {
        "event": "validation_summary",
        "run_id": "rejected",
        "valid": 0,
        "rejected": 2,
    }
    with pytest.raises(NoValidCandidatesError):
        pipeline.execute("publish")
    assert not store.read("claims")
    assert not store.read("opening_lines")
    assert len(store.read("candidate_records")) == 2
    assert store.read("research_tasks", stage="publish")[0]["error_type"] == "NoValidCandidatesError"


def test_review_can_correct_category_without_overwriting_original_candidate():
    class CorrectingReviewer(FixtureReviewer):
        def review(self, opening, candidates, source_urls):
            result = super().review(opening, candidates, source_urls)
            for review in result.output.reviews:
                if review.category is not None:
                    review.category = "maneuver"
                    review.rationale = "This describes piece development rather than a strategic plan."
            return result

    store = MemoryStore()
    pipeline = Pipeline(store, "r", config())
    for stage in STAGES:
        pipeline.execute(
            stage, collector=FixtureCollector(), agent=FixtureAgent(), reviewer=CorrectingReviewer()
        )
    assert store.read("claims")[0]["category"] == "maneuver"
    original = store.read("candidate_records", kind="claim")[0]
    assert json.loads(original["payload_json"])["category"] == "plan"
    report = json.loads(store.read("coverage_reports")[0]["report_json"])
    assert any(g["topic"] == "plan" and g["side"] == "white" for g in report["gaps"])
    assert report["published_claims"] == 1
    assert store.read("research_gaps")


def test_unsupported_claim_is_retained_but_excluded_from_publication_and_coverage():
    class RejectClaimReviewer(FixtureReviewer):
        def review(self, opening, candidates, source_urls):
            result = super().review(opening, candidates, source_urls)
            for review in result.output.reviews:
                if review.category is not None:
                    review.decision = "reject"
            return result

    store = MemoryStore()
    pipeline = Pipeline(store, "r", config())
    for stage in STAGES:
        pipeline.execute(
            stage, collector=FixtureCollector(), agent=FixtureAgent(), reviewer=RejectClaimReviewer()
        )
    assert len(store.read("candidate_records")) == 2
    assert not store.read("claims")
    assert len(store.read("opening_lines")) == 1
    assert json.loads(store.read("coverage_reports")[0]["report_json"])["published_claims"] == 0
    accepted_ids = {r["candidate_id"] for r in store.read("candidate_reviews", decision="accept")}
    assert {r["candidate_id"] for r in store.read("claim_evidence")} == accepted_ids


def test_review_cache_survives_interrupted_write_and_does_not_call_reviewer_again():
    store = MemoryStore()
    pipeline = Pipeline(store, "r", config())
    for stage in STAGES[:3]:
        pipeline.execute(stage, collector=FixtureCollector(), agent=FixtureAgent())
    store.fail_table = "candidate_reviews"
    with pytest.raises(RuntimeError):
        pipeline.execute("review", reviewer=FixtureReviewer())
    assert store.read("review_outputs")
    store.fail_table = None
    pipeline.execute("review", reviewer=object())
    pipeline.execute("publish")
    assert store.read("research_runs")[0]["status"] == "completed"


def test_partial_review_cannot_publish():
    class PartialReviewer:
        def review(self, opening, candidates, source_urls):
            output = ReviewOutput(
                reviews=[
                    ReviewDecision(
                        candidate_id=candidates[0]["candidate_id"],
                        decision="reject",
                        category=None,
                        rationale="No support",
                    )
                ]
            )
            return ReviewExtraction(output, output.model_dump_json())

    store = MemoryStore()
    pipeline = Pipeline(store, "r", config())
    for stage in STAGES[:3]:
        pipeline.execute(stage, collector=FixtureCollector(), agent=FixtureAgent())
    with pytest.raises(ValueError, match="exactly once"):
        pipeline.execute("review", reviewer=PartialReviewer())
    assert store.read("review_outputs")
    with pytest.raises(ValueError, match="Previous stage"):
        pipeline.execute("publish")
    assert not store.read("claims")


def test_coverage_failure_keeps_run_unpublished_until_repaired():
    store = MemoryStore()
    pipeline = Pipeline(store, "r", config())
    for stage in STAGES[:-1]:
        pipeline.execute(
            stage, collector=FixtureCollector(), agent=FixtureAgent(), reviewer=FixtureReviewer()
        )
    store.fail_table = "coverage_reports"
    with pytest.raises(RuntimeError):
        pipeline.execute("publish")
    assert store.read("research_runs")[0]["status"] == "failed"
    store.fail_table = None
    pipeline.execute("publish")
    assert store.read("research_runs")[0]["status"] == "completed"
    assert len(store.read("claims")) == 1


def test_reextract_receives_previous_claims_and_coverage_gaps():
    class CheckingAgent(FixtureAgent):
        def extract(self, request):
            assert request.existing_claims
            assert any("black plan" in gap for gap in request.coverage_gaps)
            return super().extract(request)

    store = MemoryStore()
    execute_all(Pipeline(store, "first", config()))
    execute_all(Pipeline(store, "second", config(mode="reextract", source_run_id="first")), CheckingAgent())
