import io
import json
from unittest.mock import patch

from context_guardian.bridge import run_protocol
from context_guardian.models import AuditTopic, ReviewOption, ReviewPlan, ReviewQuestion


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


def test_bridge_host_provider_reaches_review_with_mixed_language_evidence():
    provider_plan = ReviewPlan(
        language="zh-CN",
        findings=[{
            "id": "finding-side",
            "issue_type": "ambiguous",
            "category": "important_fact",
            "summary": "该适配器应保持可选。",
            "display_summary": "该适配器应保持可选。",
            "why_it_matters": "这会影响后续部署。",
            "suggested_correction": "untrusted provider correction",
            "importance": 0.6,
            "confidence": 0.6,
            "source_message_ids": ["source"],
            "evidence_snippets": ["The adapter should remain optional for future deployments."],
        }],
        audit_topics=[AuditTopic(
            id="provider-topic",
            title="Optional adapter",
            summary="该适配器应保持可选。",
            finding_ids=["finding-side"],
            impact=0.6,
            confidence=0.6,
            relevance_to_main_goal=0.4,
            requires_user_preference=True,
            disposition="ask_user",
            recommended_action="keep",
            suggested_correction="untrusted provider correction",
        )],
        review_questions=[ReviewQuestion(
            id="provider-question",
            topic_id="provider-topic",
            title="Optional adapter",
            question="Should this be kept?",
            context="The provider requested a decision.",
            why_it_matters="It may affect future deployments.",
            recommendation="keep",
            options=[
                ReviewOption(id="keep", label="Keep", description="Keep the conclusion."),
                ReviewOption(id="drop", label="Drop", description="Accept the preview."),
            ],
        )],
    )
    request = {
        "protocol_version": 1,
        "type": "request",
        "request_id": "request-host-audit",
        "operation": "audit_preview",
        "provider": "host",
        "language": "zh-CN",
        "preview": "The native preview omitted the optional adapter decision.",
        "messages": [{
            "id": "source",
            "role": "user",
            "content": "The adapter should remain optional for future deployments.",
        }],
        "max_review_questions": 3,
    }
    provider_response = {
        "protocol_version": 1,
        "type": "provider_response",
        "request_id": "provider-request",
        "ok": True,
        "data": provider_plan.model_dump(mode="json"),
    }
    input_stream = io.StringIO(
        json.dumps(request) + "\n" + json.dumps(provider_response) + "\n"
    )
    output_stream = io.StringIO()

    with patch("context_guardian.providers.uuid.uuid4", return_value="provider-request"):
        assert run_protocol(input_stream, output_stream) == 0

    response = json.loads(output_stream.getvalue().splitlines()[-1])
    assert response["ok"] is True
    result = response["result"]
    assert len(result["review_questions"]) == 1
    assert "该适配器应保持可选" in result["review_questions"][0]["context"]
    assert result["review_questions"][0]["evidence_snippets"] == [
        "The adapter should remain optional for future deployments."
    ]


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
            "findings": [{
                "id": "finding-db",
                "issue_type": "missing",
                "category": "decision",
                "summary": "PostgreSQL is the selected database.",
                "why_it_matters": "The database decision matters.",
                "suggested_correction": "PostgreSQL is the selected database.",
                "importance": 0.9,
                "confidence": 0.95,
                "source_message_ids": ["db"],
                "evidence_snippets": ["PostgreSQL is the selected database."],
            }],
        },
        "answers": [],
        "messages": [{
            "id": "db",
            "role": "user",
            "content": "PostgreSQL is the selected database.",
        }],
    }
    output_stream = io.StringIO()
    run_protocol(io.StringIO(json.dumps(request) + "\n"), output_stream)
    response = json.loads(output_stream.getvalue())
    assert response["ok"] is True
    assert response["result"]["version"] == "1"
    assert response["result"]["facts"][0]["origin"] == "auto_correction"
    assert "PostgreSQL" in response["result"]["text"]
