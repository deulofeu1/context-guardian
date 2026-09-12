"""Deterministic, no-API-key verification for the included conversation fixture."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .inspector import ContextGuardian
from .models import ConversationMessage, ReviewDecision

EXPECTED_MEMORY = (
    "OAuth",
    "public API",
    "PostgreSQL",
    "SQLite",
    "concurrency",
    "auth.py",
)
EXPECTED_NOISE = ("grep", "npm install", "temporary syntax error")


def _load_payload(path: Path) -> list[ConversationMessage]:
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("messages", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError('conversation file must contain a JSON array or {"messages": [...]}')
    return [ConversationMessage.model_validate(item) for item in items]


def verify_conversation(messages: Iterable[ConversationMessage | dict[str, Any]]) -> dict[str, Any]:
    """Run the stable fixture checks used by contributors and release CI."""

    normalized = [ConversationMessage.model_validate(message) for message in messages]
    guardian = ContextGuardian()
    result = guardian.inspect(normalized)
    repeat = guardian.inspect(normalized)
    retained_text = " ".join(candidate.content for candidate in result.auto_keep + result.review).casefold()
    dropped_text = " ".join(candidate.content for candidate in result.auto_drop).casefold()
    decisions = [ReviewDecision(candidate_id=candidate.id, action="keep") for candidate in result.review]
    guidance = guardian.build_guidance(result.candidates, decisions)
    checkpoint = guardian.build_checkpoint(result.candidates, decisions)
    native_preview = (
        "The project goal is to implement OAuth without modifying the public API.\n"
        "PostgreSQL is now the selected database.\n"
        "Compatibility must remain."
    )
    audit = guardian.audit_preview(normalized, preview=native_preview)
    audit_text = " ".join(audit.auto_corrections).casefold()
    audit_ui_text = " ".join(
        f"{question.title} {question.question} {question.context}"
        for question in audit.review_questions
    ).casefold()
    guidance_text = guidance.text.casefold()
    checkpoint_text = checkpoint.text.casefold()

    memory_hits = [needle for needle in EXPECTED_MEMORY if needle.casefold() in retained_text]
    noise_hits = [needle for needle in EXPECTED_NOISE if needle.casefold() in dropped_text]
    checks = {
        "critical_memory_detected": len(memory_hits) == len(EXPECTED_MEMORY),
        "noise_auto_dropped": len(noise_hits) == len(EXPECTED_NOISE),
        "candidate_ids_stable": [item.id for item in result.candidates]
        == [item.id for item in repeat.candidates],
        "guidance_has_sections": all(
            section in guidance_text for section in ("must preserve:", "can discard:", "unresolved")
        ),
        "guidance_contains_memory": all(needle.casefold() in guidance_text for needle in EXPECTED_MEMORY),
        "guidance_contains_noise": all(needle.casefold() in guidance_text for needle in EXPECTED_NOISE),
        "checkpoint_contains_memory": all(needle.casefold() in checkpoint_text for needle in EXPECTED_MEMORY),
        "checkpoint_excludes_noise": all(
            needle.casefold() not in checkpoint_text for needle in EXPECTED_NOISE
        ),
        "preview_audit_corrects_omissions": "sqlite" in audit_text and "auth.py" in audit_text,
        "review_questions_bounded": len(audit.review_questions) <= 3,
        "review_ui_excludes_noise": not any(needle.casefold() in audit_ui_text for needle in EXPECTED_NOISE),
    }
    metrics = {
        "candidates": len(result.candidates),
        "review_candidates": len(result.review),
        "audit_findings": len(audit.findings),
        "audit_topics": len(audit.audit_topics),
        "review_questions": len(audit.review_questions),
        "critical_memory_retention": len(memory_hits) / len(EXPECTED_MEMORY),
        "noise_removal": len(noise_hits) / len(EXPECTED_NOISE),
        "human_review_cost": len(audit.review_questions),
        "native_preview_audit_memory_retention": sum(
            needle.casefold() in audit_text for needle in ("sqlite", "auth.py")
        ) / 2,
        "checkpoint_memory_retention": sum(
            needle.casefold() in checkpoint_text for needle in EXPECTED_MEMORY
        )
        / len(EXPECTED_MEMORY),
    }
    return {"passed": all(checks.values()), "checks": checks, "metrics": metrics}


def verify_file(path: Path) -> dict[str, Any]:
    return verify_conversation(_load_payload(path))
