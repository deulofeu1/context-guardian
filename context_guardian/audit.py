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
    AuditDisposition,
    AuditFinding,
    AuditIssueType,
    AuditTopic,
    CandidateCategory,
    ConversationMessage,
    MemoryCandidate,
    ReviewOption,
    ReviewPlan,
    ReviewQuestion,
)
from .policy import ReviewPolicy

MAX_AUDIT_FINDINGS = 20
MAX_AUDIT_TOPICS = 10
DEFAULT_AUDIT_INPUT_CHARS = 48_000

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
_LOG_INLINE = re.compile(
    r"\b(?:traceback|npm\s+(?:warn|notice|error)|debug:)\b",
    re.I,
)
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
_DURABLE = re.compile(
    r"\b(?:goal|objective|must|required|constraint|requirement|decision|decided|chosen|selected|"
    r"final|todo|unfinished|incomplete|still need|abandoned|rejected|failed|because|due to|"
    r"目标|必须|约束|要求|决定|最终|待办|未完成|放弃|失败|因为|由于|导致|改用)\b",
    re.I,
)
_COMPLETION = re.compile(r"\b(?:completed|complete|finished|resolved|已完成|完成|已解决)\b", re.I)
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{2,}|[\u4e00-\u9fff]+", re.I)
_LATIN_WORD = re.compile(r"\b[A-Za-z][A-Za-z0-9_'-]*\b")


class AuditInput(BaseModel):
    """Bounded, complete-message input prepared for a provider audit."""

    text: str
    message_ids: list[str] = Field(default_factory=list)
    truncated: bool = False


def detect_user_language(messages: Iterable[ConversationMessage | dict]) -> str:
    """Detect language from user-authored messages only.

    Count Chinese characters but Latin words so technical identifiers and
    product names do not drown out the language of a Chinese sentence.
    """

    normalized = [ConversationMessage.model_validate(message) for message in messages]
    user_text = " ".join(message.content for message in normalized if message.role == "user")
    chinese = len(re.findall(r"[\u4e00-\u9fff]", user_text))
    latin = len(_LATIN_WORD.findall(user_text))
    return "zh-CN" if chinese > latin else "en"


def is_execution_noise(content: str) -> bool:
    """Return whether text is mechanical execution detail, not a durable conclusion."""

    value = content.strip()
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
    if _PATH_OR_HASH.search(value) and not _DURABLE.search(value):
        return True
    return False


class AuditInputBuilder:
    """Build provider input without cutting through a conversation message."""

    def __init__(self, max_chars: int = DEFAULT_AUDIT_INPUT_CHARS):
        self.max_chars = max(4_000, int(max_chars))

    @staticmethod
    def _message_id(message: ConversationMessage, index: int) -> str:
        return message.id or f"message_{index + 1:04d}"

    @staticmethod
    def _message_priority(message: ConversationMessage) -> int:
        if message.role == "user":
            return 4
        if message.role in {"tool", "toolResult", "tool_result", "bashExecution"}:
            return 0 if is_execution_noise(message.content) else 2
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
        normalized = [ConversationMessage.model_validate(message) for message in messages]
        ranked = sorted(
            enumerate(normalized),
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
        result = [message for index, message in enumerate(normalized) if index in selected]
        return result, len(result) != len(normalized)

    def build(
        self,
        messages: Iterable[ConversationMessage | dict],
        *,
        preview: str,
        previous_summary: str = "",
        retained_context: str = "",
        language: str | None = None,
    ) -> AuditInput:
        normalized = [ConversationMessage.model_validate(message) for message in messages]
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
        used_indices: set[int] = set()
        for message in selected:
            original_index = next(
                index for index, candidate in enumerate(normalized)
                if index not in used_indices and candidate == message
            )
            used_indices.add(original_index)
            message_id = self._message_id(message, original_index)
            block = f"[{message.role} id={message_id}]\n{message.content}"
            if used + len(block) + 2 > available:
                truncated = True
                continue
            source_blocks.append(block)
            selected_ids.append(message_id)
            used += len(block) + 2
        text = fixed_text + "\n\nORIGINAL SOURCE SIGNALS:\n" + "\n\n".join(source_blocks)
        return AuditInput(text=text, message_ids=selected_ids, truncated=truncated)

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
        normalized = [ConversationMessage.model_validate(message) for message in messages]
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
    if any(word in lower_content for word in ("incomplete", "unfinished", "未完成", "待办")):
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


def _topic_key(content: str, category: CandidateCategory) -> str:
    lower = content.casefold()
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
            provider_plans = [
                self.provider.generate_structured(
                    self._provider_prompt(item.text, selected_language, max_review_questions),
                    ReviewPlan,
                )
                for item in inputs
            ]
            provider_plan = self._merge_provider_plans(provider_plans, selected_language)
            return self._sanitize_provider_plan(provider_plan, selected_language, max_review_questions)
        return self._local_audit(
            normalized,
            preview=preview,
            previous_summary=previous_summary,
            retained_context=retained_context,
            language=selected_language,
            max_review_questions=max_review_questions,
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
natural-language lines. Do not invent corrections. The UI language is {language}.
Return the ReviewPlan schema exactly; auto_corrections must be incremental source-backed
corrections, not a complete summary.

{text}"""

    @staticmethod
    def _merge_provider_plans(plans: list[ReviewPlan], language: str) -> ReviewPlan:
        """Merge independently audited message chunks without exceeding model limits."""

        if not plans:
            return ReviewPlan(language=language)

        findings: list[AuditFinding] = []
        finding_keys: set[str] = set()
        topic_by_key: dict[tuple[str, str], AuditTopic] = {}
        topic_source_ids: dict[tuple[str, str], set[str]] = defaultdict(set)
        questions: list[ReviewQuestion] = []
        question_keys: set[tuple[str, str]] = set()
        corrections: list[str] = []
        omissions: list[str] = []

        for plan in plans:
            for finding in plan.findings:
                key = f"{finding.category.value}|{finding.summary.casefold()}"
                if key not in finding_keys and len(findings) < MAX_AUDIT_FINDINGS:
                    finding_keys.add(key)
                    findings.append(finding)
            for topic in plan.audit_topics:
                key = (topic.title.casefold(), topic.summary.casefold())
                topic_source_ids[key].add(topic.id)
                if key not in topic_by_key:
                    digest = hashlib.sha1((topic.title + topic.summary).encode()).hexdigest()[:12]
                    topic_by_key[key] = topic.model_copy(
                        update={"id": f"audit_topic_{digest}"}
                    )
            corrections.extend(plan.auto_corrections)
            omissions.extend(plan.accepted_omissions)

        topics = list(topic_by_key.values())
        topics.sort(key=lambda item: (-item.impact, item.id))
        topics = topics[:MAX_AUDIT_TOPICS]
        topic_key_by_source_id = {
            source_id: key
            for key, source_ids in topic_source_ids.items()
            for source_id in source_ids
        }
        kept_topic_ids = {topic.id for topic in topics}
        for plan in plans:
            for question in plan.review_questions:
                key = topic_key_by_source_id.get(question.topic_id)
                topic = topic_by_key.get(key) if key else None
                if topic is None or topic.id not in kept_topic_ids:
                    continue
                question_key = (topic.id, question.title.casefold())
                if question_key in question_keys:
                    continue
                question_keys.add(question_key)
                questions.append(question.model_copy(update={"topic_id": topic.id}))

        topic_by_id = {topic.id: topic for topic in topics}
        questions.sort(
            key=lambda item: (
                -PreviewAuditor._review_value(topic_by_id[item.topic_id]),
                item.id,
            )
        )
        return ReviewPlan(
            language=language,
            overview=next((plan.overview for plan in plans if plan.overview), ""),
            auto_preserve_summary=next(
                (plan.auto_preserve_summary for plan in plans if plan.auto_preserve_summary), ""
            ),
            findings=findings,
            audit_topics=topics,
            auto_corrections=_unique(corrections)[:MAX_AUDIT_FINDINGS],
            accepted_omissions=_unique(omissions)[:MAX_AUDIT_FINDINGS],
            review_questions=questions[:3],
        )

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
                findings.append(self._finding(candidate, issue_type, language))
            elif candidate.category in {CandidateCategory.IMPORTANT_FACT, CandidateCategory.USER_PREFERENCE}:
                findings.append(self._finding(candidate, AuditIssueType.AMBIGUOUS, language))
            else:
                accepted.append(
                    _localized(language, "未列入高优先级审计的旁支内容", "Lower-priority side context")
                )

        findings = findings[:MAX_AUDIT_FINDINGS]
        topics = self._apply_review_budget(
            self._make_topics(findings, language)[:MAX_AUDIT_TOPICS],
            max_review_questions,
        )
        questions = self._make_questions(topics, language, max_review_questions)
        auto_corrections = _unique(
            finding.suggested_correction
            for finding in findings
            if next((topic for topic in topics if finding.id in topic.finding_ids), None)
            and next(topic for topic in topics if finding.id in topic.finding_ids).disposition
            is AuditDisposition.AUTO_CORRECT
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
            accepted_omissions=_unique(accepted),
            review_questions=questions,
        )

    def _finding(
        self,
        candidate: MemoryCandidate,
        issue_type: AuditIssueType,
        language: str,
    ) -> AuditFinding:
        why = _localized(
            language,
            "这条来源明确的项目状态可能影响后续实现。",
            "This explicit source-backed project state may affect future implementation.",
        )
        return AuditFinding(
            id=f"finding_{hashlib.sha1(candidate.id.encode()).hexdigest()[:12]}",
            issue_type=issue_type,
            category=candidate.category,
            summary=_short(candidate.content),
            why_it_matters=why,
            suggested_correction=_short(candidate.content),
            importance=candidate.importance,
            confidence=candidate.confidence,
            source_message_ids=candidate.source_message_ids,
            evidence_snippets=[_short(candidate.content, 180)],
        )

    def _make_topics(
        self,
        findings: list[AuditFinding],
        language: str,
    ) -> list[AuditTopic]:
        grouped: dict[str, list[AuditFinding]] = defaultdict(list)
        ambiguous: dict[str, list[AuditFinding]] = defaultdict(list)
        for finding in findings:
            key = _topic_key(finding.summary, finding.category)
            if finding.issue_type is AuditIssueType.AMBIGUOUS:
                ambiguous[key].append(finding)
            else:
                grouped[key].append(finding)
        topics: list[AuditTopic] = []
        for key, group in grouped.items():
            high_risk = max(item.importance for item in group)
            digest = hashlib.sha1("|".join(item.id for item in group).encode()).hexdigest()[:12]
            topic_family = key.split(":", 1)[0]
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
            topics.append(
                AuditTopic(
                    id=f"audit_topic_{digest}",
                    title=title,
                    summary="；".join(item.summary for item in group),
                    finding_ids=[item.id for item in group],
                    impact=high_risk,
                    confidence=min(item.confidence for item in group),
                    relevance_to_main_goal=high_risk,
                    requires_user_preference=False,
                    disposition=AuditDisposition.AUTO_CORRECT,
                    recommended_action="correct",
                    suggested_correction=correction,
                )
            )
        for key, group in ambiguous.items():
            digest = hashlib.sha1("|".join(item.id for item in group).encode()).hexdigest()[:12]
            title = (
                _localized(language, "工具基础概念的旁支讨论", "Tooling fundamentals side discussion")
                if key == "tooling"
                else _localized(language, "未决旁支主题", "Unresolved side topic")
            )
            examples = "；".join(_short(item.summary) for item in group[:2])
            suffix = f"（共 {len(group)} 条相关内容）" if len(group) > 2 else ""
            summary = examples + suffix
            keep = max(item.importance for item in group) >= 0.65
            topics.append(
                AuditTopic(
                    id=f"audit_topic_{digest}",
                    title=title,
                    summary=summary,
                    finding_ids=[item.id for item in group],
                    impact=max(item.importance for item in group),
                    confidence=min(item.confidence for item in group),
                    relevance_to_main_goal=0.35,
                    requires_user_preference=True,
                    disposition=AuditDisposition.ASK_USER,
                    recommended_action="keep" if keep else "drop",
                    suggested_correction=summary,
                )
            )
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
            keep = topic.recommended_action == "keep"
            questions.append(
                ReviewQuestion(
                    id=f"question_{topic.id.removeprefix('audit_topic_')}",
                    topic_id=topic.id,
                    title=topic.title,
                    question=_localized(
                        language,
                        f"压缩后是否需要特别保留「{topic.title}」？",
                        f"Should the compaction specially preserve “{topic.title}”?",
                    ),
                    context=_localized(
                        language,
                        f"你曾讨论：{topic.summary}。这部分不是完整原始对话，只会保留关键结论。",
                        f"You discussed: {topic.summary}. This preserves key conclusions only, "
                        "not the full original conversation.",
                    ),
                    why_it_matters=_localized(
                        language,
                        "它与当前主任务关系较弱，只有在你希望后续继续使用这部分背景时才需要保留。",
                        "It is weakly related to the main task and matters only if you want "
                        "to use this background later.",
                    ),
                    recommendation="keep" if keep else "drop",
                    options=[
                        ReviewOption(
                            id="keep",
                            label=_localized(language, "保留关键结论", "Preserve key conclusion"),
                            description=_localized(
                                language,
                                "要求原生压缩器强调保留该主题的关键结论。",
                                "Ask the native compactor to preserve the topic's key conclusion.",
                            ),
                        ),
                        ReviewOption(
                            id="drop",
                            label=_localized(language, "无需特别保留", "Accept preview"),
                            description=_localized(
                                language,
                                "不要求特别保留；不代表删除所有相关历史。",
                                "Do not specially preserve it; this does not mean deleting all "
                                "related history.",
                            ),
                        ),
                    ],
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
            if topic.impact >= 0.65:
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

    @staticmethod
    def _sanitize_provider_plan(plan: ReviewPlan, language: str, budget: int) -> ReviewPlan:
        topics = PreviewAuditor._apply_review_budget(plan.audit_topics[:MAX_AUDIT_TOPICS], budget)
        questions = [
            question
            for question in plan.review_questions
            if not is_execution_noise(
                " ".join(
                    (
                        question.title,
                        question.question,
                        question.context,
                        question.why_it_matters,
                        *(option.label + " " + option.description for option in question.options),
                    )
                )
            )
        ][: max(0, min(3, budget))]
        allowed = {topic.id for topic in topics}
        questions = [question for question in questions if question.topic_id in allowed]
        auto_corrections = [
            item
            for item in plan.auto_corrections[:MAX_AUDIT_FINDINGS]
            if not is_execution_noise(item)
        ]
        for topic in topics:
            if topic.disposition is AuditDisposition.AUTO_CORRECT and topic.suggested_correction:
                auto_corrections.append(topic.suggested_correction)
        return plan.model_copy(
            update={
                "language": language,
                "findings": plan.findings[:MAX_AUDIT_FINDINGS],
                "audit_topics": topics,
                "auto_corrections": _unique(_short(item) for item in auto_corrections)[:MAX_AUDIT_FINDINGS],
                "accepted_omissions": [
                    _short(item)
                    for item in plan.accepted_omissions[:MAX_AUDIT_FINDINGS]
                    if not is_execution_noise(item)
                ],
                "review_questions": questions,
            }
        )


def _unique(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = item.strip()
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            result.append(value)
    return result
