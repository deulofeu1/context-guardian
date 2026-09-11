"""Deterministic review policy for memory candidates."""

from __future__ import annotations

from dataclasses import dataclass

from .models import CandidateCategory, MemoryCandidate, ReviewAction


@dataclass(frozen=True)
class ReviewPolicy:
    """Small, explainable policy; intentionally not a learned model."""

    keep_importance: float = 0.8
    keep_confidence: float = 0.8
    drop_importance: float = 0.25
    drop_confidence: float = 0.8
    version: str = "1"

    preserve_categories: frozenset[CandidateCategory] = frozenset(
        {
            CandidateCategory.GOAL,
            CandidateCategory.REQUIREMENT,
            CandidateCategory.CONSTRAINT,
            CandidateCategory.DECISION,
            CandidateCategory.TODO,
            CandidateCategory.WORKING_STATE,
            CandidateCategory.FAILED_ATTEMPT,
            CandidateCategory.USER_PREFERENCE,
            CandidateCategory.IMPORTANT_FACT,
            CandidateCategory.FILE_STATE,
        }
    )
    discard_categories: frozenset[CandidateCategory] = frozenset(
        {CandidateCategory.TOOL_OUTPUT, CandidateCategory.TEMPORARY}
    )

    def decide(self, candidate: MemoryCandidate) -> ReviewAction:
        if (
            candidate.category in self.preserve_categories
            and candidate.importance >= self.keep_importance
            and candidate.confidence >= self.keep_confidence
        ):
            return ReviewAction.KEEP
        if candidate.category in self.discard_categories and candidate.confidence >= self.drop_confidence:
            return ReviewAction.DROP
        if candidate.importance >= self.keep_importance and candidate.confidence >= self.keep_confidence:
            return ReviewAction.KEEP
        if candidate.importance <= self.drop_importance and candidate.confidence >= self.drop_confidence:
            return ReviewAction.DROP
        return ReviewAction.REVIEW

    def apply(self, candidate: MemoryCandidate) -> MemoryCandidate:
        return candidate.model_copy(update={"suggested_action": self.decide(candidate)})
