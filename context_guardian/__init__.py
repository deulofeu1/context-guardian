"""Public Python API for Context Guardian."""

from .adapters import AdapterCapabilities, ContextGuardianAdapter, IntegrationLevel
from .checkpoint import build_checkpoint
from .guidance import build_guidance
from .inspector import ContextGuardian, RuleBasedInspector
from .models import (
    CandidateCategory,
    CompactionGuidance,
    ContextCheckpoint,
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
    "ContextCheckpoint",
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
    "build_checkpoint",
    "AdapterCapabilities",
    "ContextGuardianAdapter",
    "IntegrationLevel",
    "verify_conversation",
    "verify_file",
    "__version__",
]
