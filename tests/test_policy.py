from context_guardian.models import CandidateCategory, MemoryCandidate, ReviewAction
from context_guardian.policy import ReviewPolicy


def candidate(category, importance, confidence):
    return MemoryCandidate(
        id="candidate",
        content="content",
        category=category,
        importance=importance,
        confidence=confidence,
        suggested_action=ReviewAction.REVIEW,
    )


def test_policy_keeps_high_signal_decisions_when_confidence_is_high():
    policy = ReviewPolicy()
    assert policy.decide(candidate(CandidateCategory.DECISION, 0.8, 0.8)) is ReviewAction.KEEP


def test_policy_drops_confident_noise():
    policy = ReviewPolicy()
    assert policy.decide(candidate(CandidateCategory.TOOL_OUTPUT, 0.1, 0.95)) is ReviewAction.DROP


def test_policy_reviews_ambiguous_candidate():
    policy = ReviewPolicy()
    assert policy.decide(candidate(CandidateCategory.IMPORTANT_FACT, 0.5, 0.5)) is ReviewAction.REVIEW
