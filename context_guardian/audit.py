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

_COMPLETION = re.compile(r"\b(?:completed|complete|finished|resolved|已完成|完成|已解决)\b", re.I)
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{2,}|[\u4e00-\u9fff]+", re.I)
_LATIN_WORD = re.compile(r"\b[A-Za-z][A-Za-z0-9_'-]*\b")


class AuditInput(BaseModel):
    """Bounded, complete-message input prepared for a provider audit."""

    text: str
    message_ids: list[str] = Field(default_factory=list)
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
        normalized = normalize_messages(messages)
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
        normalized = normalize_messages(messages)
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
        for message in selected:
            message_id = self._message_id(message, 0)
            block = f"[{message.role} id={message_id}]\n{message.content}"
            if used + len(block) + 2 > available:
                truncated = True
                continue
            source_blocks.append(block)
            selected_ids.append(message_id)
            used += len(block) + 2
        text = fixed_text + "\n\nORIGINAL SOURCE SIGNALS:\n" + "\n\n".join(source_blocks)
        return AuditInput(
            text=text,
            message_ids=selected_ids,
            truncated=truncated,
            source_messages=selected,
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
        normalized = normalize_messages(messages)
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
            grounded_findings: list[AuditFinding] = []
            provider_review_finding_ids: set[str] = set()
            for item in inputs:
                provider_plan = self.provider.generate_structured(
                    self._provider_prompt(item.text, selected_language, max_review_questions),
                    ReviewPlan,
                )
                source_index = SourceIndex.from_messages(item.source_messages)
                sanitized = self._sanitize_provider_findings(
                    provider_plan.findings,
                    source_index,
                    selected_language,
                )
                grounded_findings.extend(sanitized)
                provider_review_finding_ids.update(
                    self._provider_review_finding_ids(
                        provider_plan,
                        {finding.id for finding in sanitized},
                    )
                )
            grounded_findings = self._deduplicate_findings(grounded_findings)
            if provider_review_finding_ids:
                grounded_findings = [
                    finding.model_copy(update={"issue_type": AuditIssueType.AMBIGUOUS})
                    if finding.id in provider_review_finding_ids
                    else finding
                    for finding in grounded_findings
                ]
            return self._build_grounded_plan(
                grounded_findings,
                selected_language,
                max_review_questions,
            )
        return self._local_audit(
            normalized,
            preview=preview,
            previous_summary=previous_summary,
            retained_context=retained_context,
            language=selected_language,
            max_review_questions=max_review_questions,
        )

    @staticmethod
    def _deduplicate_findings(findings: Iterable[AuditFinding]) -> list[AuditFinding]:
        result: list[AuditFinding] = []
        seen: set[tuple[str, str, tuple[str, ...]]] = set()
        for finding in findings:
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
            why = _localized(
                language,
                "这条来源明确的项目状态可能影响后续实现。",
                "This explicit source-backed project state may affect future implementation.",
            )
            sanitized.append(
                finding.model_copy(
                    update={
                        "summary": source_fact,
                        "why_it_matters": why,
                        # Never write an arbitrary provider correction. The
                        # accepted correction is complete source context that
                        # contains the validated evidence, not the raw phrase
                        # the provider happened to cite.
                        "suggested_correction": source_fact,
                        "evidence_snippets": [source_fact],
                    }
                )
            )
        return sanitized

    @staticmethod
    def _provider_review_finding_ids(
        provider_plan: ReviewPlan,
        accepted_finding_ids: set[str],
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
        return requested & accepted_finding_ids

    def _build_grounded_plan(
        self,
        findings: list[AuditFinding],
        language: str,
        max_review_questions: int,
    ) -> ReviewPlan:
        topics = self._apply_review_budget(
            self._make_topics(findings, language)[:MAX_AUDIT_TOPICS],
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
            review_questions=questions,
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
When a topic needs user judgment, mark its findings with issue_type="ambiguous", include
those finding IDs in an audit_topics entry, and reference that topic from review_questions.
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
                findings.append(self._finding(candidate, issue_type, language))
            elif candidate.category in {CandidateCategory.IMPORTANT_FACT, CandidateCategory.USER_PREFERENCE}:
                findings.append(self._finding(candidate, AuditIssueType.AMBIGUOUS, language))
            else:
                accepted.append(
                    _localized(language, "未列入高优先级审计的旁支内容", "Lower-priority side context")
                )

        plan = self._build_grounded_plan(
            self._deduplicate_findings(findings),
            language,
            max_review_questions,
        )
        return plan.model_copy(update={"accepted_omissions": _unique(accepted)})

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
                                "将该主题的关键结论追加到 Reviewed Facts；不保存完整原始对话。",
                                "Append the topic's key conclusion to Reviewed Facts; do not "
                                "preserve the full history.",
                            ),
                        ),
                        ReviewOption(
                            id="drop",
                            label=_localized(language, "无需特别保留", "Accept preview"),
                            description=_localized(
                                language,
                                "不追加该主题的关键结论；不会删除原生 Preview 已有内容。",
                                "Do not append this topic's key conclusion; existing native Preview "
                                "content is not removed.",
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
    )
    return auditor._build_grounded_plan(
        auditor._deduplicate_findings(findings),
        plan.language,
        max_review_questions,
    )
