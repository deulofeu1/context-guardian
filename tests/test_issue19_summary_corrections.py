from context_guardian import ContextGuardian


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
