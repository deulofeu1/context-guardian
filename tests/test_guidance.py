from context_guardian import ContextGuardian
from context_guardian.guidance import build_guidance
from context_guardian.models import CandidateCategory, MemoryCandidate, ReviewAction


def make_candidate(identifier, content, action):
    return MemoryCandidate(
        id=identifier,
        content=content,
        category=CandidateCategory.IMPORTANT_FACT,
        importance=0.5,
        confidence=0.5,
        suggested_action=action,
    )


def test_guidance_has_three_sections_and_deduplicates():
    guidance = build_guidance(
        [
            make_candidate("1", "Keep this", ReviewAction.KEEP),
            make_candidate("2", "Keep this", ReviewAction.KEEP),
            make_candidate("3", "Drop this", ReviewAction.DROP),
            make_candidate("4", "Review this", ReviewAction.REVIEW),
        ]
    )
    assert guidance.must_preserve == ["Keep this"]
    assert guidance.can_discard == ["Drop this"]
    assert guidance.unresolved == ["Review this"]
    assert "Must preserve:" in guidance.text
    assert "Can discard:" in guidance.text
    assert "Unresolved / review carefully:" in guidance.text


def test_build_guidance_applies_explicit_decisions():
    guardian = ContextGuardian()
    candidate = make_candidate("1", "A candidate", ReviewAction.REVIEW)
    guidance = guardian.build_guidance([candidate], [{"candidate_id": "1", "action": "keep"}])
    assert guidance.must_preserve == ["A candidate"]
    assert guidance.unresolved == []
