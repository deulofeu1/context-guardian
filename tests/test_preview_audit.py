import json
from pathlib import Path

from context_guardian import (
    AuditDisposition,
    ContextGuardian,
    ReviewPlan,
    build_revision_guidance,
)
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


def test_same_side_topic_is_aggregated_and_language_comes_from_users_only():
    messages = [
        {"role": "assistant", "content": "这是中文 assistant 输出，不应决定 UI 语言。"},
        {"role": "user", "content": "I asked about npm scripts."},
        {"role": "user", "content": "I also asked about npm package basics."},
    ]
    plan = ContextGuardian().audit_preview(messages, preview="")
    assert plan.language == "en"
    assert len(plan.review_questions) == 1


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
