"""Public Python API for Context Guardian."""

from .guidance import build_guidance
from .inspector import ContextGuardian, RuleBasedInspector
from .models import (
    CandidateCategory,
    CompactionGuidance,
    ConversationMessage,
    InspectionResult,
    MemoryCandidate,
    ReviewAction,
    ReviewDecision,
)
from .policy import ReviewPolicy
from .providers import HostModelProvider, ModelProvider, OpenAIProvider
from .verification import verify_conversation, verify_file

__version__ = "0.1.0"

__all__ = [
    "CandidateCategory",
    "ContextGuardian",
    "ConversationMessage",
    "CompactionGuidance",
    "HostModelProvider",
    "InspectionResult",
    "MemoryCandidate",
    "ModelProvider",
    "OpenAIProvider",
    "ReviewAction",
    "ReviewDecision",
    "ReviewPolicy",
    "RuleBasedInspector",
    "build_guidance",
    "verify_conversation",
    "verify_file",
    "__version__",
]
