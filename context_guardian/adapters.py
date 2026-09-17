"""Framework-neutral adapter contract shared by host integrations."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from .models import (
    CompactionGuidance,
    ContextCheckpoint,
    ConversationMessage,
    InspectionResult,
    MemoryCandidate,
    PreviewFinalization,
    ReviewDecision,
    ReviewedFactsAppendix,
    ReviewPlan,
)


class IntegrationLevel(StrEnum):
    NATIVE = "native"
    ASSISTED = "assisted"


class AdapterCapabilities(BaseModel):
    """Machine-readable capabilities exposed by a host adapter."""

    model_config = ConfigDict(extra="forbid")

    platform: str
    level: IntegrationLevel
    auto_trigger: bool
    host_model: str
    human_review: str
    native_compaction_injection: str
    preview_audit: str = "one native preview → semantic audit → deterministic reviewed-facts append"
    max_review_questions: int = 3
    native_compaction_calls: int = 1
    reviewed_facts: bool = True


class ContextGuardianAdapter(Protocol):
    """Behavioral contract; host adapters may implement it in TypeScript."""

    capabilities: AdapterCapabilities

    def collect_context(self) -> Sequence[ConversationMessage]:
        """Collect the host's current or pending context."""

    def inspect(self, messages: Sequence[ConversationMessage]) -> InspectionResult:
        """Run the legacy atomic inspection API."""

    def audit_preview(self, messages: Sequence[ConversationMessage], preview: str):
        """Audit a host-native preview and return a bounded ReviewPlan."""

    def build_reviewed_facts(
        self,
        review_plan: ReviewPlan,
        answers: Sequence[dict],
        messages: Sequence[ConversationMessage] = (),
    ) -> ReviewedFactsAppendix:
        """Build deterministic facts to append after the native Preview."""

    def finalize_preview(
        self,
        preview: str,
        review_plan: ReviewPlan,
        answers: Sequence[dict],
        messages: Sequence[ConversationMessage] = (),
    ) -> PreviewFinalization:
        """Return exact source-backed edits plus reviewed facts for the native Preview."""

    def review(self, candidates: Sequence[MemoryCandidate]) -> Sequence[ReviewDecision]:
        """Resolve uncertain candidates through the host's review surface."""

    def preserve(
        self,
        candidates: Sequence[MemoryCandidate],
        decisions: Sequence[ReviewDecision],
    ) -> CompactionGuidance | ContextCheckpoint:
        """Inject native guidance or persist an assisted checkpoint."""
