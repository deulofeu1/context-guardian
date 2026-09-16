import json
from pathlib import Path

from context_guardian import (
    AuditDisposition,
    ContextGuardian,
    ReviewPlan,
    build_revision_guidance,
)
from context_guardian.audit import AuditInputBuilder, is_execution_noise
from context_guardian.models import (
    AuditFinding,
    AuditTopic,
    CandidateCategory,
    ReviewOption,
    ReviewQuestion,
)
from context_guardian.review import configured_max_review_questions


def fixture_messages():
    return json.loads(
        (Path(__file__).parents[1] / "examples" / "conversation.json").read_text(encoding="utf-8")
    )["messages"]


def test_accurate_native_preview_needs_no_questions():
    preview = (
        "The goal is to implement OAuth without modifying the public API.\n"
        "SQLite caused concurrency issues under parallel requests and was abandoned.\n"
        "PostgreSQL is now the selected database.\n"
        "auth.py is still incomplete."
    )
    plan = ContextGuardian().audit_preview(fixture_messages(), preview=preview)
    assert plan.review_questions == []
    assert plan.auto_corrections == []
    assert all(topic.disposition is not AuditDisposition.ASK_USER for topic in plan.audit_topics)


def test_missing_durable_preview_items_become_source_backed_corrections():
    plan = ContextGuardian().audit_preview(
        fixture_messages(),
        preview="OAuth is being implemented. PostgreSQL is selected.",
    )
    corrections = " ".join(plan.auto_corrections).casefold()
    assert "sqlite" in corrections
    assert "auth.py" in corrections
    assert all(finding.suggested_correction for finding in plan.findings)


def test_review_budget_and_noise_are_hard_bounded():
    messages = [
        {"id": f"m-{index}", "role": "user", "content": f"I asked about npm package concept {index}."}
        for index in range(140)
    ]
    messages.extend(
        [
            {"role": "tool", "content": "npm install completed successfully."},
            {
                "role": "tool",
                "content": "permission boilerplate: Operations that require approval may ask "
                "through the configured answers.",
            },
            {"role": "tool", "content": "sha256 0123456789abcdef0123456789abcdef0123456789abcdef"},
        ]
    )
    plan = ContextGuardian().audit_preview(messages, preview="", max_review_questions=3)
    assert len(plan.findings) <= 20
    assert len(plan.audit_topics) <= 10
    assert len(plan.review_questions) <= 3
    ui_text = " ".join(
        f"{question.title} {question.question} {question.context}"
        for question in plan.review_questions
    ).casefold()
    assert "npm install" not in ui_text
    assert "0123456789abcdef" not in ui_text
    assert "permission boilerplate" not in ui_text


def test_audit_topics_can_exceed_question_budget_without_exposing_more_questions():
    messages = [
        {"role": "user", "content": "I asked about deployment workflow."},
        {"role": "user", "content": "I asked about licensing options."},
        {"role": "user", "content": "I asked about team onboarding."},
        {"role": "user", "content": "I asked about release announcements."},
    ]
    plan = ContextGuardian().audit_preview(messages, preview="", max_review_questions=3)
    assert len(plan.audit_topics) > 3
    assert len(plan.review_questions) == 3


def test_input_builder_chunks_at_message_boundaries_and_filters_machine_noise():
    important = "Constraint: preserve the public API.\n" + ("keep this line\n" * 80)
    messages = [{"id": "important", "role": "user", "content": important}]
    messages.extend(
        {"id": f"m-{index}", "role": "user", "content": "routine context " + ("x" * 900)}
        for index in range(8)
    )
    chunks = AuditInputBuilder(max_chars=4_000).build_chunks(messages, preview="native preview")
    assert len(chunks) > 1
    assert any("Constraint: preserve the public API." in chunk.text for chunk in chunks)
    assert "partial" not in chunks[0].text
    assert is_execution_noise("The image metadata probe found dimensions 100x100.")
    assert is_execution_noise('{"request_id":"abc","arguments":{}}')
    assert is_execution_noise("temporary run UUID 123e4567-e89b-12d3-a456-426614174000")
    assert is_execution_noise("npm install completed successfully.")
    assert not is_execution_noise("npm 基础概念旁支讨论")


class ChunkAuditProvider:
    def __init__(self):
        self.calls = 0

    def generate_structured(self, prompt: str, schema: type[ReviewPlan]) -> ReviewPlan:
        self.calls += 1
        import re

        match = re.search(r"\[user id=([^\]]+)\]\n([^\n]+)", prompt)
        source_id = match.group(1) if match else f"large-{self.calls - 1}"
        evidence = match.group(2) if match else "State 0: important context"
        finding = AuditFinding(
            id=f"finding-{self.calls}",
            issue_type="missing",
            category=CandidateCategory.TODO,
            summary=evidence,
            why_it_matters="The unfinished work may affect the next step.",
            suggested_correction=evidence,
            importance=0.8,
            confidence=0.9,
            source_message_ids=[source_id],
            evidence_snippets=[evidence],
        )
        topic = AuditTopic(
            id=f"topic-{self.calls}",
            title=f"Chunk {self.calls}",
            summary=finding.summary,
            finding_ids=[finding.id],
            impact=0.8,
            confidence=0.9,
            relevance_to_main_goal=0.8,
            disposition=AuditDisposition.AUTO_CORRECT,
            recommended_action="correct",
            suggested_correction=finding.suggested_correction,
        )
        return ReviewPlan(
            language="en",
            findings=[finding],
            audit_topics=[topic],
            auto_corrections=[finding.suggested_correction],
        )


def test_provider_audit_chunks_large_input_and_merges_findings():
    provider = ChunkAuditProvider()
    messages = [
        {"id": f"large-{index}", "role": "user", "content": f"State {index}: " + ("important context " * 500)}
        for index in range(14)
    ]
    plan = ContextGuardian(provider=provider).audit_preview(messages, preview="native preview")
    assert provider.calls > 1
    assert len(plan.findings) == provider.calls
    assert 0 < len(plan.audit_topics) <= provider.calls


def test_same_side_topic_is_aggregated_and_language_comes_from_users_only():
    messages = [
        {"role": "assistant", "content": "这是中文 assistant 输出，不应决定 UI 语言。"},
        {"role": "user", "content": "I asked about npm scripts."},
        {"role": "user", "content": "I also asked about npm package basics."},
    ]
    plan = ContextGuardian().audit_preview(messages, preview="")
    assert plan.language == "en"
    assert len(plan.review_questions) == 1


def test_technical_english_terms_do_not_outvote_chinese_user_prose():
    messages = [
        {
            "role": "user",
            "content": (
                "目标是让 Context Guardian fixture smoke test 支持 public API 兼容。"
                "请保留当前约束。"
            ),
        },
    ]
    plan = ContextGuardian().audit_preview(messages, preview="")
    assert plan.language == "zh-CN"


def test_chinese_review_question_localizes_topic_ui_with_technical_terms():
    messages = [
        {"role": "assistant", "content": "English assistant output should not set the UI language."},
        {"role": "user", "content": "顺便讨论一下 npm 的基本用途，我不确定以后是否需要继续使用。"},
    ]
    plan = ContextGuardian().audit_preview(messages, preview="")
    assert plan.language == "zh-CN"
    assert len(plan.review_questions) == 1
    question = plan.review_questions[0]
    assert question.question.startswith("压缩后是否需要特别保留")
    assert question.options[0].label == "保留关键结论"
    assert question.options[1].label == "无需特别保留"
    assert "原始对话" in question.context


def test_revision_guidance_is_incremental_and_maps_topic_answer():
    finding = AuditFinding(
        id="f1",
        issue_type="missing",
        category=CandidateCategory.TODO,
        summary="auth.py is incomplete",
        why_it_matters="It affects the next implementation step.",
        suggested_correction="auth.py is incomplete and needs the callback.",
        importance=0.9,
        confidence=0.9,
    )
    topic = AuditTopic(
        id="t1",
        title="Unfinished callback work",
        summary="The callback remains unfinished.",
        finding_ids=["f1"],
        impact=0.8,
        confidence=0.8,
        relevance_to_main_goal=0.9,
        requires_user_preference=True,
        disposition=AuditDisposition.ASK_USER,
        recommended_action="drop",
        suggested_correction="The callback remains unfinished.",
    )
    plan = ReviewPlan(
        language="en",
        findings=[finding],
        audit_topics=[topic],
        review_questions=[
            ReviewQuestion(
                id="q1",
                topic_id="t1",
                title="Unfinished callback work",
                question="Preserve it?",
                context="The callback remains unfinished.",
                why_it_matters="It may be needed next.",
                recommendation="drop",
                options=[
                    ReviewOption(id="keep", label="Keep", description="Keep the key conclusion."),
                    ReviewOption(id="drop", label="Drop", description="Accept the preview."),
                ],
            )
        ],
    )
    guidance = build_revision_guidance(plan, [{"question_id": "q1", "action": "keep"}])
    assert "The callback remains unfinished." in guidance.text
    assert "replacement summary" in guidance.text
    assert "q1" not in guidance.text


def test_review_budget_configuration_is_bounded():
    assert configured_max_review_questions(0) == 0
    assert configured_max_review_questions(3) == 3
    assert configured_max_review_questions(4) == 3
    assert configured_max_review_questions(-1) == 3


def test_zero_budget_resolves_unanswered_high_value_topics_conservatively():
    plan = ContextGuardian().audit_preview(
        fixture_messages(),
        preview="The project goal is to implement OAuth without changing the public API.",
        max_review_questions=0,
    )
    assert plan.review_questions == []
    assert "sqlite" in " ".join(plan.auto_corrections).casefold()
    assert "auth.py" in " ".join(plan.auto_corrections).casefold()


class NoisyAuditProvider:
    def generate_structured(self, prompt: str, schema: type[ReviewPlan]) -> ReviewPlan:
        topic = AuditTopic(
            id="topic-noisy",
            title="A side topic",
            summary="A side topic summary.",
            finding_ids=[],
            impact=0.4,
            confidence=0.7,
            relevance_to_main_goal=0.2,
            requires_user_preference=True,
            disposition=AuditDisposition.ASK_USER,
            recommended_action="drop",
            suggested_correction="npm install output should not be retained.",
        )
        return ReviewPlan(
            language="en",
            audit_topics=[topic],
            auto_corrections=["npm install completed successfully."],
            review_questions=[
                ReviewQuestion(
                    id="question-noisy",
                    topic_id=topic.id,
                    title="A side topic",
                    question="Should we preserve npm install?",
                    context="The command ran during setup.",
                    why_it_matters="It may be useful.",
                    recommendation="drop",
                    options=[
                        ReviewOption(id="keep", label="Keep", description="Keep it."),
                        ReviewOption(id="drop", label="Drop", description="Drop it."),
                    ],
                )
            ],
        )


def test_provider_audit_sanitizes_execution_noise_from_review_surface():
    plan = ContextGuardian(provider=NoisyAuditProvider()).audit_preview(
        fixture_messages(), preview="The project goal is implemented."
    )
    assert plan.review_questions == []
    assert plan.auto_corrections == []


class PartiallyFailingAuditProvider(ChunkAuditProvider):
    def generate_structured(self, prompt: str, schema: type[ReviewPlan]) -> ReviewPlan:
        if self.calls + 1 == 2:
            self.calls += 1
            raise RuntimeError("simulated host timeout")
        return super().generate_structured(prompt, schema)


def test_provider_chunk_failure_preserves_successes_and_reports_coverage():
    provider = PartiallyFailingAuditProvider()
    messages = [
        {"id": f"chunk-{index}", "role": "user", "content": f"State {index}: " + ("important context " * 500)}
        for index in range(10)
    ]
    plan = ContextGuardian(provider=provider).audit_preview(messages, preview="native preview")
    assert provider.calls > 2
    assert plan.findings
    assert plan.audit_status == "incomplete"
    assert plan.degraded is True
    assert plan.coverage.failed_chunks == 1
    assert plan.coverage.complete is False
    assert any("chunk failed" in diagnostic.lower() for diagnostic in plan.diagnostics)


def test_oversized_single_message_is_reported_as_incomplete_not_silently_dropped():
    provider = ChunkAuditProvider()
    message = {"id": "huge", "role": "user", "content": "The goal is durable. " + ("x" * 100_000)}
    plan = ContextGuardian(provider=provider).audit_preview([message], preview="native preview")
    assert provider.calls == 1
    assert plan.coverage.total_source_messages == 1
    assert plan.coverage.covered_source_messages == 0
    assert plan.coverage.complete is False
    assert plan.audit_status == "incomplete"
    assert plan.diagnostics


def test_provider_source_rejection_is_distinguished_from_no_findings():
    class RejectedAuditProvider:
        def generate_structured(self, prompt: str, schema: type[ReviewPlan]) -> ReviewPlan:
            return ReviewPlan(findings=[AuditFinding(
                id="provider-finding",
                issue_type="missing",
                category=CandidateCategory.TODO,
                summary="invented",
                why_it_matters="invented",
                suggested_correction="invented",
                importance=0.8,
                confidence=0.8,
                source_message_ids=["missing-source"],
                evidence_snippets=["not in source"],
            )])

    plan = ContextGuardian(provider=RejectedAuditProvider()).audit_preview(
        fixture_messages(), preview="The project goal is implemented."
    )
    assert plan.audit_status == "source_rejected"
    assert plan.degraded is False
    assert any("evidence" in diagnostic for diagnostic in plan.diagnostics)
