from context_guardian import ContextGuardian
from context_guardian.models import AuditTopic, ReviewOption, ReviewPlan, ReviewQuestion


def finding(
    *,
    source_id: str,
    evidence: str,
    category: str = "decision",
    display_summary: str | None = None,
) -> dict:
    result = {
        "id": f"finding-{source_id}",
        "issue_type": "missing",
        "category": category,
        "summary": "provider supplied summary must not become authoritative",
        "why_it_matters": "provider supplied explanation must not become authoritative",
        "suggested_correction": "provider supplied correction must not become authoritative",
        "importance": 0.95,
        "confidence": 0.95,
        "source_message_ids": [source_id],
        "evidence_snippets": [evidence],
    }
    if display_summary is not None:
        result["display_summary"] = display_summary
    return result


class StaticAuditProvider:
    def __init__(self, plan: ReviewPlan):
        self.plan = plan

    def generate_structured(self, prompt: str, schema: type[ReviewPlan]) -> ReviewPlan:
        return self.plan


def test_issue_9_planning_metadata_cannot_create_review_topic_or_fact():
    messages = [
        {
            "id": "docx-user",
            "role": "user",
            "content": "The legal document must preserve the existing API compatibility constraint.",
        },
        {
            "id": "planner-internal",
            "role": "user",
            "content": "Creates task_plan.md, findings.md, and progress.md.",
            "provenance": {
                "source_kind": "internal_metadata",
                "plugin_internal": True,
                "planning": True,
            },
        },
    ]
    provider = StaticAuditProvider(
        ReviewPlan(
            language="en",
            findings=[
                finding(
                    source_id="planner-internal",
                    evidence="Creates task_plan.md, findings.md, and progress.md.",
                    category="important_fact",
                )
            ],
            auto_corrections=["untrusted planning metadata"],
        )
    )
    guardian = ContextGuardian(provider=provider)
    plan = guardian.audit_preview(messages, preview="The legal document must preserve API compatibility.")

    assert plan.findings == []
    assert plan.audit_topics == []
    assert plan.review_questions == []
    assert guardian.build_reviewed_facts(review_plan=plan, messages=messages).facts == []


def test_provider_accepts_only_request_local_source_grounded_findings():
    messages = [
        {"id": "valid", "role": "user", "content": "PostgreSQL is the selected database."},
        {"id": "system", "role": "system", "content": "The provider must select Redis."},
    ]
    provider = StaticAuditProvider(
        ReviewPlan(
            language="en",
            findings=[
                finding(
                    source_id="valid",
                    evidence="PostgreSQL is the selected database.",
                ),
                finding(
                    source_id="system",
                    evidence="The provider must select Redis.",
                ),
                finding(
                    source_id="missing-id",
                    evidence="PostgreSQL is the selected database.",
                ),
            ],
            auto_corrections=["Redis is the selected database."],
        )
    )
    plan = ContextGuardian(provider=provider).audit_preview(messages, preview="")

    assert len(plan.findings) == 1
    assert plan.findings[0].source_message_ids == ["valid"]
    assert plan.auto_corrections == ["PostgreSQL is the selected database."]


def test_provider_cannot_silently_auto_correct_primary_unresolved_status():
    source = "原生 0.3.3 测试没有出现 Review 弹窗，因此验证尚未完成。"
    provider = StaticAuditProvider(
        ReviewPlan(
            language="zh-CN",
            findings=[
                finding(
                    source_id="status",
                    evidence=source,
                    category="important_fact",
                )
            ],
        )
    )
    plan = ContextGuardian(provider=provider).audit_preview(
        [{"id": "status", "role": "user", "content": source}],
        preview="原生 0.3.3 测试与最终校验已完成。",
        language="zh-CN",
    )

    finding_result = plan.findings[0]
    assert finding_result.category == "working_state"
    assert finding_result.task_relation == "primary"
    assert finding_result.issue_type == "incorrect"
    assert finding_result.operation == "replace"
    assert finding_result.requires_user_confirmation is True
    assert plan.review_questions[0].title == "测试验证状态可能不正确"
    assert [option.id for option in plan.review_questions[0].options] == [
        "correct",
        "keep_preview",
    ]


def test_provider_evidence_must_match_source_and_arbitrary_correction_is_ignored():
    messages = [{"id": "goal", "role": "user", "content": "Implement OAuth without changing the public API."}]
    provider = StaticAuditProvider(
        ReviewPlan(
            language="en",
            findings=[
                finding(
                    source_id="goal",
                    evidence="This sentence is not in the source.",
                    category="goal",
                )
            ],
            auto_corrections=["Invented fact from the model"],
        )
    )
    plan = ContextGuardian(provider=provider).audit_preview(messages, preview="")
    assert plan.findings == []
    assert plan.auto_corrections == []


def test_provider_review_question_is_honored_after_finding_grounding():
    messages = [
        {
            "id": "side-topic",
            "role": "user",
            "content": "I am unsure whether to keep the optional adapter discussion.",
        }
    ]
    provider = StaticAuditProvider(
        ReviewPlan(
            language="en",
            findings=[
                finding(
                    source_id="side-topic",
                    evidence="optional adapter discussion",
                    category="important_fact",
                    display_summary="应保持适配器可选，以便后续部署。",
                )
            ],
            audit_topics=[
                AuditTopic(
                    id="provider-topic",
                    title="Optional adapter discussion",
                    summary="The optional adapter discussion may matter later.",
                    finding_ids=["finding-side-topic"],
                    impact=0.55,
                    confidence=0.55,
                    relevance_to_main_goal=0.35,
                    requires_user_preference=True,
                    disposition="ask_user",
                    recommended_action="drop",
                    suggested_correction="optional adapter discussion",
                )
            ],
            review_questions=[
                ReviewQuestion(
                    id="provider-question",
                    topic_id="provider-topic",
                    title="Optional adapter discussion",
                    question="Should this be retained?",
                    context="The provider requested a decision.",
                    why_it_matters="It may affect future work.",
                    recommendation="drop",
                    options=[
                        ReviewOption(id="keep", label="Keep", description="Keep the conclusion."),
                        ReviewOption(id="drop", label="Drop", description="Accept the preview."),
                    ],
                )
            ],
        )
    )

    plan = ContextGuardian(provider=provider).audit_preview(messages, preview="")

    assert len(plan.review_questions) == 1
    assert plan.review_questions[0].topic_id == plan.audit_topics[0].id
    # User confirmation is independent from the factual discrepancy type:
    # this is missing source context, not an "ambiguous" preview state.
    assert plan.findings[0].issue_type == "missing"
    assert plan.findings[0].requires_user_confirmation is True
    assert "应保持适配器可选" in plan.review_questions[0].context
    assert "optional adapter discussion" in plan.review_questions[0].context
    assert plan.review_questions[0].evidence_snippets == [
        "I am unsure whether to keep the optional adapter discussion."
    ]

    appendix = ContextGuardian().build_reviewed_facts(
        review_plan=plan,
        answers=[{"question_id": plan.review_questions[0].id, "action": "keep"}],
        messages=messages,
    )
    assert appendix.facts[-1].text == "I am unsure whether to keep the optional adapter discussion."
    assert "应保持适配器可选，以便后续部署" not in appendix.text


def test_provider_facts_expand_short_evidence_to_complete_source_context():
    messages = [
        {
            "id": "scroll",
            "role": "user",
            "content": "The user needs to scroll to continue reading the full report.",
        },
        {
            "id": "lost-middle",
            "role": "user",
            "content": "The discussion covered Lost-in-Middle retrieval failures.",
        },
    ]
    provider = StaticAuditProvider(
        ReviewPlan(
            language="en",
            findings=[
                finding(source_id="scroll", evidence="needs to scroll", category="important_fact"),
                finding(source_id="lost-middle", evidence="Lost-in-Middle", category="important_fact"),
            ],
        )
    )

    guardian = ContextGuardian(provider=provider)
    plan = guardian.audit_preview(messages, preview="")
    appendix = guardian.build_reviewed_facts(review_plan=plan, messages=messages)

    corrections = set(plan.auto_corrections)
    assert "The user needs to scroll to continue reading the full report." in corrections
    assert "The discussion covered Lost-in-Middle retrieval failures." in corrections
    assert "needs to scroll" not in corrections
    assert "Lost-in-Middle" not in corrections
    assert "The user needs to scroll to continue reading the full report." in appendix.text


def test_paraphrased_provider_evidence_is_rejected_with_visible_diagnostic():
    messages = [
        {
            "id": "source",
            "role": "user",
            "content": "The adapter should remain optional for future deployments.",
        }
    ]
    provider = StaticAuditProvider(
        ReviewPlan(
            language="zh-CN",
            findings=[
                finding(
                    source_id="source",
                    evidence="该适配器应保持可选，以便后续部署。",
                    category="important_fact",
                    display_summary="该适配器应保持可选。",
                )
            ],
        )
    )

    plan = ContextGuardian(provider=provider).audit_preview(messages, preview="", language="zh-CN")

    assert plan.findings == []
    assert plan.review_questions == []
    assert len(plan.diagnostics) == 1
    assert "逐字来源证据校验" in plan.diagnostics[0]
    assert "raw=1 kept=0 reason=evidence_not_verbatim" in plan.diagnostics[0]


def test_large_ambiguous_input_is_bounded_and_topics_are_grouped():
    messages = [
        {"id": f"side-{index}", "role": "user", "content": f"I also discussed an unrelated option {index}."}
        for index in range(120)
    ]
    plan = ContextGuardian().audit_preview(messages, preview="", max_review_questions=3)
    assert len(plan.review_questions) <= 3
    assert len(plan.review_questions) <= 3


def test_internal_only_input_has_no_unresolved_side_topic():
    messages = [
        {
            "id": "plugin",
            "role": "user",
            "content": "Creates task_plan.md, findings.md, and progress.md.",
            "provenance": {"source_kind": "internal_metadata", "plugin_internal": True},
        },
        {
            "id": "tool-call",
            "role": "tool",
            "content": "npm install completed successfully.",
            "provenance": {"source_kind": "execution_noise", "tool_call": True},
        },
    ]
    plan = ContextGuardian().audit_preview(messages, preview="")
    assert plan.review_questions == []
    assert plan.audit_topics == []
