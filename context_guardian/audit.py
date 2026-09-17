"""Native-preview auditing and bounded semantic review planning.

The audit layer does not produce the final compaction summary. It compares a
host-produced preview with source-backed signals and returns only corrections
or genuinely ambiguous topics for the host UI.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable

from pydantic import BaseModel, Field

from .models import (
    AuditCoverage,
    AuditDisposition,
    AuditFinding,
    AuditIssueType,
    AuditOperation,
    AuditTaskRelation,
    AuditTopic,
    CandidateCategory,
    ConversationMessage,
    MemoryCandidate,
    ReviewAction,
    ReviewOption,
    ReviewPlan,
    ReviewQuestion,
)
from .policy import ReviewPolicy
from .provenance import (
    SourceIndex,
    evidence_matches_source,
    is_execution_noise,
    is_source_allowed,
    normalize_evidence_text,
    normalize_messages,
)

MAX_AUDIT_FINDINGS = 20
MAX_AUDIT_TOPICS = 10
DEFAULT_AUDIT_INPUT_CHARS = 48_000

_COMPLETION = re.compile(r"\b(?:completed|complete|finished|resolved)\b|已完成|完成|已解决", re.I)
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{2,}|[\u4e00-\u9fff]+", re.I)
_LATIN_WORD = re.compile(r"\b[A-Za-z][A-Za-z0-9_'-]*\b")
_UNRESOLVED_STATUS = re.compile(
    r"\b(?:incomplete|unfinished|unresolved|not\s+(?:verified|tested|done|complete)|"
    r"did\s+not\s+appear|has\s+not\s+appeared)\b"
    r"|未完成|尚未完成|未解决|未验证|未测试|未弹窗|没有弹窗|尚未|仍未|还没",
    re.I,
)


class AuditInput(BaseModel):
    """Bounded, complete-message input prepared for a provider audit."""

    text: str
    message_ids: list[str] = Field(default_factory=list)
    source_message_ids: list[str] = Field(default_factory=list)
    omitted_message_ids: list[str] = Field(default_factory=list)
    truncated: bool = False
    source_messages: list[ConversationMessage] = Field(default_factory=list, exclude=True)


def detect_user_language(messages: Iterable[ConversationMessage | dict]) -> str:
    """Detect language from user-authored messages only.

    Count Chinese characters but Latin words so technical identifiers and
    product names do not drown out the language of a Chinese sentence.
    """

    normalized = [ConversationMessage.model_validate(message) for message in messages]
    user_text = " ".join(
        message.content
        for message in normalized
        if message.provenance.user_authored
    )
    chinese = len(re.findall(r"[\u4e00-\u9fff]", user_text))
    latin = len(_LATIN_WORD.findall(user_text))
    return "zh-CN" if chinese > latin else "en"


class AuditInputBuilder:
    """Build provider input without cutting through a conversation message."""

    def __init__(self, max_chars: int = DEFAULT_AUDIT_INPUT_CHARS):
        self.max_chars = max(4_000, int(max_chars))

    @staticmethod
    def _message_id(message: ConversationMessage, index: int) -> str:
        return message.id or f"message_{index + 1:04d}"

    @staticmethod
    def _message_priority(message: ConversationMessage) -> int:
        if message.provenance.attachment_content:
            return 3
        if message.provenance.user_authored or message.role == "user":
            return 4
        if message.provenance.tool_result or message.role in {
            "tool", "toolResult", "tool_result", "bashExecution"
        }:
            return 2 if is_source_allowed(message) else 0
        return 1

    @staticmethod
    def _complete_field(label: str, value: str, limit: int) -> str:
        if not value:
            return ""
        value = str(value)
        if len(value) <= limit:
            return f"{label}:\n{value}"
        # Keep complete lines only. A very long single line is omitted rather than
        # silently passing a misleading mid-message fragment to a model.
        lines = value.splitlines()
        kept: list[str] = []
        used = len(label) + 2
        for line in lines:
            candidate = used + len(line) + 1
            if candidate > limit:
                break
            kept.append(line)
            used = candidate
        return f"{label}:\n" + "\n".join(kept) if kept else ""

    def select_messages(
        self, messages: Iterable[ConversationMessage | dict]
    ) -> tuple[list[ConversationMessage], bool]:
        normalized = [
            message.model_copy(update={"id": message.id or f"message_{index + 1:04d}"})
            for index, message in enumerate(normalize_messages(messages))
        ]
        eligible = [message for message in normalized if is_source_allowed(message)]
        ranked = sorted(
            enumerate(eligible),
            key=lambda item: (-self._message_priority(item[1]), item[0]),
        )
        selected: set[int] = set()
        used = 0
        for index, message in ranked:
            block_cost = len(message.content) + 32
            if used + block_cost > self.max_chars:
                continue
            selected.add(index)
            used += block_cost
        result = [message for index, message in enumerate(eligible) if index in selected]
        return result, len(result) != len(eligible) or len(eligible) != len(normalized)

    def build(
        self,
        messages: Iterable[ConversationMessage | dict],
        *,
        preview: str,
        previous_summary: str = "",
        retained_context: str = "",
        language: str | None = None,
    ) -> AuditInput:
        normalized = [
            message.model_copy(update={"id": message.id or f"message_{index + 1:04d}"})
            for index, message in enumerate(normalize_messages(messages))
        ]
        selected, truncated = self.select_messages(normalized)
        fixed = [
            self._complete_field("NATIVE PREVIEW", preview, self.max_chars // 2),
            self._complete_field("PREVIOUS SUMMARY", previous_summary, self.max_chars // 6),
            self._complete_field("RETAINED CONTEXT", retained_context, self.max_chars // 6),
            f"USER LANGUAGE: {language or detect_user_language(normalized)}",
        ]
        fixed_text = "\n\n".join(item for item in fixed if item)
        available = max(1_000, self.max_chars - len(fixed_text) - 80)
        source_blocks: list[str] = []
        used = 0
        selected_ids: list[str] = []
        source_ids = [self._message_id(message, index) for index, message in enumerate(selected)]
        omitted_ids: list[str] = []
        included_messages: list[ConversationMessage] = []
        for index, message in enumerate(selected):
            message_id = self._message_id(message, index)
            block = f"[{message.role} id={message_id}]\n{message.content}"
            if used + len(block) + 2 > available:
                truncated = True
                omitted_ids.append(message_id)
                continue
            source_blocks.append(block)
            selected_ids.append(message_id)
            included_messages.append(message)
            used += len(block) + 2
        text = fixed_text + "\n\nORIGINAL SOURCE SIGNALS:\n" + "\n\n".join(source_blocks)
        return AuditInput(
            text=text,
            message_ids=selected_ids,
            source_message_ids=source_ids,
            omitted_message_ids=omitted_ids,
            truncated=truncated or bool(omitted_ids),
            source_messages=included_messages,
        )

    def build_chunks(
        self,
        messages: Iterable[ConversationMessage | dict],
        *,
        preview: str,
        previous_summary: str = "",
        retained_context: str = "",
        language: str | None = None,
    ) -> list[AuditInput]:
        """Partition source messages at message boundaries for large audits."""
        normalized = [
            message.model_copy(update={"id": message.id or f"message_{index + 1:04d}"})
            for index, message in enumerate(normalize_messages(messages))
        ]
        normalized = [message for message in normalized if is_source_allowed(message)]
        if not normalized:
            return [
                self.build(
                    [],
                    preview=preview,
                    previous_summary=previous_summary,
                    retained_context=retained_context,
                    language=language,
                )
            ]
        chunks: list[list[ConversationMessage]] = []
        current: list[ConversationMessage] = []
        current_cost = 0
        for message in normalized:
            cost = len(message.content) + 32
            if current and current_cost + cost > self.max_chars // 2:
                chunks.append(current)
                current = []
                current_cost = 0
            if cost <= self.max_chars // 2:
                current.append(message)
                current_cost += cost
            else:
                # Keep an explicit one-message chunk so callers can report
                # incomplete coverage instead of silently dropping long input.
                if current:
                    chunks.append(current)
                    current = []
                    current_cost = 0
                chunks.append([message])
        if current:
            chunks.append(current)
        return [
            self.build(
                chunk,
                preview=preview,
                previous_summary=previous_summary,
                retained_context=retained_context,
                language=language,
            )
            for chunk in chunks
        ]


class AuditModelOutput(BaseModel):
    """Small schema used when a host model is asked to audit a preview."""

    model_config = {"extra": "forbid"}

    findings: list[AuditFinding] = Field(default_factory=list, max_length=MAX_AUDIT_FINDINGS)
    audit_topics: list[AuditTopic] = Field(default_factory=list, max_length=MAX_AUDIT_TOPICS)
    auto_corrections: list[str] = Field(default_factory=list, max_length=MAX_AUDIT_FINDINGS)
    accepted_omissions: list[str] = Field(default_factory=list, max_length=MAX_AUDIT_FINDINGS)
    review_questions: list[ReviewQuestion] = Field(default_factory=list, max_length=3)


def _tokens(text: str) -> set[str]:
    result: set[str] = set()
    for token in _TOKEN.findall(text.casefold()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            result.update(token[index : index + 2] for index in range(max(0, len(token) - 1)))
        else:
            result.add(token.rstrip(".,;:!?)]}"))
    return {
        token
        for token in result
        if token
        not in {
            "about",
            "after",
            "also",
            "and",
            "asked",
            "been",
            "because",
            "could",
            "current",
            "for",
            "from",
            "have",
            "into",
            "is",
            "me",
            "more",
            "only",
            "please",
            "should",
            "that",
            "the",
            "this",
            "through",
            "with",
            "what",
        }
    }


def _present_in_preview(
    content: str,
    searchable: str,
    category: CandidateCategory | None = None,
) -> bool:
    source = _tokens(content)
    preview = _tokens(searchable)
    if not source:
        return True
    overlap = len(source & preview)
    lower_content = content.casefold()
    lower_preview = searchable.casefold()
    if (
        category is CandidateCategory.DECISION
        and "stop using" in lower_content
        and "abandon" in lower_preview
    ):
        return bool({token for token in source if len(token) >= 6} & preview)
    if category is CandidateCategory.DECISION and any(
        word in lower_preview for word in ("selected", "chosen", "final", "采用", "最终")
    ):
        return bool({token for token in source if len(token) >= 6} & preview)
    if len(source) <= 2:
        distinctive = {token for token in source if "." in token or len(token) >= 6}
        return overlap >= 1 or bool(distinctive & preview)
    return overlap >= 2


def _contradicts(content: str, preview: str) -> bool:
    lower_content = content.casefold()
    lower_preview = preview.casefold()
    if any(word in lower_content for word in ("abandoned", "rejected", "放弃", "弃用")):
        technologies = [token for token in _tokens(content) if token in lower_preview]
        return bool(technologies) and any(
            word in lower_preview for word in ("final", "selected", "chosen", "最终", "采用")
        )
    if any(
        word in lower_content
        for word in (
            "incomplete",
            "unfinished",
            "未完成",
            "待办",
            "not verified",
            "unverified",
            "not tested",
            "did not appear",
            "didn't appear",
            "未验证",
            "未测试",
            "未弹窗",
            "没有弹窗",
            "尚未",
            "还没",
            "仍未",
            "停在",
        )
    ):
        return _COMPLETION.search(lower_preview) is not None
    return False


def _strong_durable(candidate: MemoryCandidate) -> bool:
    durable_categories = {
            CandidateCategory.GOAL,
            CandidateCategory.REQUIREMENT,
            CandidateCategory.CONSTRAINT,
            CandidateCategory.DECISION,
            CandidateCategory.TODO,
            CandidateCategory.WORKING_STATE,
            CandidateCategory.FAILED_ATTEMPT,
            CandidateCategory.USER_PREFERENCE,
        }
    if candidate.category not in durable_categories:
        return False
    # Failure rationales are often reported by tools and therefore have lower
    # classifier confidence, but remain important when explicitly stated.
    threshold = (0.65, 0.55) if candidate.category is CandidateCategory.FAILED_ATTEMPT else (0.7, 0.7)
    return candidate.importance >= threshold[0] and candidate.confidence >= threshold[1]


def _short(content: str, limit: int = 220) -> str:
    return re.sub(r"\s+", " ", content).strip()[:limit]


def _source_context(source: str, evidence: str, *, limit: int = 500) -> str:
    """Return a complete source sentence or bounded source context.

    Providers often cite the most distinctive phrase in a message. That
    phrase is not a suitable durable fact by itself, so expand it to the
    sentence or source line that contains it while keeping the result
    source-exact.
    """

    normalized_source = re.sub(r"\s+", " ", str(source or "")).strip()
    normalized_evidence = normalize_evidence_text(evidence)
    if not normalized_source or not normalized_evidence:
        return ""
    if normalized_evidence not in normalize_evidence_text(normalized_source):
        return ""

    segments = [
        segment.strip()
        for segment in re.split(r"(?<=[.!?。！？])\s+|\n+", normalized_source)
        if segment.strip()
    ]
    matching = [
        segment
        for segment in segments
        if normalized_evidence in normalize_evidence_text(segment)
    ]
    for segment in matching:
        if not is_execution_noise(segment):
            return segment[:limit].rstrip()

    # If the source has no sentence boundary, retain the whole source when it
    # is reasonably sized. This remains safer than a provider paraphrase or a
    # mid-sentence evidence slice.
    if len(normalized_source) <= limit and not is_execution_noise(normalized_source):
        return normalized_source
    return ""


def _grounded_source_fact(finding: AuditFinding, source_index: SourceIndex) -> str:
    """Find a readable, source-exact fact for a validated provider finding."""

    for message_id in finding.source_message_ids:
        source = source_index.allowed(message_id)
        if source is None:
            continue
        for evidence in finding.evidence_snippets:
            context = _source_context(source.content, evidence)
            if context:
                return context
    return ""


def _display_summary(finding: AuditFinding, source_fact: str) -> str:
    """Choose readable provider text without making it durable authority."""

    candidate = _short(finding.display_summary or "", 500)
    if candidate and not is_execution_noise(candidate):
        return candidate
    return source_fact


def _topic_key(content: str, category: CandidateCategory) -> str:
    lower = content.casefold()
    if category is CandidateCategory.WORKING_STATE and _looks_like_verification_status(content):
        return "verification-status"
    if any(word in lower for word in ("npm", "pip", "python", "node", "package")):
        return "tooling"
    if category in {CandidateCategory.GOAL, CandidateCategory.CONSTRAINT, CandidateCategory.DECISION}:
        return "project-direction"
    # Keep unrelated ambiguous user topics separate while allowing repeated
    # sentences from the same topic to cluster through their stable signal words.
    tokens = sorted(_tokens(content))[:2]
    return f"side-discussion:{'-'.join(tokens) or 'other'}"


def _localized(language: str, zh: str, en: str) -> str:
    return zh if language == "zh-CN" else en


def preview_fingerprint(preview: str) -> str:
    """Return a stable request-local identity for a native preview."""

    return hashlib.sha256(str(preview).encode("utf-8")).hexdigest()


def _exact_target(preview: str, candidate: str) -> str | None:
    """Find one exact, complete target in the native preview.

    Rewriting is deliberately conservative.  A target must occur exactly once;
    token overlap or a fuzzy match is never enough to edit host output.
    """

    target = re.sub(r"\s+", " ", str(candidate or "")).strip()
    if not target:
        return None
    normalized_preview = re.sub(r"\s+", " ", str(preview or ""))
    occurrences = [match.start() for match in re.finditer(re.escape(target), normalized_preview)]
    return target if len(occurrences) == 1 else None


def _relation_for(category: CandidateCategory, content: str = "") -> AuditTaskRelation:
    if category in {
        CandidateCategory.GOAL,
        CandidateCategory.REQUIREMENT,
        CandidateCategory.CONSTRAINT,
        CandidateCategory.DECISION,
        CandidateCategory.TODO,
        CandidateCategory.WORKING_STATE,
        CandidateCategory.FAILED_ATTEMPT,
    }:
        return AuditTaskRelation.PRIMARY
    if category in {CandidateCategory.IMPORTANT_FACT, CandidateCategory.USER_PREFERENCE}:
        return AuditTaskRelation.RELATED
    if category in {CandidateCategory.TOOL_OUTPUT, CandidateCategory.TEMPORARY}:
        return AuditTaskRelation.BACKGROUND
    lower = content.casefold()
    return AuditTaskRelation.BACKGROUND if any(
        word in lower for word in ("npm", "pip", "shell", "command", "日志", "权限")
    ) else AuditTaskRelation.RELATED


def _looks_like_working_state(content: str) -> bool:
    """Recognize unresolved status language even if a provider mislabels it."""

    return bool(_UNRESOLVED_STATUS.search(str(content)))


def _looks_like_verification_status(content: str) -> bool:
    """Recognize unresolved verification/test status that needs explicit review."""

    lower = str(content).casefold()
    return _looks_like_working_state(content) and any(
        marker in lower
        for marker in ("验证", "测试", "弹窗", "校验", "popup", "review", "verify", "test")
    )


def _finding_operation(
    issue_type: AuditIssueType,
    *,
    preview: str,
    source_fact: str,
) -> tuple[AuditOperation, str | None]:
    if issue_type in {AuditIssueType.INCORRECT, AuditIssueType.STALE}:
        target = _exact_target(preview, source_fact)
        # The source fact itself is normally absent for an incorrect finding.
        # Callers may provide a provider-supplied current target separately.
        return (AuditOperation.REPLACE if target else AuditOperation.KEEP_PREVIEW, target)
    return AuditOperation.ADD, None


def _contradictory_preview_target(content: str, preview: str) -> str | None:
    """Locate the complete preview sentence that conflicts with source state."""

    source_tokens = {
        token
        for token in _tokens(content)
        if len(token) >= 4 or re.search(r"[\u4e00-\u9fff]", token)
    }
    segments = [
        segment.strip()
        for segment in re.split(r"(?<=[.!?。！？])\s+|\n+", preview)
        if segment.strip()
    ]
    for segment in segments:
        segment_tokens = _tokens(segment)
        shares_signal = bool(source_tokens.intersection(segment_tokens))
        if _looks_like_working_state(content):
            # Chinese status phrases are often tokenized as different long
            # runs (e.g. “当前验证状态” vs “验证与最终校验”). Keep the
            # deterministic conflict check conservative but allow shared
            # status signals to bridge those word-boundary differences.
            shares_signal = shares_signal or any(
                marker in segment
                for marker in ("验证", "测试", "弹窗", "校验", "原生", "test", "verify")
                if marker in content.casefold()
            )
        if not shares_signal:
            continue
        if _COMPLETION.search(segment) or any(
            word in segment.casefold()
            for word in ("selected", "chosen", "final", "采用", "最终", "已完成")
        ):
            return _exact_target(preview, segment)
    return None


class PreviewAuditor:
    """Compare a native preview to conservative source-derived memory signals."""

    def __init__(
        self,
        *,
        policy: ReviewPolicy,
        rule_inspector,
        provider=None,
        max_input_chars: int = DEFAULT_AUDIT_INPUT_CHARS,
    ):
        self.policy = policy
        self.rule_inspector = rule_inspector
        self.provider = provider
        self.input_builder = AuditInputBuilder(max_input_chars)

    def audit(
        self,
        messages: Iterable[ConversationMessage | dict],
        *,
        preview: str,
        previous_summary: str = "",
        retained_context: str = "",
        language: str | None = None,
        max_review_questions: int = 3,
    ) -> ReviewPlan:
        normalized = [ConversationMessage.model_validate(message) for message in messages]
        selected_language = language if language in {"zh-CN", "en"} else detect_user_language(normalized)
        audit_input = self.input_builder.build(
            normalized,
            preview=preview,
            previous_summary=previous_summary,
            retained_context=retained_context,
            language=selected_language,
        )
        if self.provider is not None:
            inputs = (
                self.input_builder.build_chunks(
                    normalized,
                    preview=preview,
                    previous_summary=previous_summary,
                    retained_context=retained_context,
                    language=selected_language,
                )
                if audit_input.truncated
                else [audit_input]
            )
            grounded_findings: list[AuditFinding] = []
            provider_review_finding_ids: set[str] = set()
            raw_provider_findings = 0
            provider_successes = 0
            failed_chunks = 0
            attempted_ids: set[str] = set()
            covered_ids: set[str] = set()
            diagnostics: list[str] = []
            accepted_omissions: list[str] = []
            provider_id_map: dict[str, str] = {}
            for item in inputs:
                attempted_ids.update(item.source_message_ids)
                covered_ids.update(item.message_ids)
                try:
                    provider_plan = self.provider.generate_structured(
                        self._provider_prompt(item.text, selected_language, max_review_questions),
                        ReviewPlan,
                    )
                except Exception as error:
                    failed_chunks += 1
                    diagnostics.append(
                        _localized(
                            selected_language,
                            f"宿主模型审计分块失败（{type(error).__name__}）：已对该分块降级到本地规则；先前成功结果仍保留。",
                            f"Host-model audit chunk failed ({type(error).__name__}); this chunk used local "
                            "rules "
                            "while earlier successful results were retained.",
                        )
                    )
                    local = self._local_audit(
                        item.source_messages,
                        preview=preview,
                        previous_summary=previous_summary,
                        retained_context=retained_context,
                        language=selected_language,
                        max_review_questions=max_review_questions,
                    )
                    grounded_findings.extend(local.findings)
                    accepted_omissions.extend(local.accepted_omissions)
                    continue
                provider_successes += 1
                raw_provider_findings += len(provider_plan.findings)
                source_index = SourceIndex.from_messages(item.source_messages)
                sanitized = self._sanitize_provider_findings(
                    provider_plan.findings,
                    source_index,
                    selected_language,
                    preview=preview,
                    provider_id_map=provider_id_map,
                )
                grounded_findings.extend(sanitized)
                accepted_omissions.extend(provider_plan.accepted_omissions)
                provider_review_finding_ids.update(
                    self._provider_review_finding_ids(
                        provider_plan,
                        {finding.id for finding in sanitized},
                        provider_id_map,
                    )
                )
            grounded_findings = self._deduplicate_findings(grounded_findings)
            # Provider classification is useful for breadth, but the source
            # itself remains authoritative for unresolved verification status.
            # Run the cheap deterministic guard as well so a model cannot
            # relabel a primary "not verified / popup did not appear" signal
            # as an unrelated side discussion or silently omit it.
            status_findings = [
                finding.model_copy(update={"requires_user_confirmation": True})
                for finding in self._source_status_findings(
                    normalized,
                    preview=preview,
                    language=selected_language,
                )
            ]
            for status_finding in status_findings:
                source_ids = set(status_finding.source_message_ids)
                grounded_findings = [
                    finding
                    for finding in grounded_findings
                    if not source_ids.intersection(finding.source_message_ids)
                ]
                grounded_findings.append(status_finding)
            grounded_findings = self._deduplicate_findings(grounded_findings)
            if provider_review_finding_ids:
                grounded_findings = [
                    finding.model_copy(update={"requires_user_confirmation": True})
                    if finding.id in provider_review_finding_ids
                    else finding
                    for finding in grounded_findings
                ]
            if raw_provider_findings and not grounded_findings and not failed_chunks:
                diagnostics.append(
                    _localized(
                        selected_language,
                        f"宿主模型审计诊断：raw={raw_provider_findings} kept=0 reason=evidence_not_verbatim。"
                        "没有一条结果通过逐字来源证据校验，因此未显示 Review 问题，也未追加未经验证的事实。",
                        f"Host audit diagnostic: raw={raw_provider_findings} kept=0 "
                        "reason=evidence_not_verbatim. No finding passed verbatim source-evidence "
                        "validation, so no Review question or ungrounded fact was added.",
                    )
                )
            coverage = AuditCoverage(
                total_source_messages=len({
                    message.id or f"message_{index + 1:04d}"
                    for index, message in enumerate(normalized)
                    if is_source_allowed(message)
                }),
                attempted_source_messages=len(attempted_ids),
                covered_source_messages=len(covered_ids),
                failed_chunks=failed_chunks,
                chunks=len(inputs),
                complete=(
                    failed_chunks == 0
                    and len(covered_ids) >= len({
                        message.id or f"message_{index + 1:04d}"
                        for index, message in enumerate(normalized)
                        if is_source_allowed(message)
                    })
                    and all(not item.omitted_message_ids for item in inputs)
                ),
            )
            if not coverage.complete:
                diagnostics.append(
                    _localized(
                        selected_language,
                        f"审计覆盖不完整：{coverage.covered_source_messages}/"
                        f"{coverage.total_source_messages} 条来源消息进入模型输入。",
                        f"Audit coverage is incomplete: {coverage.covered_source_messages}/"
                        f"{coverage.total_source_messages} source messages reached the host model.",
                    )
                )
            return self._build_grounded_plan(
                grounded_findings,
                selected_language,
                max_review_questions,
                diagnostics=diagnostics,
                accepted_omissions=accepted_omissions,
                coverage=coverage,
                preview=preview,
                audit_status=(
                    "model_failed" if failed_chunks and provider_successes == 0
                    else "incomplete" if failed_chunks or not coverage.complete
                    else "source_rejected" if raw_provider_findings and not grounded_findings
                    else "success"
                ),
                degraded=bool(failed_chunks or not coverage.complete),
            )
        return self._local_audit(
            normalized,
            preview=preview,
            previous_summary=previous_summary,
            retained_context=retained_context,
            language=selected_language,
            max_review_questions=max_review_questions,
        )

    def _source_status_findings(
        self,
        messages: list[ConversationMessage],
        *,
        preview: str,
        language: str,
    ) -> list[AuditFinding]:
        """Create a deterministic finding for unresolved verification status.

        This guard intentionally does not depend on either the provider's
        category or the rule inspector's phrase ranking.  Host models have
        repeatedly described this exact source signal as an unrelated side
        topic, which can hide a primary-task correction from the user.
        """

        findings: list[AuditFinding] = []
        for index, message in enumerate(messages):
            if not is_source_allowed(message) or not _looks_like_verification_status(message.content):
                continue
            source_id = message.id or f"message_{index + 1:04d}"
            candidate = MemoryCandidate(
                id=f"status_{hashlib.sha1(f'{source_id}|{message.content}'.encode()).hexdigest()[:12]}",
                content=message.content,
                category=CandidateCategory.WORKING_STATE,
                importance=0.95,
                confidence=0.95,
                suggested_action=ReviewAction.KEEP,
                source_message_ids=[source_id],
            )
            target = _contradictory_preview_target(message.content, preview)
            finding = self._finding(
                candidate,
                AuditIssueType.INCORRECT if target else AuditIssueType.MISSING,
                language,
                preview,
            )
            findings.append(finding.model_copy(update={"requires_user_confirmation": True}))
        return findings

    @staticmethod
    def _deduplicate_findings(findings: Iterable[AuditFinding]) -> list[AuditFinding]:
        result: list[AuditFinding] = []
        seen: set[tuple[str, str, tuple[str, ...]]] = set()
        ordered = sorted(
            findings,
            key=lambda finding: (
                -finding.importance,
                -finding.confidence,
                finding.category.value,
                finding.id,
            ),
        )
        for finding in ordered:
            key = (
                finding.category.value,
                finding.summary.casefold(),
                tuple(sorted(finding.source_message_ids)),
            )
            if key in seen:
                continue
            seen.add(key)
            if len(result) >= MAX_AUDIT_FINDINGS:
                break
            result.append(finding)
        return result

    def _sanitize_provider_findings(
        self,
        findings: Iterable[AuditFinding],
        source_index: SourceIndex,
        language: str,
        *,
        preview: str = "",
        provider_id_map: dict[str, str] | None = None,
    ) -> list[AuditFinding]:
        """Accept only findings grounded in this request's real source messages."""

        sanitized: list[AuditFinding] = []
        for finding in findings:
            if not evidence_matches_source(
                finding.source_message_ids,
                finding.evidence_snippets,
                source_index,
            ):
                continue
            source_fact = _grounded_source_fact(finding, source_index)
            if not source_fact:
                continue
            status_signal = _looks_like_working_state(source_fact)
            display_summary = _display_summary(finding, source_fact)
            why = _localized(
                language,
                "这条来源明确的项目状态可能影响后续实现。",
                "This explicit source-backed project state may affect future implementation.",
            )
            stable_id = "finding_" + hashlib.sha1(
                "|".join(
                    [
                        finding.category.value,
                        source_fact,
                        ",".join(sorted(finding.source_message_ids)),
                    ]
                ).encode()
            ).hexdigest()[:12]
            if provider_id_map is not None:
                provider_id_map[finding.id] = stable_id
            current_target = _exact_target(preview, finding.current_summary_text or "")
            if current_target is None and status_signal:
                current_target = _contradictory_preview_target(source_fact, preview)
            issue_type = finding.issue_type
            if status_signal and current_target and issue_type in {
                AuditIssueType.MISSING,
                AuditIssueType.AMBIGUOUS,
            }:
                issue_type = AuditIssueType.INCORRECT
            if issue_type in {AuditIssueType.INCORRECT, AuditIssueType.STALE}:
                operation = AuditOperation.REPLACE if current_target else AuditOperation.KEEP_PREVIEW
            else:
                operation = AuditOperation.ADD
            # A source-backed replacement of the primary task state must never
            # disappear into a silent auto-correction. The host model may omit
            # `requires_user_confirmation` even when it correctly detects the
            # conflict; the deterministic safety rule keeps the before/after
            # decision visible in the host UI.
            requires_confirmation = finding.requires_user_confirmation or (
                operation == AuditOperation.REPLACE
                and (
                    status_signal
                    or finding.category is CandidateCategory.WORKING_STATE
                    or finding.task_relation is AuditTaskRelation.PRIMARY
                )
            )
            sanitized.append(
                finding.model_copy(
                    update={
                        "id": stable_id,
                        "issue_type": issue_type,
                        "category": CandidateCategory.WORKING_STATE if status_signal else finding.category,
                        "summary": display_summary,
                        "display_summary": display_summary,
                        "why_it_matters": why,
                        # Never write an arbitrary provider correction. The
                        # accepted correction is complete source context that
                        # contains the validated evidence, not the raw phrase
                        # the provider happened to cite.
                        "suggested_correction": source_fact,
                        "evidence_snippets": [source_fact],
                        "task_relation": (
                            AuditTaskRelation.PRIMARY
                            if status_signal
                            else finding.task_relation
                            if finding.task_relation != AuditTaskRelation.RELATED
                            else _relation_for(finding.category, source_fact)
                        ),
                        "operation": operation,
                        "requires_user_confirmation": requires_confirmation,
                        "current_summary_text": current_target,
                        "proposed_text": source_fact,
                    }
                )
            )
        return sanitized

    @staticmethod
    def _provider_review_finding_ids(
        provider_plan: ReviewPlan,
        accepted_finding_ids: set[str],
        provider_id_map: dict[str, str] | None = None,
    ) -> set[str]:
        """Resolve provider review requests to source-validated findings.

        Provider question text is untrusted and is not copied into the UI. A
        question is honored only when its topic (or direct finding reference)
        points at a finding that passed request-local source validation.
        """

        topics = {topic.id: topic for topic in provider_plan.audit_topics}
        requested: set[str] = set()
        for topic in provider_plan.audit_topics:
            if topic.disposition is AuditDisposition.ASK_USER:
                requested.update(topic.finding_ids)
        for question in provider_plan.review_questions:
            topic = topics.get(question.topic_id)
            if topic is not None:
                requested.update(topic.finding_ids)
            elif question.topic_id in accepted_finding_ids:
                requested.add(question.topic_id)
        mapped = {provider_id_map.get(item, item) for item in requested} if provider_id_map else requested
        return mapped & accepted_finding_ids

    def _build_grounded_plan(
        self,
        findings: list[AuditFinding],
        language: str,
        max_review_questions: int,
        *,
        diagnostics: Iterable[str] = (),
        accepted_omissions: Iterable[str] = (),
        coverage: AuditCoverage | None = None,
        audit_status: str = "success",
        degraded: bool = False,
        degradation_reason: str | None = None,
        preview: str = "",
    ) -> ReviewPlan:
        raw_topics = self._make_topics(findings, language)[:MAX_AUDIT_TOPICS]
        topics = self._apply_review_budget(
            raw_topics,
            max_review_questions,
        )
        questions = self._make_questions(topics, language, max_review_questions)
        topic_by_finding = {
            finding_id: topic
            for topic in topics
            for finding_id in topic.finding_ids
        }
        auto_corrections = _unique(
            finding.suggested_correction
            for finding in findings
            if topic_by_finding.get(finding.id) is not None
            and topic_by_finding[finding.id].disposition is AuditDisposition.AUTO_CORRECT
        )
        return ReviewPlan(
            language=language,
            overview=self._overview(language, len(auto_corrections), len(questions)),
            auto_preserve_summary=_localized(
                language,
                "明确的目标、约束、决定和未完成工作会自动审计并保留。",
                "Explicit goals, constraints, decisions, and unfinished work are audited "
                "and preserved automatically.",
            ),
            findings=findings,
            audit_topics=topics,
            auto_corrections=auto_corrections,
            accepted_omissions=_unique(accepted_omissions),
            review_questions=questions,
            diagnostics=_unique(diagnostics),
            audit_status=(
                "budget_exhausted"
                if max_review_questions == 0
                and any(topic.disposition is AuditDisposition.ASK_USER for topic in raw_topics)
                else "no_issues"
                if not findings and not questions and audit_status == "success"
                else audit_status
            ),
            degraded=degraded,
            degradation_reason=degradation_reason,
            coverage=coverage or AuditCoverage(),
            preview_fingerprint=preview_fingerprint(preview) if preview else None,
        )

    @staticmethod
    def _provider_prompt(text: str, language: str, max_questions: int) -> str:
        return f"""You are auditing a native compaction preview, not writing a replacement summary.
Compare the NATIVE PREVIEW with ORIGINAL SOURCE SIGNALS. Report only source-backed
missing, incorrect, stale, or ambiguous durable context. Goals, constraints, decisions,
rejected approaches with reasons, unfinished work, and user preferences matter most.
Treat commands, logs, paths, hashes, permissions, attachment metadata, and resolved
transient errors as accepted omissions. Never put those raw strings in review questions.
Group related findings into semantic topics. Ask at most {max_questions} questions and
ask only about uncertain topics that affect future work. Keep evidence to two concise
natural-language lines. `evidence_snippets` MUST be verbatim excerpts copied from the
original source message, in its original language; never translate or paraphrase them.
Put any readable translation or paraphrase in `display_summary` instead. `display_summary`
is UI-only and will never be written as an authoritative fact. Do not invent corrections.
The UI language is {language}.
Keep issue_type factual: it describes whether the preview is missing, incorrect, stale, or
ambiguous. Do not change it merely because a human must confirm the action. Instead set
requires_user_confirmation=true and use task_relation=primary|related|background. Use
operation=add for missing information, operation=replace for an exact current preview
sentence that is wrong, and operation=keep_preview when an exact safe replacement target
cannot be proven. For replace, current_summary_text MUST be an exact unique substring of
NATIVE PREVIEW. proposed_text must be source-backed. Include the finding IDs in the topic
and reference that topic from review_questions when confirmation is required.
The host will regenerate the visible question from validated source context.
Return the ReviewPlan schema exactly; auto_corrections must be incremental source-backed
corrections, not a complete summary.

{text}"""

    def _local_audit(
        self,
        messages: list[ConversationMessage],
        *,
        preview: str,
        previous_summary: str,
        retained_context: str,
        language: str,
        max_review_questions: int,
    ) -> ReviewPlan:
        candidates = self.rule_inspector.inspect(messages, self.policy)
        searchable = "\n".join((preview, previous_summary, retained_context))
        findings: list[AuditFinding] = []
        accepted: list[str] = []
        for candidate in candidates:
            if is_execution_noise(candidate.content) or candidate.category in {
                CandidateCategory.TOOL_OUTPUT,
                CandidateCategory.TEMPORARY,
            }:
                accepted.append(self._omission_label(candidate, language))
                continue
            present = _present_in_preview(candidate.content, searchable, candidate.category)
            if present and not _contradicts(candidate.content, searchable):
                continue
            issue_type = AuditIssueType.INCORRECT if _contradicts(
                candidate.content, searchable
            ) else AuditIssueType.MISSING
            if _strong_durable(candidate):
                findings.append(self._finding(candidate, issue_type, language, preview))
            elif candidate.category in {CandidateCategory.IMPORTANT_FACT, CandidateCategory.USER_PREFERENCE}:
                finding = self._finding(candidate, AuditIssueType.MISSING, language, preview)
                findings.append(finding.model_copy(update={"requires_user_confirmation": True}))
            else:
                accepted.append(
                    _localized(language, "未列入高优先级审计的旁支内容", "Lower-priority side context")
                )

        plan = self._build_grounded_plan(
            self._deduplicate_findings(findings),
            language,
            max_review_questions,
            preview=preview,
        )
        return plan.model_copy(update={"accepted_omissions": _unique(accepted)})

    def _finding(
        self,
        candidate: MemoryCandidate,
        issue_type: AuditIssueType,
        language: str,
        preview: str,
    ) -> AuditFinding:
        why = _localized(
            language,
            "这条来源明确的项目状态可能影响后续实现。",
            "This explicit source-backed project state may affect future implementation.",
        )
        target = _contradictory_preview_target(candidate.content, preview) if issue_type in {
            AuditIssueType.INCORRECT,
            AuditIssueType.STALE,
        } else None
        operation = AuditOperation.REPLACE if target else AuditOperation.ADD
        if issue_type in {AuditIssueType.INCORRECT, AuditIssueType.STALE} and not target:
            operation = AuditOperation.KEEP_PREVIEW
        return AuditFinding(
            id="finding_" + hashlib.sha1(
                "|".join(
                    [
                        candidate.category.value,
                        candidate.content,
                        ",".join(sorted(candidate.source_message_ids)),
                    ]
                ).encode()
            ).hexdigest()[:12],
            issue_type=issue_type,
            category=candidate.category,
            summary=_short(candidate.content),
            why_it_matters=why,
            suggested_correction=_short(candidate.content),
            importance=candidate.importance,
            confidence=candidate.confidence,
            source_message_ids=candidate.source_message_ids,
            evidence_snippets=[_short(candidate.content, 180)],
            task_relation=_relation_for(candidate.category, candidate.content),
            operation=operation,
            requires_user_confirmation=(candidate.category in {
                CandidateCategory.IMPORTANT_FACT,
                CandidateCategory.USER_PREFERENCE,
                CandidateCategory.WORKING_STATE,
            } and issue_type in {AuditIssueType.INCORRECT, AuditIssueType.STALE}),
            current_summary_text=target,
            proposed_text=_short(candidate.content),
            effect_if_rejected=(
                _localized(
                    language,
                    "当前摘要中的状态可能继续误导后续任务。",
                    "The current preview status may continue to mislead future work.",
                )
                if target else None
            ),
        )

    def _make_topics(
        self,
        findings: list[AuditFinding],
        language: str,
    ) -> list[AuditTopic]:
        grouped: dict[str, list[AuditFinding]] = defaultdict(list)
        for finding in findings:
            grouped[_topic_key(finding.summary, finding.category)].append(finding)
        topics: list[AuditTopic] = []
        for key, group in grouped.items():
            high_risk = max(item.importance for item in group)
            digest = hashlib.sha1("|".join(item.id for item in group).encode()).hexdigest()[:12]
            topic_family = key.split(":", 1)[0]
            is_status = any(
                item.category is CandidateCategory.WORKING_STATE
                and _looks_like_verification_status(item.summary)
                for item in group
            )
            if is_status:
                title = _localized(
                    language,
                    "测试验证状态可能不正确",
                    "Test or delivery status may be incorrect",
                )
            else:
                title = {
                    "project-direction": _localized(
                        language,
                        "项目目标、约束与技术决定",
                        "Project goals, constraints, and decisions",
                    ),
                    "tooling": _localized(
                        language, "工具与基础概念旁支讨论", "Tooling and fundamentals side discussion"
                    ),
                    "side-discussion": _localized(language, "旁支主题", "Side discussion"),
                }[topic_family]
            correction = "；".join(item.suggested_correction for item in group)
            relation = min(
                (item.task_relation for item in group),
                key=lambda value: {
                    AuditTaskRelation.PRIMARY: 0,
                    AuditTaskRelation.RELATED: 1,
                    AuditTaskRelation.BACKGROUND: 2,
                }[value],
            )
            operation = (
                AuditOperation.REPLACE
                if any(item.operation == AuditOperation.REPLACE for item in group)
                else AuditOperation.KEEP_PREVIEW
                if all(item.operation == AuditOperation.KEEP_PREVIEW for item in group)
                else AuditOperation.ADD
            )
            requires_confirmation = any(item.requires_user_confirmation for item in group)
            disposition = (
                AuditDisposition.ACCEPT_PREVIEW
                if operation == AuditOperation.KEEP_PREVIEW
                else AuditDisposition.ASK_USER
                if requires_confirmation
                else AuditDisposition.AUTO_CORRECT
            )
            if requires_confirmation:
                recommendation = (
                    "correct" if operation == AuditOperation.REPLACE
                    else "add" if operation == AuditOperation.ADD and relation == AuditTaskRelation.PRIMARY
                    else "keep"
                )
            else:
                recommendation = "correct" if operation != AuditOperation.KEEP_PREVIEW else "accept_preview"
            current = next((item.current_summary_text for item in group if item.current_summary_text), None)
            proposed = _short(
                "；".join(item.proposed_text or item.suggested_correction for item in group),
                500,
            )
            effect = next((item.effect_if_rejected for item in group if item.effect_if_rejected), None)
            topics.append(AuditTopic(
                id=f"audit_topic_{digest}",
                title=title,
                summary="；".join(item.summary for item in group),
                finding_ids=[item.id for item in group],
                impact=high_risk,
                confidence=min(item.confidence for item in group),
                relevance_to_main_goal=(1.0 if relation == AuditTaskRelation.PRIMARY else 0.35),
                requires_user_preference=requires_confirmation,
                disposition=disposition,
                recommended_action=recommendation,
                suggested_correction=correction,
                evidence_snippets=_unique(
                    evidence for item in group for evidence in item.evidence_snippets
                )[:3],
                task_relation=relation,
                operation=operation,
                current_summary_text=current,
                proposed_text=proposed,
                effect_if_rejected=effect,
            ))
        topics.sort(
            key=lambda item: (
                0 if item.disposition is AuditDisposition.ASK_USER else 1,
                -self._review_value(item)
                if item.disposition is AuditDisposition.ASK_USER
                else -item.impact,
                item.id,
            )
        )
        return topics

    @staticmethod
    def _review_value(topic: AuditTopic) -> float:
        """Rank only uncertain topics by impact, uncertainty, preference, and relevance."""

        if topic.disposition is not AuditDisposition.ASK_USER:
            return topic.impact
        preference_factor = 1.0 if topic.requires_user_preference else 0.5
        uncertainty = max(0.0, 1.0 - topic.confidence)
        relevance = max(0.1, topic.relevance_to_main_goal)
        return topic.impact * uncertainty * preference_factor * relevance

    @staticmethod
    def _make_questions(topics: list[AuditTopic], language: str, budget: int) -> list[ReviewQuestion]:
        questions: list[ReviewQuestion] = []
        for topic in topics:
            if topic.disposition is not AuditDisposition.ASK_USER:
                continue
            if topic.operation == AuditOperation.REPLACE:
                first_id, second_id = "correct", "keep_preview"
                first_label = _localized(language, "采用修正", "Apply correction")
                second_label = _localized(language, "保持当前摘要", "Keep current summary")
                first_description = _localized(
                    language,
                    "用下方的来源事实替换当前摘要中的这段文字；不会保留完整原始对话。",
                    "Replace the exact current-preview text with the source-backed fact; "
                    "the full history is not preserved.",
                )
                second_description = _localized(
                    language,
                    "不修改当前摘要，也不追加这项修正。",
                    "Leave the current preview unchanged and do not add this correction.",
                )
                question_text = _localized(
                    language,
                    f"是否采用对「{topic.title}」的摘要修正？",
                    f"Apply the summary correction for “{topic.title}”?",
                )
                recommendation = "correct"
            elif topic.task_relation == "primary" and topic.operation == AuditOperation.ADD:
                first_id, second_id = "add", "drop"
                first_label = _localized(language, "补充此信息", "Add this information")
                second_label = _localized(language, "不补充", "Do not add")
                first_description = _localized(
                    language,
                    "将来源明确的关键事实加入摘要；不会保留完整原始对话。",
                    "Add the source-backed fact to the summary; the full history is not preserved.",
                )
                second_description = _localized(
                    language,
                    "不特别补充这项信息，也不会删除原生摘要已有内容。",
                    "Do not add this information; existing native preview text is not deleted.",
                )
                question_text = _localized(
                    language,
                    f"是否补充「{topic.title}」中的关键事实？",
                    f"Add the key fact from “{topic.title}” to the summary?",
                )
                recommendation = "add"
            else:
                first_id, second_id = "keep", "drop"
                first_label = _localized(language, "保留关键结论", "Preserve key conclusion")
                second_label = _localized(language, "无需特别保留", "Do not specially preserve")
                first_description = _localized(
                    language,
                    "追加该主题的关键结论；不会保留完整原始对话。",
                    "Append the topic's key conclusion; the full history is not preserved.",
                )
                second_description = _localized(
                    language,
                    "不追加该主题；不会删除原生摘要已有内容。",
                    "Do not append this topic; existing native preview text is not deleted.",
                )
                question_text = _localized(
                    language,
                    f"压缩后是否需要特别保留「{topic.title}」？",
                    f"Should the compaction specially preserve “{topic.title}”?",
                )
                recommendation = "keep" if topic.recommended_action == "keep" else "drop"
            current = topic.current_summary_text or _localized(
                language,
                "当前摘要未提及。",
                "The current preview does not mention it.",
            )
            proposed = topic.proposed_text or topic.suggested_correction or topic.summary
            reason = topic.effect_if_rejected or _localized(
                language,
                "这是来源明确的内容，是否特别保留会影响后续任务的可用上下文。",
                "This is source-backed context, and the choice affects what remains useful after compaction.",
            )
            questions.append(
                ReviewQuestion(
                    id=f"question_{topic.id.removeprefix('audit_topic_')}",
                    topic_id=topic.id,
                    title=topic.title,
                    question=question_text,
                    context=_localized(
                        language,
                        f"主题说明：{topic.summary}\n\n当前摘要：{current}\n\n建议写入：{proposed}\n\n这部分不是完整原始对话，只会保留关键结论。",
                        f"Topic: {topic.summary}\n\nCurrent summary: {current}\n\n"
                        f"Proposed text: {proposed}\n\n"
                        "This is not the full original conversation; only the key conclusion is preserved.",
                    ),
                    why_it_matters=reason,
                    recommendation=recommendation,
                    options=[
                        ReviewOption(
                            id=first_id,
                            label=first_label,
                            description=first_description,
                        ),
                        ReviewOption(
                            id=second_id,
                            label=second_label,
                            description=second_description,
                        ),
                    ],
                    evidence_snippets=topic.evidence_snippets[:3],
                    task_relation=topic.task_relation,
                    operation=topic.operation,
                    current_summary_text=topic.current_summary_text,
                    proposed_text=proposed,
                    effect_if_rejected=reason,
                )
            )
        return questions[: max(0, min(3, budget))]

    @staticmethod
    def _apply_review_budget(topics: list[AuditTopic], budget: int) -> list[AuditTopic]:
        """Resolve ambiguous topics that cannot fit in the hard question budget."""

        remaining = max(0, min(3, budget))
        resolved: list[AuditTopic] = []
        for topic in topics:
            if topic.disposition is not AuditDisposition.ASK_USER:
                resolved.append(topic)
                continue
            if remaining > 0:
                remaining -= 1
                resolved.append(topic)
                continue
            if topic.impact >= 0.65 and topic.operation != AuditOperation.KEEP_PREVIEW:
                resolved.append(
                    topic.model_copy(
                        update={
                            "disposition": AuditDisposition.AUTO_CORRECT,
                            "recommended_action": "correct",
                        }
                    )
                )
            else:
                resolved.append(
                    topic.model_copy(
                        update={
                            "disposition": AuditDisposition.ACCEPT_PREVIEW,
                            "recommended_action": "accept_preview",
                        }
                    )
                )
        return resolved

    @staticmethod
    def _omission_label(candidate: MemoryCandidate, language: str) -> str:
        return _localized(language, "临时工具输出和执行日志", "Transient tool output and execution logs")

    @staticmethod
    def _overview(language: str, corrections: int, questions: int) -> str:
        if questions:
            zh = (
                f"本次压缩先审计原生预览，自动补正 {corrections} 项来源明确的关键状态；"
                f"还有 {questions} 个主题需要判断。"
            )
            en = (
                f"This compaction audits the native preview first and automatically corrects "
                f"{corrections} source-backed items; {questions} topic(s) need your judgment."
            )
        else:
            zh = (
                f"本次压缩先审计原生预览，自动补正 {corrections} 项来源明确的关键状态；"
                "没有需要人工判断的主题。"
            )
            en = (
                f"This compaction audits the native preview first and automatically corrects "
                f"{corrections} source-backed items; no topic needs your judgment."
            )
        return _localized(language, zh, en)


def _unique(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = item.strip()
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            result.append(value)
    return result


def validate_review_plan(
    review_plan: ReviewPlan,
    messages: Iterable[ConversationMessage | dict] | None,
    *,
    max_review_questions: int = 3,
    preview: str = "",
) -> ReviewPlan:
    """Re-ground a plan against the original request-local source snapshot.

    This is intentionally deterministic and provider-free.  It is used again
    immediately before facts are written so a host cannot mutate a plan after
    the audit and smuggle an unsupported correction into the native preview.
    """

    plan = ReviewPlan.model_validate(review_plan)
    if not messages:
        return ReviewPlan(language=plan.language)
    from .inspector import RuleBasedInspector

    auditor = PreviewAuditor(
        policy=ReviewPolicy(),
        rule_inspector=RuleBasedInspector(),
    )
    normalized = normalize_messages(messages)
    findings = auditor._sanitize_provider_findings(
        plan.findings,
        SourceIndex.from_messages(normalized),
        plan.language,
        preview=preview,
    )
    rebuilt = auditor._build_grounded_plan(
        auditor._deduplicate_findings(findings),
        plan.language,
        max_review_questions,
        diagnostics=plan.diagnostics,
        accepted_omissions=plan.accepted_omissions,
        coverage=plan.coverage,
        audit_status=plan.audit_status,
        degraded=plan.degraded,
        degradation_reason=plan.degradation_reason,
        preview=preview,
    )
    return rebuilt
