"""Portable, reviewed context checkpoints for assisted integrations."""

from __future__ import annotations

from collections.abc import Iterable

from .models import CandidateCategory, ContextCheckpoint, MemoryCandidate, ReviewAction

CHECKPOINT_SECTIONS: tuple[tuple[str, frozenset[CandidateCategory]], ...] = (
    ("Goal", frozenset({CandidateCategory.GOAL})),
    (
        "Constraints",
        frozenset({CandidateCategory.REQUIREMENT, CandidateCategory.CONSTRAINT}),
    ),
    ("Decisions", frozenset({CandidateCategory.DECISION})),
    ("Failed Attempts", frozenset({CandidateCategory.FAILED_ATTEMPT})),
    (
        "Current State",
        frozenset(
            {
                CandidateCategory.WORKING_STATE,
                CandidateCategory.FILE_STATE,
                CandidateCategory.IMPORTANT_FACT,
                CandidateCategory.USER_PREFERENCE,
            }
        ),
    ),
    ("TODO", frozenset({CandidateCategory.TODO})),
)


def _unique(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = item.strip()
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def build_checkpoint(
    candidates: Iterable[MemoryCandidate],
    *,
    unresolved_action: ReviewAction = ReviewAction.KEEP,
) -> ContextCheckpoint:
    """Render reviewed candidates as a portable Markdown checkpoint.

    Adapters share candidate resolution while choosing either native guidance or a
    durable checkpoint file. ``unresolved_action`` defaults to Keep because an assisted
    integration must not silently discard a candidate that the user did not reject.
    """

    grouped: dict[str, list[str]] = {name: [] for name, _ in CHECKPOINT_SECTIONS}
    category_to_section = {
        category: name for name, categories in CHECKPOINT_SECTIONS for category in categories
    }

    for candidate in candidates:
        action = candidate.suggested_action
        if action is ReviewAction.REVIEW:
            action = unresolved_action
        if action is not ReviewAction.KEEP:
            continue
        section = category_to_section.get(candidate.category)
        if section is not None:
            grouped[section].append(candidate.content)

    normalized = {name: _unique(items) for name, items in grouped.items()}
    checkpoint = ContextCheckpoint(
        goals=normalized["Goal"],
        constraints=normalized["Constraints"],
        decisions=normalized["Decisions"],
        failed_attempts=normalized["Failed Attempts"],
        current_state=normalized["Current State"],
        todos=normalized["TODO"],
    )
    return checkpoint.model_copy(update={"text": checkpoint.render()})
