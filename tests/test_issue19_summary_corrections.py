import io
import json

from context_guardian import ContextGuardian
from context_guardian.bridge import run_protocol


def _status_messages():
    return [
        {
            "id": "status-source",
            "role": "user",
            "content": "原生 0.3.3 测试未弹窗，因此验证尚未完成。",
        }
    ]


def _status_preview():
    return "原生 0.3.3 测试与最终校验已完成。"


def test_status_conflict_is_primary_review_with_before_after_actions():
    guardian = ContextGuardian()
    plan = guardian.audit_preview(
        _status_messages(),
        preview=_status_preview(),
        language="zh-CN",
    )

    assert len(plan.review_questions) == 1
    finding = plan.findings[0]
    topic = plan.audit_topics[0]
    question = plan.review_questions[0]
    assert finding.issue_type == "incorrect"
    assert finding.task_relation == "primary"
    assert finding.requires_user_confirmation is True
    assert topic.title == "测试验证状态可能不正确"
    assert topic.operation == "replace"
    assert question.options[0].id == "correct"
    assert question.options[1].id == "keep_preview"
    assert _status_preview() in question.context
    assert "验证尚未完成" in question.context
    assert question.evidence_snippets == [
        "原生 0.3.3 测试未弹窗，因此验证尚未完成。"
    ]


def test_accepting_correction_replaces_exact_preview_without_duplicate_old_state():
    guardian = ContextGuardian()
    plan = guardian.audit_preview(_status_messages(), preview=_status_preview(), language="zh-CN")
    question = plan.review_questions[0]
    finalization = guardian.finalize_preview(
        preview=_status_preview(),
        review_plan=plan,
        answers=[{"question_id": question.id, "action": "correct"}],
        messages=_status_messages(),
    )

    assert finalization.edits[0].status == "applied"
    assert "已完成" not in finalization.final_summary
    assert finalization.final_summary.count("验证尚未完成") == 1
    assert finalization.appendix.text == ""


def test_rejecting_correction_keeps_native_preview_untouched():
    guardian = ContextGuardian()
    plan = guardian.audit_preview(_status_messages(), preview=_status_preview(), language="zh-CN")
    question = plan.review_questions[0]
    finalization = guardian.finalize_preview(
        preview=_status_preview(),
        review_plan=plan,
        answers=[{"question_id": question.id, "action": "keep_preview"}],
        messages=_status_messages(),
    )

    assert finalization.changed is False
    assert finalization.final_summary == _status_preview()
    assert finalization.edits == []


def test_preview_fingerprint_mismatch_fails_closed_for_summary_edits():
    guardian = ContextGuardian()
    plan = guardian.audit_preview(_status_messages(), preview=_status_preview(), language="zh-CN")
    question = plan.review_questions[0]
    finalization = guardian.finalize_preview(
        preview="A different native preview.",
        review_plan=plan,
        answers=[{"question_id": question.id, "action": "correct"}],
        messages=_status_messages(),
    )

    assert finalization.changed is False
    assert finalization.final_summary == "A different native preview."
    assert "preview_fingerprint_mismatch" in finalization.diagnostics


def test_more_than_one_hundred_atomic_candidates_still_have_at_most_three_questions():
    messages = [
        {
            "id": f"topic-{index}",
            "role": "user",
            "content": f"I am unsure whether background topic {index} should be retained.",
        }
        for index in range(120)
    ]
    guardian = ContextGuardian()
    assert len(guardian.rule_inspector.inspect(messages, guardian.policy)) >= 100
    plan = guardian.audit_preview(messages, preview="", max_review_questions=3)
    assert len(plan.findings) <= 20
    assert len(plan.review_questions) <= 3


def test_long_contradictory_bullet_is_split_and_corrected_without_validation_error():
    guardian = ContextGuardian()
    long_preview = "- 当前验证与最终校验已完成，并且" + ("补充背景说明" * 600) + "。"

    plan = guardian.audit_preview(
        _status_messages(),
        preview=long_preview,
        language="zh-CN",
    )

    assert len(plan.review_questions) == 1
    finding = plan.findings[0]
    assert finding.current_summary_target == long_preview
    assert len(finding.current_summary_target) > 500
    assert len(finding.current_summary_text or "") <= 500
    assert plan.review_questions[0].current_summary_target == long_preview

    finalization = guardian.finalize_preview(
        preview=long_preview,
        review_plan=plan,
        answers=[{"question_id": plan.review_questions[0].id, "action": "correct"}],
        messages=_status_messages(),
    )

    assert finalization.edits[0].status == "applied"
    assert finalization.final_summary == "原生 0.3.3 测试未弹窗，因此验证尚未完成。"


def test_unbounded_contradictory_bullet_is_preserved_with_diagnostic():
    guardian = ContextGuardian()
    too_long_preview = "- 当前验证与最终校验已完成，并且" + ("补充背景说明" * 3_000) + "。"

    plan = guardian.audit_preview(
        _status_messages(),
        preview=too_long_preview,
        language="zh-CN",
    )

    assert plan.findings
    assert plan.findings[0].operation == "keep_preview"
    assert plan.findings[0].current_summary_target is None
    assert plan.review_questions == []
    assert any("安全精确替换" in diagnostic for diagnostic in plan.diagnostics)


def test_empty_provider_and_failing_provider_do_not_crash_on_long_bullet():
    from context_guardian.models import ReviewPlan

    long_preview = "- 当前验证与最终校验已完成，并且" + ("补充背景说明" * 600) + "。"

    class EmptyProvider:
        def generate_structured(self, prompt, schema):
            return ReviewPlan(language="zh-CN")

    class FailingProvider:
        def generate_structured(self, prompt, schema):
            raise RuntimeError("provider unavailable")

    for provider in (EmptyProvider(), FailingProvider()):
        plan = ContextGuardian(provider=provider).audit_preview(
            _status_messages(),
            preview=long_preview,
            language="zh-CN",
        )
        assert plan.findings
        assert len(plan.review_questions) <= 3


def test_jsonl_bridge_returns_valid_audit_result_for_long_bullet():
    long_preview = "- 当前验证与最终校验已完成，并且" + ("补充背景说明" * 600) + "。"
    request = {
        "protocol_version": 1,
        "type": "request",
        "request_id": "issue-21-long-bullet",
        "operation": "audit_preview",
        "provider": "rules",
        "language": "zh-CN",
        "preview": long_preview,
        "messages": _status_messages(),
    }
    output_stream = io.StringIO()

    assert run_protocol(io.StringIO(json.dumps(request) + "\n"), output_stream) == 0
    response = json.loads(output_stream.getvalue())
    assert response["ok"] is True
    assert response["request_id"] == "issue-21-long-bullet"
    assert len(response["result"]["review_questions"]) == 1
