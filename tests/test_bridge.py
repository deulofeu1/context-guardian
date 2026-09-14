import io
import json

from context_guardian.bridge import run_protocol


def test_bridge_handles_rules_inspection():
    request = {
        "protocol_version": 1,
        "type": "request",
        "request_id": "request-1",
        "operation": "inspect",
        "provider": "rules",
        "messages": [{"role": "user", "content": "The goal is to keep the public API unchanged."}],
    }
    input_stream = io.StringIO(json.dumps(request) + "\n")
    output_stream = io.StringIO()
    assert run_protocol(input_stream, output_stream) == 0
    response = json.loads(output_stream.getvalue())
    assert response["ok"] is True
    assert response["request_id"] == "request-1"
    assert response["result"]["candidates"]


def test_bridge_rejects_unknown_operation():
    request = {"protocol_version": 1, "request_id": "request-2", "operation": "unknown"}
    input_stream = io.StringIO(json.dumps(request) + "\n")
    output_stream = io.StringIO()
    run_protocol(input_stream, output_stream)
    response = json.loads(output_stream.getvalue())
    assert response["ok"] is False
    assert response["error"] == "unsupported operation"


def test_bridge_guidance_validates_json_candidates():
    request = {
        "protocol_version": 1,
        "type": "request",
        "request_id": "request-3",
        "operation": "guidance",
        "provider": "rules",
        "candidates": [{
            "id": "memory-1",
            "content": "PostgreSQL is the final database choice.",
            "category": "decision",
            "importance": 0.91,
            "confidence": 0.9,
            "suggested_action": "review",
            "source_message_ids": ["m1"],
        }],
        "decisions": [{"candidate_id": "memory-1", "action": "keep"}],
    }
    input_stream = io.StringIO(json.dumps(request) + "\n")
    output_stream = io.StringIO()
    run_protocol(input_stream, output_stream)
    response = json.loads(output_stream.getvalue())
    assert response["ok"] is True
    assert "PostgreSQL" in response["result"]["text"]


def test_bridge_audits_native_preview_with_bounded_questions():
    request = {
        "protocol_version": 1,
        "type": "request",
        "request_id": "request-audit",
        "operation": "audit_preview",
        "provider": "rules",
        "preview": "PostgreSQL is selected.",
        "messages": [
            {
                "id": "u1",
                "role": "user",
                "content": "The goal is to implement OAuth without changing the public API.",
            },
            {
                "id": "u2",
                "role": "user",
                "content": "auth.py is still incomplete.",
            },
        ],
        "max_review_questions": 3,
    }
    input_stream = io.StringIO(json.dumps(request) + "\n")
    output_stream = io.StringIO()
    run_protocol(input_stream, output_stream)
    response = json.loads(output_stream.getvalue())
    assert response["ok"] is True
    assert len(response["result"]["review_questions"]) <= 3
    assert "auth.py" in " ".join(response["result"]["auto_corrections"])


def test_bridge_revision_guidance_accepts_topic_answer():
    request = {
        "protocol_version": 1,
        "type": "request",
        "request_id": "request-revision",
        "operation": "revision_guidance",
        "review_plan": {
            "language": "en",
            "audit_topics": [
                {
                    "id": "topic-1",
                    "title": "Side topic",
                    "summary": "Keep the key conclusion.",
                    "finding_ids": [],
                    "impact": 0.6,
                    "confidence": 0.5,
                    "relevance_to_main_goal": 0.4,
                    "requires_user_preference": True,
                    "disposition": "ask_user",
                    "recommended_action": "drop",
                    "suggested_correction": "Keep the key conclusion.",
                }
            ],
            "review_questions": [
                {
                    "id": "question-1",
                    "topic_id": "topic-1",
                    "title": "Side topic",
                    "question": "Keep it?",
                    "context": "A key conclusion.",
                    "why_it_matters": "It may matter later.",
                    "recommendation": "drop",
                    "options": [
                        {"id": "keep", "label": "Keep", "description": "Keep it."},
                        {"id": "drop", "label": "Drop", "description": "Drop it."},
                    ],
                }
            ],
        },
        "answers": [{"question_id": "question-1", "action": "keep"}],
    }
    output_stream = io.StringIO()
    run_protocol(io.StringIO(json.dumps(request) + "\n"), output_stream)
    response = json.loads(output_stream.getvalue())
    assert response["ok"] is True
    assert "Keep the key conclusion." in response["result"]["text"]


def test_bridge_build_reviewed_facts_is_deterministic_and_does_not_call_revision():
    request = {
        "protocol_version": 1,
        "type": "request",
        "request_id": "request-facts",
        "operation": "build_reviewed_facts",
        "review_plan": {
            "language": "en",
            "auto_corrections": ["PostgreSQL is the selected database."],
        },
        "answers": [],
    }
    output_stream = io.StringIO()
    run_protocol(io.StringIO(json.dumps(request) + "\n"), output_stream)
    response = json.loads(output_stream.getvalue())
    assert response["ok"] is True
    assert response["result"]["version"] == "1"
    assert response["result"]["facts"][0]["origin"] == "auto_correction"
    assert "PostgreSQL" in response["result"]["text"]
