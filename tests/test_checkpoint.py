from context_guardian import ContextCheckpoint, ContextGuardian, build_checkpoint
from context_guardian.models import CandidateCategory, MemoryCandidate, ReviewAction


def candidate(identifier, content, category, action=ReviewAction.KEEP):
    return MemoryCandidate(
        id=identifier,
        content=content,
        category=category,
        importance=0.9,
        confidence=0.9,
        suggested_action=action,
    )


def test_checkpoint_groups_reviewed_candidates_and_deduplicates():
    checkpoint = build_checkpoint(
        [
            candidate("goal", "Implement OAuth.", CandidateCategory.GOAL),
            candidate("constraint", "Keep the public API compatible.", CandidateCategory.CONSTRAINT),
            candidate("decision", "PostgreSQL is final.", CandidateCategory.DECISION),
            candidate("failure", "SQLite failed under concurrency.", CandidateCategory.FAILED_ATTEMPT),
            candidate("state", "auth.py is unfinished.", CandidateCategory.TODO),
            candidate("drop", "Temporary grep output.", CandidateCategory.TOOL_OUTPUT, ReviewAction.DROP),
            candidate("duplicate", "PostgreSQL is final.", CandidateCategory.DECISION),
        ]
    )

    assert isinstance(checkpoint, ContextCheckpoint)
    assert checkpoint.goals == ["Implement OAuth."]
    assert checkpoint.decisions == ["PostgreSQL is final."]
    assert checkpoint.todos == ["auth.py is unfinished."]
    assert "Temporary grep output." not in checkpoint.text
    assert checkpoint.text.count("PostgreSQL is final.") == 1


def test_checkpoint_keeps_unresolved_by_default_and_can_drop_it():
    unresolved = candidate(
        "review", "Keep this uncertain state.", CandidateCategory.WORKING_STATE, ReviewAction.REVIEW
    )

    assert "Keep this uncertain state." in build_checkpoint([unresolved]).text
    assert "Keep this uncertain state." not in build_checkpoint(
        [unresolved], unresolved_action=ReviewAction.DROP
    ).text


def test_guardian_checkpoint_applies_explicit_review_decisions():
    guardian = ContextGuardian()
    item = candidate("review", "SQLite was abandoned.", CandidateCategory.FAILED_ATTEMPT, ReviewAction.REVIEW)

    checkpoint = guardian.build_checkpoint([item], [{"candidate_id": "review", "action": "drop"}])

    assert checkpoint.failed_attempts == []
