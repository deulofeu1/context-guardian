"""Deterministic source provenance and evidence grounding helpers.

Provider output is untrusted.  This module is the boundary that decides which
host messages may support an audit finding or a durable Reviewed Fact.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from .models import ConversationMessage, MessageProvenance, MessageSourceKind

_COMMAND = re.compile(
    r"^\s*(?:[$>]\s*|PS\s*>\s*|"
    r"(?:npm|pnpm|yarn|pip|uv)\s+(?:install|update|add|remove|ci|run|publish|audit|test)\b|"
    r"(?:grep|rg|find|ls|pwd|cat|head|tail)\s+(?:[-/]|[A-Za-z0-9_.]))",
    re.I,
)
_COMMAND_INLINE = re.compile(
    r"\b(?:npm|pnpm|yarn|pip|uv)\s+(?:install|update|add|remove|ci|run|publish|audit)\b|"
    r"\b(?:grep|rg|find|ls|pwd|cat|head|tail)\s+(?:[-/]|[A-Za-z0-9_.])",
    re.I,
)
_LOG = re.compile(r"^\s*(?:traceback|error:|warning:|npm\s+(?:warn|notice|error)|debug:)\b", re.I)
_LOG_INLINE = re.compile(r"\b(?:traceback|npm\s+(?:warn|notice|error)|debug:)\b", re.I)
_MACHINE_PAYLOAD = re.compile(
    r"^\s*[\[{].*[\]}]\s*$|\"(?:id|type|arguments|payload|request_id|metadata)\"\s*:",
    re.I | re.S,
)
_ATTACHMENT_METADATA = re.compile(
    r"(?:image|attachment|document|file)\s+(?:metadata|probe|inspection|解包|探测)|"
    r"(?:mime[- ]type|dimensions?|解包结果|图片元数据|附件元数据)",
    re.I,
)
_PATH_OR_HASH = re.compile(
    r"(?:^|\s)(?:[A-Za-z]:\\|/(?:Users|private|tmp|var|home)/|\.\.?/)[^\s]*|\b[a-f0-9]{32,}\b",
    re.I,
)
_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.I,
)
_PERMISSION = re.compile(
    r"operations that require approval may ask through the configured answers|"
    r"capabilit(?:y|ies) (?:are|is) (?:not )?available",
    re.I,
)
_INTERNAL_PLANNING = re.compile(
    r"(?:task[_ -]?plan|findings|progress)\.md|"
    r"(?:creates?|created|writing|written|updates?|updated|maintains?)\b[^\n]{0,160}"
    r"(?:task[_ -]?plan|findings|progress)\.md",
    re.I,
)
_DURABLE = re.compile(
    r"\b(?:goal|objective|must|required|constraint|requirement|decision|decided|chosen|selected|"
    r"final|todo|unfinished|incomplete|still need|abandoned|rejected|failed|because|due to|"
    r"caused|concurrency|并发|"
    r"目标|必须|约束|要求|决定|最终|待办|未完成|放弃|失败|因为|由于|导致|改用)\b",
    re.I,
)


def normalize_evidence_text(value: object) -> str:
    """Normalize Unicode and whitespace for exact source-grounding checks."""

    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


def is_execution_noise(content: str) -> bool:
    """Return whether text is mechanical execution or internal metadata."""

    value = str(content or "").strip()
    if not value:
        return True
    if (
        _COMMAND.search(value)
        or _COMMAND_INLINE.search(value)
        or _LOG.search(value)
        or _LOG_INLINE.search(value)
        or _PERMISSION.search(value)
        or _MACHINE_PAYLOAD.search(value)
        or _ATTACHMENT_METADATA.search(value)
        or _UUID.search(value)
    ):
        return True
    # Issue #9's exact false-positive text is planning metadata, not document
    # content.  Keep this guard deterministic even if a provider repeats it.
    if _INTERNAL_PLANNING.search(value):
        return True
    if _PATH_OR_HASH.search(value) and not _DURABLE.search(value):
        return True
    return False


def is_durable_tool_result(message: ConversationMessage) -> bool:
    """Allow tool results only when they express a durable, understandable fact."""

    if is_execution_noise(message.content):
        return False
    return bool(_DURABLE.search(message.content))


def is_blocked_provenance(provenance: MessageProvenance) -> bool:
    return any(
        (
            provenance.system,
            provenance.developer,
            provenance.plugin_internal,
            provenance.planning,
            provenance.compaction_metadata,
            provenance.bookkeeping,
            provenance.tool_call,
        )
    )


def is_source_allowed(message: ConversationMessage) -> bool:
    """Return whether a message may supply evidence for durable memory."""

    provenance = message.provenance
    if is_blocked_provenance(provenance):
        return False
    if provenance.source_kind in {
        MessageSourceKind.USER_AUTHORED,
        MessageSourceKind.ASSISTANT_RESPONSE,
        MessageSourceKind.ATTACHMENT_CONTENT,
        MessageSourceKind.DURABLE_TOOL_RESULT,
    }:
        # User/assistant messages may contain a command alongside a real
        # sentence.  Evidence snippets still reject mechanical text; the
        # whole message must remain available for mixed natural-language turns.
        return True
    if provenance.source_kind is MessageSourceKind.TOOL_RESULT:
        return is_durable_tool_result(message)
    if provenance.source_kind is MessageSourceKind.EXECUTION_NOISE:
        return False
    # Unknown non-user sources are intentionally fail-closed.
    return False


def normalize_messages(messages: Iterable[ConversationMessage | dict]) -> list[ConversationMessage]:
    """Normalize and assign deterministic IDs without trusting host metadata."""

    result: list[ConversationMessage] = []
    for index, raw in enumerate(messages):
        message = ConversationMessage.model_validate(raw)
        if not message.id:
            message = message.model_copy(update={"id": f"message_{index + 1:04d}"})
        result.append(message)
    return result


@dataclass(frozen=True)
class SourceIndex:
    """The exact request-local message set allowed for provider grounding."""

    messages: dict[str, ConversationMessage]
    duplicate_ids: frozenset[str]

    @classmethod
    def from_messages(cls, messages: Iterable[ConversationMessage | dict]) -> SourceIndex:
        entries: dict[str, ConversationMessage] = {}
        duplicates: set[str] = set()
        for message in normalize_messages(messages):
            assert message.id is not None
            if message.id in entries:
                duplicates.add(message.id)
            else:
                entries[message.id] = message
        return cls(messages=entries, duplicate_ids=frozenset(duplicates))

    def allowed(self, message_id: str) -> ConversationMessage | None:
        if message_id in self.duplicate_ids:
            return None
        message = self.messages.get(message_id)
        return message if message is not None and is_source_allowed(message) else None

    def eligible_messages(self) -> list[ConversationMessage]:
        return [
            message
            for message_id, message in self.messages.items()
            if message_id not in self.duplicate_ids and is_source_allowed(message)
        ]


def evidence_matches_source(
    source_message_ids: Iterable[str],
    evidence_snippets: Iterable[str],
    source_index: SourceIndex,
) -> bool:
    """Validate all referenced IDs and every evidence snippet against source text."""

    ids = [str(item) for item in source_message_ids if str(item)]
    snippets = [str(item) for item in evidence_snippets if str(item).strip()]
    if not ids or not snippets or len(ids) != len(set(ids)):
        return False
    sources = [source_index.allowed(message_id) for message_id in ids]
    if any(source is None for source in sources):
        return False
    normalized_sources = [normalize_evidence_text(source.content) for source in sources if source is not None]
    for snippet in snippets:
        if is_execution_noise(snippet):
            return False
        normalized = normalize_evidence_text(snippet)
        if not normalized or not any(normalized in source for source in normalized_sources):
            return False
    return True
