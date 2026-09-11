"""Guidance generation; intentionally not a summarizer."""

from __future__ import annotations

from collections.abc import Iterable

from .models import CompactionGuidance, MemoryCandidate, ReviewAction


def build_guidance(candidates: Iterable[MemoryCandidate]) -> CompactionGuidance:
    must_preserve: list[str] = []
    can_discard: list[str] = []
    unresolved: list[str] = []
    seen: set[str] = set()

    for candidate in candidates:
        content = candidate.content.strip()
        key = content.casefold()
        if not content or key in seen:
            continue
        seen.add(key)
        if candidate.suggested_action is ReviewAction.KEEP:
            must_preserve.append(content)
        elif candidate.suggested_action is ReviewAction.DROP:
            can_discard.append(content)
        else:
            unresolved.append(content)

    guidance = CompactionGuidance(
        must_preserve=must_preserve,
        can_discard=can_discard,
        unresolved=unresolved,
    )
    return guidance.model_copy(update={"text": guidance.render()})
