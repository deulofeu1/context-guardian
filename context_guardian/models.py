"""Validated, framework-neutral data models used by the core and bridge."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class ConversationMessage(BaseModel):
    """A minimal message shape that adapters can normalize into."""

    model_config = ConfigDict(extra="allow")

    role: str
    content: str
    id: str | None = None
    tool_name: str | None = None
    is_error: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

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


class InspectionResult(BaseModel):
    candidates: list[MemoryCandidate] = Field(default_factory=list)
    auto_keep: list[MemoryCandidate] = Field(default_factory=list)
    auto_drop: list[MemoryCandidate] = Field(default_factory=list)
    review: list[MemoryCandidate] = Field(default_factory=list)
    mode: Literal["rules", "provider"] = "rules"
    policy_version: str = "1"

    @classmethod
    def from_candidates(
        cls,
        candidates: list[MemoryCandidate],
        *,
        mode: Literal["rules", "provider"],
        policy_version: str,
    ) -> InspectionResult:
        return cls(
            candidates=candidates,
            auto_keep=[c for c in candidates if c.suggested_action is ReviewAction.KEEP],
            auto_drop=[c for c in candidates if c.suggested_action is ReviewAction.DROP],
            review=[c for c in candidates if c.suggested_action is ReviewAction.REVIEW],
            mode=mode,
            policy_version=policy_version,
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
