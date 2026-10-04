import json

import chess
import httpx
import pytest
from openai import OpenAI
from pydantic import ValidationError

from openings_research.agents import OpenAIAgent
from openings_research.contracts import ResearchInput, Source
from openings_research.evidence import (
    EVIDENCE_INDEX_VERSION,
    MAX_PASSAGE_CHARS,
    index_passages,
    reference_schema,
    resolve_references,
)
from openings_research.validation import validate_candidate


def source(content, source_id="s"):
    return Source(source_version_id=source_id, url="fixture://evidence", title="Test source", content=content)


def referenced_claim(passage_id):
    return {
        "text": "White develops the bishop to c4.",
        "category": "plan",
        "side": "white",
        "position_fen": None,
        "evidence": [{"passage_id": passage_id, "relation": "supports"}],
    }


def test_passages_preserve_original_markdown_unicode_and_line_breaks():
    # Regression: the old agent flattened these into a new, non-verbatim quotation.
    text = "White’s plan:\r\n\r\n* **Develop** the bishop.\r\n* Play d3.\n\n" * 70
    document = source(text)
    passages = index_passages([document])
    assert len(passages) > 1
    assert "".join(p.text for p in passages) == text
    assert all(0 < len(p.text) <= MAX_PASSAGE_CHARS for p in passages)
    assert all(p.text == text[p.start : p.end] for p in passages)


def test_passage_ids_are_independent_of_source_collection_order():
    first, second = source("Plan A", "a"), source("Plan B", "b")
    assert index_passages([first, second]) == index_passages([second, first, first])


def test_conflicting_versions_and_empty_content_fail_before_provider_call():
    with pytest.raises(ValueError, match="Conflicting"):
        index_passages([source("a"), source("b")])
    with pytest.raises(ValueError, match="nonempty"):
        index_passages([source(" \n\t")])


def test_long_unbroken_content_is_bounded_without_dropping_text():
    text = "x" * (MAX_PASSAGE_CHARS * 2 + 1)
    passages = index_passages([source(text)])
    assert "".join(p.text for p in passages) == text
    assert len(passages) == 3


def test_resolution_copies_original_text_and_source_identity():
    documents = [
        source("White develops the bishop to c4.\n\n* Prepare d3.", "a"),
        source("Another source’s **different** plan.", "b"),
    ]
    passages = index_passages(documents)
    schema = reference_schema(passages)
    candidate = referenced_claim(passages[0].passage_id)
    output = schema.model_validate({"lines": [], "claims": [candidate], "unresolved_questions": []})
    resolved = resolve_references(output, passages)
    evidence = resolved.claims[0].evidence[0]
    assert evidence.source_version_id == "a"
    assert evidence.excerpt == documents[0].content
    assert validate_candidate(resolved.claims[0], documents)["review_status"] == "unreviewed"


def test_schema_rejects_unknown_passages_and_generated_quotes():
    passages = index_passages([source("Real evidence")])
    schema = reference_schema(passages)
    candidate = referenced_claim("p9999")
    with pytest.raises(ValidationError):
        schema.model_validate({"lines": [], "claims": [candidate], "unresolved_questions": []})
    candidate = referenced_claim(passages[0].passage_id)
    candidate["evidence"][0]["excerpt"] = "Invented quotation"
    with pytest.raises(ValidationError):
        schema.model_validate({"lines": [], "claims": [candidate], "unresolved_questions": []})


def test_resolver_revalidates_even_if_model_was_mutated():
    passages = index_passages([source("Real evidence")])
    schema = reference_schema(passages)
    output = schema.model_validate(
        {"lines": [], "claims": [referenced_claim("p0001")], "unresolved_questions": []}
    )
    output.claims[0].evidence[0].passage_id = "p9999"
    with pytest.raises(ValidationError):
        resolve_references(output, passages)


def test_resolved_evidence_does_not_bypass_chess_or_support_checks():
    document = source("White develops the bishop.")
    passages = index_passages([document])
    schema = reference_schema(passages)
    output = schema.model_validate(
        {
            "lines": [
                {
                    "name": "Illegal",
                    "start_fen": chess.STARTING_FEN,
                    "moves_san": ["e5"],
                    "evidence": [{"passage_id": "p0001", "relation": "supports"}],
                }
            ],
            "claims": [],
            "unresolved_questions": [],
        }
    )
    with pytest.raises(ValueError):
        validate_candidate(resolve_references(output, passages).lines[0], [document])
    claim = referenced_claim("p0001")
    claim["evidence"][0]["relation"] = "disputes"
    output = schema.model_validate({"lines": [], "claims": [claim], "unresolved_questions": []})
    with pytest.raises(ValueError, match="supporting"):
        validate_candidate(resolve_references(output, passages).claims[0], [document])


def test_openai_adapter_uses_constrained_references_and_saves_wire_response():
    document = source("White develops the bishop to c4.\n\n* Keep developing.")
    wire = {}

    def handler(request):
        body = json.loads(request.content)
        context = json.loads(body["input"][1]["content"])
        assert context["sources"][0]["passages"][0]["text"] == document.content
        schema = body["text"]["format"]["schema"]
        reference = schema["$defs"]["PassageReference"]["properties"]["passage_id"]
        assert reference.get("const") == "p0001" or reference.get("enum") == ["p0001"]
        assert "excerpt" not in schema["$defs"]["PassageReference"]["properties"]
        output = {"lines": [], "claims": [referenced_claim("p0001")], "unresolved_questions": []}
        wire.update(
            {
                "id": "resp_test",
                "created_at": 0,
                "model": "gpt-4.1-mini",
                "object": "response",
                "status": "completed",
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": json.dumps(output), "annotations": []}],
                    }
                ],
                "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            }
        )
        return httpx.Response(200, json=wire)

    agent = OpenAIAgent("test-key", "gpt-4.1-mini")
    agent.client.close()
    with OpenAI(
        api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    ) as client:
        agent.client = client
        result = agent.extract(ResearchInput(opening="Italian Game", sources=[document]))
    raw = json.loads(result.raw_response)
    assert raw["provider_response"] == wire
    assert raw["evidence_index_version"] == EVIDENCE_INDEX_VERSION
    assert raw["passages"][0]["source_version_id"] == document.source_version_id
    assert result.output.claims[0].evidence[0].excerpt == document.content
    assert json.loads(result.usage_json)["total_tokens"] == 120
