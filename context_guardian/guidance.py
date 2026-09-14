"""Guidance generation; intentionally not a summarizer."""

from __future__ import annotations

from collections.abc import Iterable

from .models import AuditDisposition, CompactionGuidance, MemoryCandidate, ReviewAction, ReviewPlan


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


def build_revision_guidance(
    review_plan: ReviewPlan,
    answers: Iterable[dict] = (),
) -> CompactionGuidance:
    """Deprecated 0.2.x helper for callers that still perform a second compaction.

    ``answers`` accepts ``question_id`` or ``topic_id`` plus ``action``. Unknown
    ids are ignored by design. Maintained 0.3.x adapters use ``build_reviewed_facts``
    and an append-only finalization instead.
    """

    answer_map: dict[str, str] = {}
    for raw in answers:
        if not isinstance(raw, dict):
            continue
        action = str(raw.get("action", raw.get("answer", ""))).lower()
        key = raw.get("question_id") or raw.get("topic_id") or raw.get("id")
        if key and action in {"keep", "drop"}:
            answer_map[str(key)] = action

    topic_by_id = {topic.id: topic for topic in review_plan.audit_topics}
    must_preserve = list(review_plan.auto_corrections)
    unresolved: list[str] = []
    # Accepted omissions are audit facts, not revision instructions. The native
    # preview already omitted them, so repeating them would waste prompt budget.
    can_discard: list[str] = []
    seen: set[str] = {item.casefold() for item in must_preserve}

    for question in review_plan.review_questions:
        action = answer_map.get(question.id, answer_map.get(question.topic_id, question.recommendation))
        if action != "keep":
            continue
        topic = topic_by_id.get(question.topic_id)
        correction = topic.suggested_correction if topic else None
        if not correction and topic:
            correction = topic.summary
        if correction and correction.casefold() not in seen:
            must_preserve.append(correction)
            seen.add(correction.casefold())

    # A plan can contain an auto-correct topic without duplicating its text in
    # auto_corrections (for example, provider-produced plans).
    for topic in review_plan.audit_topics:
        if topic.disposition is not AuditDisposition.AUTO_CORRECT:
            continue
        correction = topic.suggested_correction
        if correction and correction.casefold() not in seen:
            must_preserve.append(correction)
            seen.add(correction.casefold())

    if not must_preserve and not can_discard and not unresolved:
        return CompactionGuidance(text="")

    guidance = CompactionGuidance(
        must_preserve=_unique(must_preserve),
        can_discard=_unique(can_discard),
        unresolved=_unique(unresolved),
    )
    lines = [
        "Context Guardian incremental revision guidance. Revise the native preview; do not "
        "write a replacement summary.",
    ]
    if guidance.must_preserve:
        lines.extend(["", "Must additionally preserve or correct:"])
        lines.extend(f"- {item}" for item in guidance.must_preserve)
    if guidance.unresolved:
        lines.extend(["", "Unresolved:"])
        lines.extend(f"- {item}" for item in guidance.unresolved)
    return guidance.model_copy(update={"text": "\n".join(lines)})


def _unique(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = item.strip()
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            result.append(value)
    return result
