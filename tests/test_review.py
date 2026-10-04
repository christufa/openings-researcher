import json

import httpx
import pytest
from openai import OpenAI

from openings_research.review import OpenAIReviewer, ReviewDecision, ReviewOutput, validate_reviews


def candidate(candidate_id="a", kind="claim"):
    return {
        "candidate_id": candidate_id,
        "kind": kind,
        "payload_json": json.dumps(
            {
                "text": "The bishop sacrifice is speculative.",
                "category": "pawn_break",
                "side": "white",
                "position_fen": None,
                "evidence": [
                    {
                        "source_version_id": "s",
                        "excerpt": "A speculative bishop sacrifice.",
                        "relation": "supports",
                    }
                ],
            }
        ),
    }


def decision(candidate_id="a", category="assessment"):
    return ReviewDecision(
        candidate_id=candidate_id,
        decision="accept",
        category=category,
        rationale="This assesses a sacrifice; no pawn advance is described.",
    )


@pytest.mark.parametrize("reviews", [[], [decision("unknown")], [decision(), decision()]])
def test_review_must_cover_exact_candidate_set(reviews):
    with pytest.raises(ValueError, match="exactly once"):
        validate_reviews(ReviewOutput(reviews=reviews), [candidate()])


def test_accepted_claim_needs_category_and_line_must_not_have_one():
    with pytest.raises(ValueError, match="category"):
        validate_reviews(ReviewOutput(reviews=[decision(category=None)]), [candidate()])
    with pytest.raises(ValueError, match="category"):
        validate_reviews(ReviewOutput(reviews=[decision()]), [candidate(kind="line")])


def test_openai_review_preserves_wire_output_and_restores_candidate_ids():
    def handler(request):
        body = json.loads(request.content)
        context = json.loads(body["input"][1]["content"])
        assert context["candidates"][0]["candidate_id"] == "c0001"
        assert context["candidates"][0]["candidate"]["category"] == "pawn_break"
        assert "piece sacrifice is not a pawn break" in body["input"][0]["content"]
        output = ReviewOutput(reviews=[decision("c0001")]).model_dump_json()
        return httpx.Response(
            200,
            json={
                "id": "resp_review",
                "created_at": 0,
                "model": "gpt-4.1-mini",
                "object": "response",
                "status": "completed",
                "output": [
                    {
                        "id": "msg_review",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": output, "annotations": []}],
                    }
                ],
                "usage": {"input_tokens": 50, "output_tokens": 20, "total_tokens": 70},
            },
        )

    reviewer = OpenAIReviewer("test-key", "gpt-4.1-mini")
    reviewer.client.close()
    with OpenAI(
        api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    ) as client:
        reviewer.client = client
        result = reviewer.review("Italian Game", [candidate("original-id")], {"s": "fixture://s"})
    assert result.output.reviews[0].candidate_id == "original-id"
    assert result.output.reviews[0].category == "assessment"
    assert json.loads(result.raw_response)["candidate_aliases"] == {"c0001": "original-id"}
    validate_reviews(result.output, [candidate("original-id")])
