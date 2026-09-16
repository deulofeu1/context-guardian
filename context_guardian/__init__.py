"""Public Python API for Context Guardian."""

from .adapters import AdapterCapabilities, ContextGuardianAdapter, IntegrationLevel
from .audit import (
    AuditInput,
    AuditInputBuilder,
    detect_user_language,
    is_execution_noise,
    validate_review_plan,
)
from .checkpoint import build_checkpoint
from .guidance import build_guidance, build_revision_guidance
from .inspector import ContextGuardian, RuleBasedInspector
from .models import (
    AuditDisposition,
    AuditFinding,
    AuditIssueType,
    AuditTopic,
    CandidateCategory,
    CompactionGuidance,
    ContextCheckpoint,
    ConversationMessage,
    InspectionResult,
    MemoryCandidate,
    MessageProvenance,
    MessageSourceKind,
    PreviewFinalization,
    ReviewAction,
    ReviewDecision,
    ReviewedFact,
    ReviewedFactsAppendix,
    ReviewOption,
    ReviewPlan,
    ReviewQuestion,
)
from .policy import ReviewPolicy
from .providers import HostModelProvider, ModelProvider, OpenAIProvider
from .reviewed_facts import (
    END_MARKER,
    START_MARKER,
    append_reviewed_facts,
    build_reviewed_facts,
    finalize_preview,
)
from .verification import verify_conversation, verify_file

__version__ = "0.3.3"

__all__ = [
    "CandidateCategory",
    "AuditDisposition",
    "AuditFinding",
    "AuditInput",
    "AuditInputBuilder",
    "AuditIssueType",
    "AuditTopic",
    "ContextGuardian",
    "ConversationMessage",
    "MessageProvenance",
    "MessageSourceKind",
    "CompactionGuidance",
    "ContextCheckpoint",
    "HostModelProvider",
    "InspectionResult",
    "MemoryCandidate",
    "ModelProvider",
    "OpenAIProvider",
    "ReviewAction",
    "ReviewDecision",
    "ReviewOption",
    "ReviewPlan",
    "ReviewQuestion",
    "ReviewedFact",
    "ReviewedFactsAppendix",
    "PreviewFinalization",
    "ReviewPolicy",
    "RuleBasedInspector",
    "build_guidance",
    "build_revision_guidance",
    "build_reviewed_facts",
    "append_reviewed_facts",
    "finalize_preview",
    "START_MARKER",
    "END_MARKER",
    "build_checkpoint",
    "detect_user_language",
    "is_execution_noise",
    "validate_review_plan",
    "AdapterCapabilities",
    "ContextGuardianAdapter",
    "IntegrationLevel",
    "verify_conversation",
    "verify_file",
    "__version__",
]
