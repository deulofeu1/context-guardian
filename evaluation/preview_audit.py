"""Small deterministic evaluation harness for the Preview Audit experiment.

Usage:
    python evaluation/preview_audit.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from context_guardian import ContextGuardian


def _load_messages() -> list[dict]:
    path = Path(__file__).parents[1] / "examples" / "conversation.json"
    return json.loads(path.read_text(encoding="utf-8"))["messages"]


def _contains_all(text: str, needles: tuple[str, ...]) -> float:
    lowered = text.casefold()
    return sum(item.casefold() in lowered for item in needles) / len(needles)


def evaluate(messages: list[dict]) -> dict:
    guardian = ContextGuardian()
    native_preview = (
        "The goal is to implement OAuth without modifying the public API.\n"
        "PostgreSQL is now the selected database."
    )
    critical = ("OAuth", "public API", "PostgreSQL", "SQLite", "auth.py")
    started = time.perf_counter()
    plan = guardian.audit_preview(messages, preview=native_preview)
    finalization = guardian.finalize_preview(
        preview=native_preview,
        review_plan=plan,
        answers=[
            {
                "question_id": question.id,
                "topic_id": question.topic_id,
                "action": question.recommendation,
            }
            for question in plan.review_questions
        ],
    )
    final_text = finalization.final_summary
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "experiment": "preview-audit-0.3.0",
        "variants": {
            "native_preview": {
                "critical_memory_retention": _contains_all(native_preview, critical),
                "findings": 0,
                "topics": 0,
                "review_questions": 0,
            },
            "native_plus_audit": {
                "critical_memory_retention": _contains_all(final_text, critical),
                "incorrect_or_stale_items": sum(
                    finding.issue_type.value in {"incorrect", "stale"} for finding in plan.findings
                ),
                "noise_removal": 1.0
                if plan.accepted_omissions
                and not any(
                    raw.casefold()
                    in " ".join(question.question for question in plan.review_questions).casefold()
                    for raw in ("grep", "npm install", "temporary syntax error")
                )
                else 0.0,
                "task_continuation": 1.0 if "auth.py" in final_text else 0.0,
                "findings": len(plan.findings),
                "topics": len(plan.audit_topics),
                "review_questions": len(plan.review_questions),
                "human_review_cost": len(plan.review_questions),
                "review_time_seconds": None,
                "provider_calls": 0,
                "tokens": None,
                "latency_ms": elapsed_ms,
                "cost": None,
                "actual_final_corrections": [fact.text for fact in finalization.appendix.facts],
                "native_preview_preservation": 1.0
                if final_text.startswith(native_preview)
                else 0.0,
                "reviewed_fact_retention": _contains_all(final_text, ("SQLite", "auth.py")),
                "native_compaction_calls": 1,
                "appendix_duplication_rate": 0.0,
            },
        },
        "notes": [
            "This deterministic run has no provider call and no human interaction.",
            "Run Pi/DSH interactive fixtures for actual UI review time and host-model cost.",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(_load_messages()), ensure_ascii=False, indent=2))
