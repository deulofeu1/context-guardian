"""Deterministic Reviewed Facts generation and append-only finalization.

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

from .audit import is_execution_noise
from .models import (
    CandidateCategory,
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
    return text[:max_length].rstrip()


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
        if key and action in {"keep", "drop"}:
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
) -> ReviewedFactsAppendix:
    """Build a stable appendix from plan corrections and explicit Keep answers."""

    plan = ReviewPlan.model_validate(review_plan)
    facts: list[ReviewedFact] = []
    seen: set[str] = set()

    for correction in _non_conflicting_corrections(plan):
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
        if action != "keep":
            continue
        topic = topic_by_id.get(question.topic_id)
        if topic is None:
            continue
        correction = topic.suggested_correction or topic.summary
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
) -> PreviewFinalization:
    """Build facts and append them, returning an explicit preservation record."""

    appendix = _with_carried_forward(preview, build_reviewed_facts(review_plan, answers))
    final = append_reviewed_facts(preview, appendix)
    return PreviewFinalization(
        original_preview=preview,
        final_summary=final,
        appendix=appendix,
        changed=final != preview,
    )
