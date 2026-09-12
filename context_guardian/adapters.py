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
    ReviewDecision,
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


class ContextGuardianAdapter(Protocol):
    """Behavioral contract; host adapters may implement it in TypeScript."""

    capabilities: AdapterCapabilities

    def collect_context(self) -> Sequence[ConversationMessage]:
        """Collect the host's current or pending context."""

    def inspect(self, messages: Sequence[ConversationMessage]) -> InspectionResult:
        """Run the shared Context Guardian inspection pipeline."""

    def review(self, candidates: Sequence[MemoryCandidate]) -> Sequence[ReviewDecision]:
        """Resolve uncertain candidates through the host's review surface."""

    def preserve(
        self,
        candidates: Sequence[MemoryCandidate],
        decisions: Sequence[ReviewDecision],
    ) -> CompactionGuidance | ContextCheckpoint:
        """Inject native guidance or persist an assisted checkpoint."""
