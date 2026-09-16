"""Validated, framework-neutral data models used by the core and bridge."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CandidateCategory(StrEnum):
    GOAL = "goal"
    REQUIREMENT = "requirement"
    CONSTRAINT = "constraint"
    DECISION = "decision"
    TODO = "todo"
    WORKING_STATE = "working_state"
    FAILED_ATTEMPT = "failed_attempt"
    USER_PREFERENCE = "user_preference"
    IMPORTANT_FACT = "important_fact"
    FILE_STATE = "file_state"
    TOOL_OUTPUT = "tool_output"
    TEMPORARY = "temporary"


class ReviewAction(StrEnum):
    KEEP = "keep"
    DROP = "drop"
    REVIEW = "review"


class MessageSourceKind(StrEnum):
    """Provenance categories exchanged by host adapters and the Core."""

    UNKNOWN = "unknown"
    USER_AUTHORED = "user_authored"
    ASSISTANT_RESPONSE = "assistant_response"
    ATTACHMENT_CONTENT = "attachment_content"
    TOOL_RESULT = "tool_result"
    DURABLE_TOOL_RESULT = "durable_tool_result"
    EXECUTION_NOISE = "execution_noise"
    INTERNAL_METADATA = "internal_metadata"


class MessageProvenance(BaseModel):
    """Additive source metadata used to decide whether a message is evidence."""

    model_config = ConfigDict(extra="forbid")

    source_kind: MessageSourceKind = MessageSourceKind.UNKNOWN
    user_authored: bool = False
    assistant_response: bool = False
    attachment_content: bool = False
    tool_call: bool = False
    tool_result: bool = False
    system: bool = False
    developer: bool = False
    plugin_internal: bool = False
    planning: bool = False
    compaction_metadata: bool = False
    bookkeeping: bool = False


class AuditIssueType(StrEnum):
    MISSING = "missing"
    INCORRECT = "incorrect"
    STALE = "stale"
    AMBIGUOUS = "ambiguous"


class AuditDisposition(StrEnum):
    AUTO_CORRECT = "auto_correct"
    ACCEPT_PREVIEW = "accept_preview"
    ASK_USER = "ask_user"


class ConversationMessage(BaseModel):
    """A minimal message shape that adapters can normalize into."""

    model_config = ConfigDict(extra="allow")

    role: str
    content: str
    id: str | None = None
    tool_name: str | None = None
    is_error: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: MessageProvenance = Field(default_factory=MessageProvenance)

    @field_validator("content", mode="before")
    @classmethod
    def normalize_content(cls, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts: list[str] = []
            for block in value:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(parts)
        return str(value)

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_provenance(cls, value: Any) -> Any:
        """Keep the pre-0.3.1 public message shape source-safe by default.

        Adapters provide explicit provenance for host-specific messages.  Direct
        Core callers that only provide the historical role/content shape retain
        the old user/assistant behavior; every other unknown role is treated as
        internal metadata and cannot become evidence.
        """

        if not isinstance(value, dict):
            return value
        existing = value.get("provenance")
        if existing is not None:
            existing_kind = (
                existing.get("source_kind")
                if isinstance(existing, dict)
                else getattr(existing, "source_kind", None)
            )
            if existing_kind not in {None, MessageSourceKind.UNKNOWN, MessageSourceKind.UNKNOWN.value}:
                return value
        role = str(value.get("role", ""))
        if role == "user":
            inferred = {
                "source_kind": MessageSourceKind.USER_AUTHORED,
                "user_authored": True,
            }
        elif role == "assistant":
            inferred = {
                "source_kind": MessageSourceKind.ASSISTANT_RESPONSE,
                "assistant_response": True,
            }
        elif role in {"tool", "toolResult", "tool_result", "bashExecution"}:
            inferred = {
                "source_kind": MessageSourceKind.TOOL_RESULT,
                "tool_result": True,
            }
        else:
            inferred = {
                "source_kind": MessageSourceKind.INTERNAL_METADATA,
                "plugin_internal": True,
            }
        return {**value, "provenance": inferred}


class MemoryCandidate(BaseModel):
    """An atomic piece of context that may be preserved through compaction."""

    model_config = ConfigDict(extra="forbid")

    id: str
    content: str = Field(min_length=1)
    category: CandidateCategory
    importance: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    suggested_action: ReviewAction
    reason: str | None = None
    source_message_ids: list[str] = Field(default_factory=list)


class ReviewDecision(BaseModel):
    candidate_id: str
    action: Literal["keep", "drop"]


class ReviewTopicDecision(BaseModel):
    """A user's decision about one bounded, topic-level review question."""

    topic_id: str
    action: Literal["keep", "drop"]


class ReviewTopic(BaseModel):
    """A human-readable group of atomic candidates shown as one question."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    recommendation: Literal["keep", "drop"]
    candidate_ids: list[str] = Field(min_length=1)
    evidence_snippets: list[str] = Field(default_factory=list, max_length=3)


class AuditFinding(BaseModel):
    """A source-backed discrepancy found while auditing a native preview."""

    model_config = ConfigDict(extra="forbid")

    id: str
    issue_type: AuditIssueType
    category: CandidateCategory
    summary: str = Field(min_length=1)
    # Provider-authored, readable UI text. It is never used as an authoritative
    # correction; suggested_correction/evidence_snippets remain source-grounded.
    display_summary: str | None = Field(default=None, max_length=500)
    why_it_matters: str = Field(min_length=1)
    suggested_correction: str = Field(min_length=1)
    importance: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    source_message_ids: list[str] = Field(default_factory=list)
    evidence_snippets: list[str] = Field(default_factory=list, max_length=2)


class AuditTopic(BaseModel):
    """A semantic group of findings used for automatic resolution or UI review."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    finding_ids: list[str] = Field(default_factory=list, max_length=20)
    impact: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    relevance_to_main_goal: float = Field(ge=0, le=1)
    requires_user_preference: bool = False
    disposition: AuditDisposition
    recommended_action: Literal["keep", "drop", "correct", "accept_preview"] = "accept_preview"
    suggested_correction: str | None = None
    evidence_snippets: list[str] = Field(default_factory=list, max_length=3)


class ReviewOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Literal["keep", "drop"]
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)


class ReviewQuestion(BaseModel):
    """One bounded, topic-level question shown by a host adapter."""

    model_config = ConfigDict(extra="forbid")

    id: str
    topic_id: str
    title: str = Field(min_length=1)
    question: str = Field(min_length=1)
    context: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    recommendation: Literal["keep", "drop"]
    options: list[ReviewOption] = Field(min_length=2, max_length=2)
    # Exact source excerpts are shown separately from the localized question.
    evidence_snippets: list[str] = Field(default_factory=list, max_length=3)


class AuditCoverage(BaseModel):
    """Request-local coverage facts for a bounded host-model audit."""

    total_source_messages: int = Field(default=0, ge=0)
    attempted_source_messages: int = Field(default=0, ge=0)
    covered_source_messages: int = Field(default=0, ge=0)
    failed_chunks: int = Field(default=0, ge=0)
    chunks: int = Field(default=0, ge=0)
    complete: bool = True


class ReviewPlan(BaseModel):
    """Preview audit result and the bounded review surface for host adapters."""

    model_config = ConfigDict(extra="forbid")

    language: Literal["zh-CN", "en"] = "en"
    overview: str = ""
    auto_preserve_summary: str = ""
    findings: list[AuditFinding] = Field(default_factory=list, max_length=20)
    audit_topics: list[AuditTopic] = Field(default_factory=list, max_length=10)
    auto_corrections: list[str] = Field(default_factory=list, max_length=20)
    accepted_omissions: list[str] = Field(default_factory=list, max_length=20)
    review_questions: list[ReviewQuestion] = Field(default_factory=list, max_length=3)
    diagnostics: list[str] = Field(default_factory=list, max_length=5)
    audit_status: Literal[
        "success",
        "no_issues",
        "budget_exhausted",
        "source_rejected",
        "model_failed",
        "rules_fallback",
        "incomplete",
    ] = "success"
    degraded: bool = False
    degradation_reason: str | None = None
    coverage: AuditCoverage = Field(default_factory=AuditCoverage)
    # Kept for compatibility with the 0.1 topic planner. Maintained adapters use
    # audit_topics/review_questions instead.
    review_topics: list[ReviewTopic] = Field(default_factory=list, max_length=3)

    @field_validator("language", mode="before")
    @classmethod
    def normalize_language(cls, value: Any) -> Any:
        return "zh-CN" if value == "zh" else value


class ReviewedFact(BaseModel):
    """One deterministic fact approved for appending to a native preview."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=500)
    origin: Literal["auto_correction", "human_keep", "carried_forward"]
    topic_id: str | None = Field(default=None, max_length=120)
    category: CandidateCategory | None = None


class ReviewedFactsAppendix(BaseModel):
    """A versioned, deterministic appendix that can be added to host output."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    language: Literal["zh-CN", "en"] = "en"
    facts: list[ReviewedFact] = Field(default_factory=list, max_length=50)
    text: str = Field(default="", max_length=32_000)


class PreviewFinalization(BaseModel):
    """The original native preview and its append-only finalized form."""

    model_config = ConfigDict(extra="forbid")

    original_preview: str
    final_summary: str
    appendix: ReviewedFactsAppendix
    changed: bool


class InspectionResult(BaseModel):
    candidates: list[MemoryCandidate] = Field(default_factory=list)
    auto_keep: list[MemoryCandidate] = Field(default_factory=list)
    auto_drop: list[MemoryCandidate] = Field(default_factory=list)
    review: list[MemoryCandidate] = Field(default_factory=list)
    review_plan: ReviewPlan = Field(default_factory=ReviewPlan)
    mode: Literal["rules", "provider"] = "rules"
    policy_version: str = "1"
    degraded: bool = False
    diagnostics: list[str] = Field(default_factory=list, max_length=5)

    @classmethod
    def from_candidates(
        cls,
        candidates: list[MemoryCandidate],
        *,
        mode: Literal["rules", "provider"],
        policy_version: str,
        review_plan: ReviewPlan | None = None,
        degraded: bool = False,
        diagnostics: list[str] | None = None,
    ) -> InspectionResult:
        return cls(
            candidates=candidates,
            auto_keep=[c for c in candidates if c.suggested_action is ReviewAction.KEEP],
            auto_drop=[c for c in candidates if c.suggested_action is ReviewAction.DROP],
            review=[c for c in candidates if c.suggested_action is ReviewAction.REVIEW],
            review_plan=review_plan or ReviewPlan(),
            mode=mode,
            policy_version=policy_version,
            degraded=degraded,
            diagnostics=diagnostics or [],
        )


class CompactionGuidance(BaseModel):
    """Structured guidance plus the text passed to the host agent summarizer."""

    must_preserve: list[str] = Field(default_factory=list)
    can_discard: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    text: str = ""

    def render(self) -> str:
        sections: list[str] = [
            "Context Guardian review guidance. This is guidance for the native compaction "
            "summary, not a replacement summary.",
            "",
            "Must preserve:",
        ]
        sections.extend(f"- {item}" for item in self.must_preserve or ["(none)"])
        sections.extend(["", "Can discard:"])
        sections.extend(f"- {item}" for item in self.can_discard or ["(none)"])
        sections.extend(["", "Unresolved / review carefully:"])
        sections.extend(f"- {item}" for item in self.unresolved or ["(none)"])
        return "\n".join(sections)


class ContextCheckpoint(BaseModel):
    """A durable, reviewed project-state document for assisted integrations."""

    goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    failed_attempts: list[str] = Field(default_factory=list)
    current_state: list[str] = Field(default_factory=list)
    todos: list[str] = Field(default_factory=list)
    text: str = ""

    def render(self) -> str:
        sections = (
            ("Goal", self.goals),
            ("Constraints", self.constraints),
            ("Decisions", self.decisions),
            ("Failed Attempts", self.failed_attempts),
            ("Current State", self.current_state),
            ("TODO", self.todos),
        )
        lines = [
            "# Context Guardian Checkpoint",
            "",
            "Reviewed project state generated by Context Guardian. "
            "This is a checkpoint, not a full conversation summary.",
        ]
        for name, items in sections:
            lines.extend(["", f"## {name}"])
            lines.extend(f"- {item}" for item in items or ["(none)"])
        return "\n".join(lines)
