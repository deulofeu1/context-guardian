import json
from pathlib import Path

from context_guardian import ContextGuardian
from context_guardian.models import CandidateCategory, ReviewAction, ReviewDecision


def load_example():
    return json.loads((Path(__file__).parents[1] / "examples" / "conversation.json").read_text())["messages"]


def test_rules_inspector_finds_durable_and_transient_context():
    result = ContextGuardian().inspect(load_example())
    contents = {candidate.content for candidate in result.candidates}
    assert any("public API" in content for content in contents)
    assert any("PostgreSQL" in content for content in contents)
    assert any(
        candidate.category is CandidateCategory.DECISION and "selected database" in candidate.content
        for candidate in result.candidates
    )
    assert any(
        candidate.category is CandidateCategory.TODO and "auth.py" in candidate.content
        for candidate in result.candidates
    )
    assert any(candidate.category is CandidateCategory.TOOL_OUTPUT for candidate in result.candidates)
    assert any(candidate.category is CandidateCategory.FAILED_ATTEMPT for candidate in result.candidates)
    assert len(result.auto_keep) > 0
    assert len(result.auto_drop) > 0
    assert len(result.review) > 0


def test_candidate_ids_are_stable():
    first = ContextGuardian().inspect(load_example())
    second = ContextGuardian().inspect(load_example())
    assert [candidate.id for candidate in first.candidates] == [
        candidate.id for candidate in second.candidates
    ]


def test_example_guidance_keeps_project_memory_and_discards_noise():
    guardian = ContextGuardian()
    result = guardian.inspect(load_example())
    decisions = [ReviewDecision(candidate_id=candidate.id, action="keep") for candidate in result.review]
    guidance = guardian.build_guidance(result.candidates, decisions)

    assert "public API" in guidance.text
    assert "PostgreSQL" in guidance.text
    assert "SQLite caused concurrency issues" in guidance.text
    assert "auth.py is still incomplete" in guidance.text
    assert "grep -R OAuth ." in guidance.text
    assert "npm install completed successfully" in guidance.text
    assert "temporary syntax error" in guidance.text
    assert "Can discard:" in guidance.text


class FakeProvider:
    def generate_structured(self, prompt, schema):
        return schema.model_validate(
            {
                "candidates": [
                    {
                        "id": "memory_provider_1",
                        "content": "Use PostgreSQL instead of SQLite.",
                        "category": "decision",
                        "importance": 0.95,
                        "confidence": 0.95,
                        "suggested_action": "review",
                        "reason": "Explicit architecture decision.",
                    }
                ]
            }
        )


def test_provider_results_are_policy_normalized():
    result = ContextGuardian(provider=FakeProvider()).inspect(load_example())
    assert result.mode == "provider"
    assert result.candidates[0].suggested_action is ReviewAction.KEEP


class BrokenProvider:
    def generate_structured(self, prompt, schema):
        raise RuntimeError("provider unavailable")


def test_provider_failure_falls_back_to_rules():
    result = ContextGuardian(provider=BrokenProvider()).inspect_with_fallback(load_example())
    assert result.mode == "rules"
    assert result.candidates
