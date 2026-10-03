"""Explicit Delta schemas, all within a single Unity Catalog schema."""

TABLES = {
    "research_runs": "run_id STRING, opening_id STRING, opening STRING, config_json STRING, status STRING, created_at STRING, completed_at STRING",
    "research_tasks": "task_id STRING, run_id STRING, stage STRING, status STRING, error_type STRING, updated_at STRING",
    "raw_responses": "response_id STRING, run_id STRING, provider STRING, request_json STRING, response_json STRING, created_at STRING",
    "sources": "source_id STRING, url STRING",
    "source_versions": "source_version_id STRING, source_id STRING, title STRING, content STRING, content_hash STRING, retrieved_at STRING",
    "run_sources": "link_id STRING, run_id STRING, source_version_id STRING",
    "agent_outputs": "run_id STRING, output_json STRING, raw_response STRING, usage_json STRING, created_at STRING",
    "candidate_records": "candidate_id STRING, run_id STRING, kind STRING, payload_json STRING",
    "validation_results": "candidate_id STRING, run_id STRING, valid BOOLEAN, reason STRING, normalized_json STRING, validator_version STRING",
    "openings": "opening_id STRING, name STRING",
    "positions": "position_id STRING, normalized_fen STRING, identity_version STRING",
    "position_moves": "move_id STRING, from_position_id STRING, to_position_id STRING, uci STRING, san STRING",
    "lines": "line_id STRING, start_position_id STRING, end_position_id STRING, moves_uci ARRAY<STRING>",
    "opening_lines": "record_id STRING, run_id STRING, opening_id STRING, line_id STRING, name STRING, candidate_id STRING, review_status STRING",
    "claims": "record_id STRING, run_id STRING, opening_id STRING, claim_id STRING, text STRING, category STRING, side STRING, position_id STRING, candidate_id STRING, review_status STRING",
    "claim_evidence": "evidence_id STRING, run_id STRING, candidate_id STRING, source_version_id STRING, excerpt STRING, relation STRING",
}

KEYS = {name: ddl.split()[0] for name, ddl in TABLES.items()}
