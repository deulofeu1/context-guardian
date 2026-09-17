import json
from pathlib import Path

from context_guardian import ContextGuardian
from context_guardian.audit import _contradictory_preview_segment, _contradicts
from context_guardian.models import ConversationMessage
from context_guardian.provenance import is_diagnostic_background, is_execution_noise
from context_guardian.reviewed_facts import _normalize_text, finalize_preview

FIXTURE = Path(__file__).parents[1] / "examples" / "issue23-review-dialog.json"


def fixture_messages():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["messages"]


def test_issue23_fixture_excludes_raw_diagnostics_from_review_surface():
    messages = fixture_messages()
    assert is_execution_noise(messages[6]["content"])
    assert is_execution_noise(messages[7]["content"])
    assert is_execution_noise(messages[8]["content"])
    assert not is_execution_noise(messages[9]["content"])

    plan = ContextGuardian().audit_preview(
        messages,
        preview="目标：实现 OAuth。当前验证已完成。",
        language="zh-CN",
        max_review_questions=3,
    )
    assert len(plan.review_questions) <= 3
    ui_text = json.dumps(
        [question.model_dump(mode="json") for question in plan.review_questions],
        ensure_ascii=False,
    )
    assert "REASONING_EFFORTS" not in ui_text
    assert "anaconda3" not in ui_text
    assert "<path>" not in ui_text
    assert "context_guardian/audit.py" not in ui_text


def test_diagnostic_background_allows_explicit_durable_configuration_decision():
    assert is_diagnostic_background("REASONING_EFFORTS = [off, low, high, max]")
    assert not is_diagnostic_background("结构化审计关闭 reasoning，将输出额度用于 JSON 结果。")


def test_complete_source_conclusion_is_not_blindly_sliced():
    long_fact = "The audit conclusion is complete and must remain visible. " + ("Additional context. " * 100)
    assert _normalize_text(long_fact) == "The audit conclusion is complete and must remain visible."
    assert "Additional context." not in _normalize_text(long_fact)
    assert _normalize_text("A single sentence without a safe boundary " + ("x" * 600)) == ""


def test_unresolved_completion_is_not_marked_as_resolved():
    assert not _contradicts("The review is not yet complete.", "The review is not yet complete.")
    assert _contradicts("The review is not yet complete.", "The review is complete.")


def test_unfinished_file_todo_cannot_target_unrelated_completion_sentence():
    preview = (
        "目标：实现 OAuth，但不能修改 public API。\n"
        "决定：PostgreSQL 是最终数据库方案。\n"
        "当前验证与最终校验已完成。"
    )
    assert _contradictory_preview_segment(
        "TODO：auth.py 仍未完成，需要实现 OAuth 回调。",
        preview,
    ) is None


def test_finalize_preview_rejects_changed_user_approved_write_text():
    messages = [{
        "id": "status",
        "role": "user",
        "content": "The verification is not complete.",
    }]
    guardian = ContextGuardian()
    plan = guardian.audit_preview(messages, preview="The verification is complete.", language="en")
    assert plan.review_questions
    question = plan.review_questions[0]
    altered = plan.model_copy(update={
        "audit_topics": [
            plan.audit_topics[0].model_copy(update={"proposed_text": "The verification is complete forever."})
        ],
        "review_questions": [
            question.model_copy(update={"proposed_text": "The verification is complete forever."})
        ],
    })
    finalization = finalize_preview(
        preview="The verification is complete.",
        review_plan=altered,
        answers=[{"question_id": question.id, "action": "correct"}],
        messages=messages,
    )
    assert finalization.final_summary == "The verification is complete."
    assert finalization.changed is False
    assert any(item.startswith("approved_text_changed:") for item in finalization.diagnostics)


def test_unknown_content_blocks_are_not_trusted_as_message_text():
    message = ConversationMessage.model_validate({
        "id": "wrapped",
        "role": "user",
        "content": [{"type": "xml", "content": "hidden raw wrapper"}],
    })
    assert message.content == ""


def test_status_review_uses_user_source_once_when_assistant_echoes_it():
    source = "The verification is not complete."
    plan = ContextGuardian().audit_preview(
        [
            {"id": "user-status", "role": "user", "content": source},
            {"id": "assistant-echo", "role": "assistant", "content": f"Recorded: {source}"},
        ],
        preview="The verification is complete.",
        language="en",
    )
    assert len(plan.review_questions) == 1
    question = plan.review_questions[0]
    assert question.proposed_text == source
    assert question.source_message_ids == ["user-status"]
