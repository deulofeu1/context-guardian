from context_guardian import (
    AuditDisposition,
    CandidateCategory,
    ContextGuardian,
    ReviewedFactsAppendix,
    ReviewPlan,
    append_reviewed_facts,
    finalize_preview,
)
from context_guardian.models import AuditFinding, AuditTopic, ReviewOption, ReviewQuestion


def review_plan() -> ReviewPlan:
    finding = AuditFinding(
        id="finding-db",
        issue_type="missing",
        category=CandidateCategory.DECISION,
        summary="SQLite was abandoned because of concurrency issues.",
        why_it_matters="The database decision affects future implementation.",
        suggested_correction="SQLite was abandoned because of concurrency issues.",
        importance=0.9,
        confidence=0.95,
    )
    topic = AuditTopic(
        id="topic-side",
        title="Package discussion",
        summary="The package discussion concluded that the adapter should stay optional.",
        finding_ids=[],
        impact=0.5,
        confidence=0.4,
        relevance_to_main_goal=0.2,
        requires_user_preference=True,
        disposition=AuditDisposition.ASK_USER,
        recommended_action="drop",
        suggested_correction="The adapter should stay optional.",
    )
    question = ReviewQuestion(
        id="question-side",
        topic_id=topic.id,
        title=topic.title,
        question="Should the compaction specially preserve this topic?",
        context="This was a side discussion.",
        why_it_matters="It may affect a later setup choice.",
        recommendation="drop",
        options=[
            ReviewOption(id="keep", label="Keep key conclusion", description="Append the key conclusion."),
            ReviewOption(id="drop", label="Do not specially preserve", description="Do not append it."),
        ],
    )
    return ReviewPlan(
        language="en",
        findings=[finding],
        audit_topics=[topic],
        auto_corrections=[
            finding.suggested_correction,
            "SQLite was abandoned because of concurrency issues.",
        ],
        review_questions=[question],
        accepted_omissions=["npm install output"],
    )


def test_reviewed_facts_are_deterministic_and_exclude_drop_ui_material():
    guardian = ContextGuardian()
    first = guardian.build_reviewed_facts(review_plan=review_plan(), answers=[])
    second = guardian.build_reviewed_facts(review_plan=review_plan(), answers=[])

    assert first.model_dump() == second.model_dump()
    assert len(first.facts) == 1
    assert first.facts[0].origin == "auto_correction"
    assert "npm" not in first.text
    assert "Do not append" not in first.text
    assert "may affect" not in first.text


def test_human_keep_adds_only_topic_key_conclusion_and_maps_topic_id():
    appendix = ContextGuardian().build_reviewed_facts(
        review_plan=review_plan(),
        answers=[{"question_id": "question-side", "topic_id": "topic-side", "action": "keep"}],
    )
    assert [fact.origin for fact in appendix.facts] == ["auto_correction", "human_keep"]
    assert appendix.facts[1].topic_id == "topic-side"
    assert appendix.facts[1].text == "The adapter should stay optional."


def test_append_is_append_only_and_idempotent():
    plan = review_plan()
    original = "Native preview line 1.\nNative preview line 2."
    finalization = finalize_preview(
        preview=original,
        review_plan=plan,
        answers=[{"question_id": "question-side", "action": "keep"}],
    )
    assert finalization.original_preview == original
    assert finalization.final_summary.startswith(original)
    assert finalization.changed is True
    assert finalization.final_summary.count("context-guardian:reviewed-facts:v1") == 1
    assert (
        append_reviewed_facts(finalization.final_summary, finalization.appendix)
        == finalization.final_summary
    )


def test_existing_legal_appendix_is_carried_forward_and_deduplicated():
    old = (
        "Native preview\n\n"
        "<!-- context-guardian:reviewed-facts:v1 -->\n"
        "## Context Guardian Reviewed Facts\n"
        "- Existing decision\n"
        "- SQLite was abandoned because of concurrency issues.\n"
        "<!-- /context-guardian:reviewed-facts -->"
    )
    appendix = ReviewedFactsAppendix(
        language="en",
        facts=[
            {
                "id": "new",
                "text": "SQLite was abandoned because of concurrency issues.",
                "origin": "auto_correction",
            },
            {"id": "newer", "text": "auth.py is unfinished.", "origin": "auto_correction"},
        ],
        text="ignored because facts are rendered deterministically",
    )
    result = append_reviewed_facts(old, appendix)
    assert result.count("context-guardian:reviewed-facts:v1") == 1
    assert result.count("SQLite was abandoned because of concurrency issues.") == 1
    assert "Existing decision" in result
    assert "auth.py is unfinished." in result


def test_malformed_old_appendix_is_preserved_and_new_block_is_added():
    preview = "Native preview\n\n<!-- context-guardian:reviewed-facts:v1 -->\n- old text"
    appendix = ReviewedFactsAppendix(
        language="zh-CN",
        facts=[{"id": "f", "text": "必须保持 API 兼容。", "origin": "human_keep"}],
    )
    result = append_reviewed_facts(preview, appendix)
    assert result.startswith(preview)
    assert result.count("context-guardian:reviewed-facts:v1") == 2
    assert "必须保持 API 兼容。" in result


def test_append_renders_from_validated_facts_not_caller_supplied_text():
    appendix = ReviewedFactsAppendix(
        language="en",
        facts=[{"id": "f", "text": "The API must remain compatible.", "origin": "auto_correction"}],
        text="caller supplied text must not become an appendix",
    )
    result = append_reviewed_facts("Native preview", appendix)
    assert "The API must remain compatible." in result
    assert "caller supplied text" not in result


def test_no_facts_does_not_change_native_preview():
    preview = "Native preview with no reviewed additions."
    plan = ReviewPlan(language="en")
    finalization = finalize_preview(preview=preview, review_plan=plan)
    assert finalization.final_summary == preview
    assert finalization.changed is False
    assert finalization.appendix.text == ""


def test_conflicting_corrections_keep_high_confidence_latest_authoritative_fact():
    plan = review_plan().model_copy(
        update={
            "findings": [
                AuditFinding(
                    id="old",
                    issue_type="missing",
                    category="decision",
                    summary="SQLite is selected.",
                    why_it_matters="Database choice matters.",
                    suggested_correction="SQLite is selected.",
                    importance=0.5,
                    confidence=0.5,
                ),
                AuditFinding(
                    id="new",
                    issue_type="missing",
                    category="decision",
                    summary="SQLite was abandoned because of concurrency issues.",
                    why_it_matters="Database choice matters.",
                    suggested_correction="SQLite was abandoned because of concurrency issues.",
                    importance=0.99,
                    confidence=0.99,
                ),
            ],
            "auto_corrections": [
                "SQLite is selected.",
                "SQLite was abandoned because of concurrency issues.",
            ],
        }
    )
    appendix = ContextGuardian().build_reviewed_facts(review_plan=plan)
    assert [fact.text for fact in appendix.facts] == [
        "SQLite was abandoned because of concurrency issues."
    ]
