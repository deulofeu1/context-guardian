"""Deterministic Reviewed Facts generation and safe preview finalization.

This module intentionally contains no provider or model calls.  A host native
compactor owns the preview; Context Guardian only adds source-backed facts that
were automatically corrected, explicitly kept by a human, or carried forward
from a previous legal appendix.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable

from .audit import _complete_conclusion, is_execution_noise, validate_review_plan
from .models import (
    AuditDisposition,
    AuditOperation,
    CandidateCategory,
    ConversationMessage,
    PreviewEdit,
    PreviewFinalization,
    ReviewedFact,
    ReviewedFactsAppendix,
    ReviewPlan,
)

START_MARKER = "<!-- context-guardian:reviewed-facts:v1 -->"
END_MARKER = "<!-- /context-guardian:reviewed-facts -->"
_BLOCK_RE = re.compile(
    re.escape(START_MARKER) + r"(?P<body>.*?)" + re.escape(END_MARKER),
    re.DOTALL,
)
_MAX_FACT_CHARS = 500
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_KNOWN_SUBJECTS = (
    "postgresql",
    "sqlite",
    "mysql",
    "redis",
    "mongodb",
    "oauth",
    "auth.py",
    "callback",
    "public api",
    "api compatibility",
)
_POSITIVE_STANCE = re.compile(
    r"\b(?:selected|chosen|final|adopt(?:ed)?|use|using|complete|completed|采用|确定|完成)\b",
    re.I,
)
_NEGATIVE_STANCE = re.compile(
    r"\b(?:abandoned|rejected|stop using|not use|incomplete|unfinished|failed|放弃|弃用|未完成|失败)\b",
    re.I,
)


def _normalize_text(value: object, *, max_length: int = _MAX_FACT_CHARS) -> str:
    text = unicodedata.normalize("NFC", str(value or ""))
    text = _CONTROL_CHARS.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" -\t")
    text = text.replace(START_MARKER, "[reviewed-facts marker removed]")
    text = text.replace(END_MARKER, "[reviewed-facts end marker removed]")
    text = text.replace("<!--", "&lt;!--").replace("-->", "--&gt;")
    if len(text) > max_length:
        text = _complete_conclusion(text, limit=max_length)
    return text if text and len(text) <= max_length else ""


def _fact_id(text: str) -> str:
    digest = hashlib.sha256(text.casefold().encode("utf-8")).hexdigest()[:16]
    return f"reviewed_fact_{digest}"


def _subject(text: str) -> str | None:
    lowered = text.casefold()
    for candidate in _KNOWN_SUBJECTS:
        if candidate in lowered:
            return candidate
    return None


def _conflict(left: str, right: str) -> bool:
    left_subject = _subject(left)
    right_subject = _subject(right)
    if left_subject is None or left_subject != right_subject:
        return False
    left_positive = bool(_POSITIVE_STANCE.search(left))
    right_positive = bool(_POSITIVE_STANCE.search(right))
    left_negative = bool(_NEGATIVE_STANCE.search(left))
    right_negative = bool(_NEGATIVE_STANCE.search(right))
    return (left_positive and right_negative) or (left_negative and right_positive)


def _correction_score(plan: ReviewPlan, text: str, index: int) -> tuple[float, float, int]:
    matches = [
        finding
        for finding in plan.findings
        if finding.suggested_correction.casefold() == text.casefold()
    ]
    if not matches:
        return (0.0, 0.0, index)
    finding = max(matches, key=lambda item: (item.confidence, item.importance, item.id))
    return (finding.confidence, finding.importance, index)


def _non_conflicting_corrections(plan: ReviewPlan) -> list[str]:
    corrections = list(plan.auto_corrections)
    winners: set[int] = set(range(len(corrections)))
    for left_index, left in enumerate(corrections):
        for right_index in range(left_index + 1, len(corrections)):
            right = corrections[right_index]
            if not _conflict(str(left), str(right)):
                continue
            left_score = _correction_score(plan, str(left), left_index)
            right_score = _correction_score(plan, str(right), right_index)
            if left_score <= right_score:
                winners.discard(left_index)
            else:
                winners.discard(right_index)
    return [str(correction) for index, correction in enumerate(corrections) if index in winners]


def _append_fact(
    facts: list[ReviewedFact],
    seen: set[str],
    value: object,
    *,
    origin: str,
    topic_id: str | None = None,
    category: CandidateCategory | None = None,
) -> None:
    text = _normalize_text(value)
    if not text or text.casefold() in seen:
        return
    # These are defensive guards for provider-produced plans.  Normal review
    # plans already remove this material before it reaches the appendix.
    if is_execution_noise(text):
        return
    seen.add(text.casefold())
    facts.append(
        ReviewedFact(
            id=_fact_id(text),
            text=text,
            origin=origin,
            topic_id=topic_id,
            category=category,
        )
    )


def _answer_map(answers: Iterable[dict]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in answers:
        if not isinstance(raw, dict):
            continue
        action = str(raw.get("action", raw.get("answer", ""))).casefold()
        key = raw.get("question_id") or raw.get("topic_id") or raw.get("id")
        if key and action in {"keep", "drop", "correct", "keep_preview", "add"}:
            result[str(key)] = action
    return result


def _finding_categories(plan: ReviewPlan) -> dict[str, CandidateCategory]:
    return {finding.id: finding.category for finding in plan.findings}


def _topic_category(plan: ReviewPlan, finding_ids: Iterable[str]) -> CandidateCategory | None:
    categories = _finding_categories(plan)
    for finding_id in finding_ids:
        category = categories.get(finding_id)
        if category is not None:
            return category
    return None


def _render_appendix(language: str, facts: list[ReviewedFact]) -> str:
    if not facts:
        return ""
    if language == "zh-CN":
        title = "## Context Guardian 已确认事实"
        intro = "以下是经过自动校正或人工确认、供后续任务优先参考的关键事实；不代表保留完整原始对话。"
    else:
        title = "## Context Guardian Reviewed Facts"
        intro = (
            "The following reviewed facts should take priority for future work; "
            "this does not preserve the full original conversation."
        )
    lines = [START_MARKER, title, intro]
    lines.extend(f"- {fact.text}" for fact in facts)
    lines.append(END_MARKER)
    return "\n".join(lines)


def build_reviewed_facts(
    review_plan: ReviewPlan,
    answers: Iterable[dict] = (),
    messages: Iterable[ConversationMessage | dict] | None = None,
    *,
    preview: str = "",
    validated: bool = False,
) -> ReviewedFactsAppendix:
    """Build a stable appendix only from a revalidated source-backed plan."""

    plan = (
        ReviewPlan.model_validate(review_plan)
        if validated
        else validate_review_plan(review_plan, messages, preview=preview)
    )
    facts: list[ReviewedFact] = []
    seen: set[str] = set()

    topic_by_finding = {
        finding_id: topic
        for topic in plan.audit_topics
        for finding_id in topic.finding_ids
    }
    appendable_corrections = [
        correction
        for correction in _non_conflicting_corrections(plan)
        if not any(
            topic_by_finding.get(finding.id) is not None
            and topic_by_finding[finding.id].operation == "replace"
            and finding.suggested_correction.casefold() == str(correction).casefold()
            for finding in plan.findings
        )
    ]
    for correction in appendable_corrections:
        category = next(
            (
                finding.category
                for finding in plan.findings
                if finding.suggested_correction.casefold() == str(correction).casefold()
            ),
            None,
        )
        _append_fact(facts, seen, correction, origin="auto_correction", category=category)

    topic_by_id = {topic.id: topic for topic in plan.audit_topics}
    answer_map = _answer_map(answers)
    for question in plan.review_questions:
        action = answer_map.get(question.id) or answer_map.get(question.topic_id)
        if action not in {"keep", "add", "correct"}:
            continue
        topic = topic_by_id.get(question.topic_id)
        if topic is None:
            continue
        if topic.operation == "replace":
            # Replacements are applied to the native text by finalize_preview;
            # appending the replacement would leave both contradictory states.
            continue
        correction = topic.proposed_text or topic.suggested_correction or topic.summary
        _append_fact(
            facts,
            seen,
            correction,
            origin="human_keep",
            topic_id=topic.id,
            category=_topic_category(plan, topic.finding_ids),
        )

    human_texts = [fact.text for fact in facts if fact.origin == "human_keep"]
    facts = [
        fact
        for fact in facts
        if fact.origin != "auto_correction"
        or not any(_conflict(fact.text, human_text) for human_text in human_texts)
    ]

    return ReviewedFactsAppendix(
        language=plan.language,
        facts=facts,
        text=_render_appendix(plan.language, facts),
    )


def _parse_existing_facts(block_body: str) -> list[ReviewedFact]:
    facts: list[ReviewedFact] = []
    seen: set[str] = set()
    for line in block_body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        _append_fact(facts, seen, stripped[2:], origin="carried_forward")
    return facts


def _origin_priority(origin: str) -> int:
    return {"carried_forward": 1, "auto_correction": 2, "human_keep": 3}.get(origin, 0)


def _merge_facts(base: Iterable[ReviewedFact], incoming: Iterable[ReviewedFact]) -> list[ReviewedFact]:
    """Merge facts while letting newer, more authoritative facts replace conflicts."""

    merged: list[ReviewedFact] = []
    for candidate in [*base, *incoming]:
        if any(existing.text.casefold() == candidate.text.casefold() for existing in merged):
            continue
        conflicts = [
            index for index, existing in enumerate(merged) if _conflict(existing.text, candidate.text)
        ]
        if not conflicts:
            merged.append(candidate)
            continue
        if all(
            _origin_priority(candidate.origin) >= _origin_priority(merged[index].origin)
            for index in conflicts
        ):
            merged = [existing for index, existing in enumerate(merged) if index not in conflicts]
            merged.append(candidate)
    return merged


def _with_carried_forward(preview: str, appendix: ReviewedFactsAppendix) -> ReviewedFactsAppendix:
    blocks = list(_BLOCK_RE.finditer(preview))
    if not blocks:
        return appendix
    carried: list[ReviewedFact] = []
    for block in blocks:
        carried = _merge_facts(carried, _parse_existing_facts(block.group("body")))
    facts = _merge_facts(carried, appendix.facts)
    return appendix.model_copy(update={"facts": facts, "text": _render_appendix(appendix.language, facts)})


def _effective_topic_payload(plan: ReviewPlan, topic) -> tuple[str, str, str]:
    """Capture the exact operation text the host showed to a user."""

    findings = {finding.id: finding for finding in plan.findings}
    question = next(
        (item for item in plan.review_questions if item.topic_id == topic.id),
        None,
    )
    target = (
        (question.current_summary_target if question is not None else None)
        or topic.current_summary_target
        or next(
            (
                finding.current_summary_target or finding.current_summary_text
                for finding_id in topic.finding_ids
                if (finding := findings.get(finding_id)) is not None
                and (finding.current_summary_target or finding.current_summary_text)
            ),
            "",
        )
    )
    replacement = (
        (question.proposed_text if question is not None else None)
        or topic.proposed_text
        or topic.suggested_correction
        or next(
            (
                finding.proposed_text or finding.suggested_correction
                for finding_id in topic.finding_ids
                if (finding := findings.get(finding_id)) is not None
            ),
            "",
        )
    )
    return (str(topic.operation), str(target or ""), str(replacement or ""))


def append_reviewed_facts(
    preview: str,
    appendix: ReviewedFactsAppendix,
) -> str:
    """Append or merge one legal appendix without rewriting native preview text."""

    original = str(preview)
    appendix = ReviewedFactsAppendix.model_validate(appendix)
    legal_blocks = list(_BLOCK_RE.finditer(original))
    if legal_blocks:
        carried: list[ReviewedFact] = []
        for block in legal_blocks:
            carried = _merge_facts(carried, _parse_existing_facts(block.group("body")))
        merged = _merge_facts(carried, appendix.facts)
        if [fact.text for fact in merged] == [fact.text for fact in carried]:
            return original
        rendered = _render_appendix(appendix.language, merged)
        # Replace legal blocks only; all surrounding native preview text stays
        # byte-for-byte unchanged.  Multiple old legal blocks collapse into one.
        first = legal_blocks[0]
        prefix = original[: first.start()]
        suffix = original[legal_blocks[-1].end() :]
        return prefix + rendered + suffix

    if not appendix.facts:
        return original
    separator = "" if not original else "\n\n"
    return original + separator + _render_appendix(appendix.language, appendix.facts)


def finalize_preview(
    *,
    preview: str,
    review_plan: ReviewPlan,
    answers: Iterable[dict] = (),
    messages: Iterable[ConversationMessage | dict] | None = None,
) -> PreviewFinalization:
    """Apply only exact, source-backed corrections, then append reviewed facts.

    The native preview is the authority for everything not explicitly corrected.
    A correction is never a fuzzy replacement: the target must be present exactly
    once and the audit must belong to this exact preview.
    """

    from .audit import preview_fingerprint

    original = str(preview)
    diagnostics: list[str] = []
    incoming_plan = ReviewPlan.model_validate(review_plan)
    source_messages = list(messages or [])
    if not source_messages and (
        incoming_plan.findings
        or incoming_plan.audit_topics
        or incoming_plan.review_questions
    ):
        diagnostics.append("source_validation_unavailable")
        return PreviewFinalization(
            original_preview=original,
            final_summary=original,
            appendix=ReviewedFactsAppendix(language=incoming_plan.language),
            changed=False,
            diagnostics=diagnostics,
        )
    incoming_answers = _answer_map(answers)
    incoming_topic_actions: dict[str, str] = {}
    incoming_finding_actions: dict[tuple[str, tuple[str, ...]], str] = {}
    incoming_findings = {finding.id: finding for finding in incoming_plan.findings}
    incoming_topics = {topic.id: topic for topic in incoming_plan.audit_topics}
    for question in incoming_plan.review_questions:
        action = incoming_answers.get(question.id) or incoming_answers.get(question.topic_id)
        if action and question.topic_id in incoming_topics:
            for finding_id in incoming_topics[question.topic_id].finding_ids:
                incoming_topic_actions[finding_id] = action
                finding = incoming_findings.get(finding_id)
                if finding is not None:
                    incoming_finding_actions[
                        (finding.category.value, tuple(sorted(finding.source_message_ids)))
                    ] = action
    incoming_payloads = {
        topic.id: _effective_topic_payload(incoming_plan, topic)
        for topic in incoming_plan.audit_topics
    }
    expected = incoming_plan.preview_fingerprint
    if expected and expected != preview_fingerprint(original):
        diagnostics.append("preview_fingerprint_mismatch")
        empty = ReviewedFactsAppendix(language=incoming_plan.language)
        return PreviewFinalization(
            original_preview=original,
            final_summary=original,
            appendix=empty,
            changed=False,
            diagnostics=diagnostics,
        )
    plan = validate_review_plan(incoming_plan, source_messages, preview=original)

    blocked_topic_ids: set[str] = set()
    blocked_finding_ids: set[str] = set()
    for incoming_topic in incoming_plan.audit_topics:
        action = incoming_answers.get(incoming_topic.id)
        if action is None:
            for question in incoming_plan.review_questions:
                if question.topic_id == incoming_topic.id:
                    action = incoming_answers.get(question.id)
                    break
        writes = incoming_topic.disposition is AuditDisposition.AUTO_CORRECT or action in {
            "keep",
            "add",
            "correct",
        }
        if not writes:
            continue
        rebuilt_topic = next(
            (topic for topic in plan.audit_topics if topic.id == incoming_topic.id),
            None,
        )
        if (
            rebuilt_topic is None
            or _effective_topic_payload(plan, rebuilt_topic)
            != incoming_payloads[incoming_topic.id]
        ):
            blocked_topic_ids.add(incoming_topic.id)
            blocked_finding_ids.update(incoming_topic.finding_ids)
            diagnostics.append(f"approved_text_changed:{incoming_topic.id}")

    safe_topics = [
        topic.model_copy(update={
            "disposition": AuditDisposition.ACCEPT_PREVIEW,
            "recommended_action": "accept_preview",
            "requires_user_preference": False,
        }) if topic.id in blocked_topic_ids else topic
        for topic in plan.audit_topics
    ]
    blocked_corrections = {
        finding.suggested_correction.casefold()
        for finding in plan.findings
        if finding.id in blocked_finding_ids
    }
    safe_plan = plan.model_copy(update={
        "audit_topics": safe_topics,
        "review_questions": [
            question for question in plan.review_questions
            if question.topic_id not in blocked_topic_ids
        ],
        "auto_corrections": [
            correction for correction in plan.auto_corrections
            if correction.casefold() not in blocked_corrections
        ],
    })

    answers_by_key = _answer_map(answers)
    finding_by_id = {finding.id: finding for finding in plan.findings}
    edits: list[PreviewEdit] = []
    replacements: list[tuple[str, str, str, str | None]] = []
    for topic in plan.audit_topics:
        if topic.id in blocked_topic_ids:
            continue
        action = None
        if topic.disposition is AuditDisposition.ASK_USER:
            action = answers_by_key.get(topic.id)
            if action is None:
                for question in plan.review_questions:
                    if question.topic_id == topic.id:
                        action = answers_by_key.get(question.id)
                        break
            if action is None:
                action = next(
                    (
                        incoming_topic_actions.get(finding_id)
                        for finding_id in topic.finding_ids
                        if incoming_topic_actions.get(finding_id) is not None
                    ),
                    None,
                )
            if action is None:
                action = next(
                    (
                        incoming_finding_actions.get(
                            (finding.category.value, tuple(sorted(finding.source_message_ids)))
                        )
                        for finding_id in topic.finding_ids
                        if (finding := finding_by_id.get(finding_id)) is not None
                        and incoming_finding_actions.get(
                            (finding.category.value, tuple(sorted(finding.source_message_ids)))
                        ) is not None
                    ),
                    None,
                )
        should_apply = (
            topic.operation == AuditOperation.REPLACE
            and (
                topic.disposition is AuditDisposition.AUTO_CORRECT
                or action in {"correct", "add"}
            )
        )
        if not should_apply:
            continue
        target = topic.current_summary_target or next(
            (
                finding.current_summary_target or finding.current_summary_text
                for finding_id in topic.finding_ids
                if (finding := finding_by_id.get(finding_id)) is not None
                and (finding.current_summary_target or finding.current_summary_text)
            ),
            None,
        )
        replacement = topic.proposed_text or next(
            (
                finding.proposed_text or finding.suggested_correction
                for finding_id in topic.finding_ids
                if (finding := finding_by_id.get(finding_id)) is not None
            ),
            None,
        )
        if not target or not replacement:
            diagnostics.append(f"edit_target_missing:{topic.id}")
            continue
        count = original.count(target)
        if count != 1:
            diagnostics.append(f"edit_target_not_unique:{topic.id}:{count}")
            edits.append(PreviewEdit(
                id=f"edit_{topic.id}",
                target=target,
                replacement=replacement,
                topic_id=topic.id,
                status="skipped",
                reason="target must occur exactly once in the original preview",
            ))
            continue
        replacements.append(
            (target, replacement, topic.id, topic.finding_ids[0] if topic.finding_ids else None)
        )

    edited = original
    # Longer targets first prevents a short target from consuming a larger,
    # overlapping exact sentence. Overlap is still rejected rather than guessed.
    for target, replacement, topic_id, finding_id in sorted(
        replacements,
        key=lambda item: (-len(item[0]), item[2]),
    ):
        if edited.count(target) != 1:
            diagnostics.append(f"edit_target_changed:{topic_id}")
            edits.append(PreviewEdit(
                id=f"edit_{topic_id}", target=target, replacement=replacement,
                topic_id=topic_id, finding_id=finding_id, status="skipped",
                reason="target was no longer unique after an earlier edit",
            ))
            continue
        edited = edited.replace(target, replacement, 1)
        edits.append(PreviewEdit(
            id=f"edit_{topic_id}", target=target, replacement=replacement,
            topic_id=topic_id, finding_id=finding_id, status="applied",
            reason="exact unique source-backed target",
        ))

    appendix = _with_carried_forward(
        edited,
        build_reviewed_facts(safe_plan, answers, source_messages, preview=original, validated=True),
    )
    final = append_reviewed_facts(edited, appendix)
    return PreviewFinalization(
        original_preview=original,
        final_summary=final,
        appendix=appendix,
        changed=final != original,
        edits=edits,
        diagnostics=diagnostics,
    )
