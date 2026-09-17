"""Context inspection and public ContextGuardian facade."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from pydantic import BaseModel, Field

from .models import (
    CandidateCategory,
    CompactionGuidance,
    ContextCheckpoint,
    ConversationMessage,
    InspectionResult,
    MemoryCandidate,
    PreviewFinalization,
    ReviewAction,
    ReviewDecision,
    ReviewedFactsAppendix,
    ReviewPlan,
)
from .policy import ReviewPolicy
from .provenance import is_source_allowed, normalize_messages
from .providers import ModelProvider, ProviderError


class CandidateBatch(BaseModel):
    candidates: list[MemoryCandidate] = Field(default_factory=list)


class RuleBasedInspector:
    """Conservative source-derived extractor with no network dependency."""

    _high_signal_patterns: tuple[tuple[re.Pattern[str], CandidateCategory], ...] = (
        (
            re.compile(
                r"(not verified|unverified|not tested|did not appear|didn't appear|"
                r"not shown|not completed|still pending|current status|未验证|未测试|"
                r"未弹窗|没有弹窗|尚未|还没|仍未|未完成|停在|状态)",
                re.I,
            ),
            CandidateCategory.WORKING_STATE,
        ),
        (
            re.compile(r"\b(must|need to|required|requirement|不能|必须|要求)\b", re.I),
            CandidateCategory.CONSTRAINT,
        ),
        (
            re.compile(
                r"\b(todo|to-do|next step|unfinished|incomplete|still incomplete|未完成|下一步)\b", re.I
            ),
            CandidateCategory.TODO,
        ),
        (
            re.compile(
                r"\b(decided|decision|choose|chosen|selected|use .* instead(?: of)?|"
                r"stop using|改为|改用|决定)\b",
                re.I,
            ),
            CandidateCategory.DECISION,
        ),
        (
            re.compile(r"\b(failed|failure|abandoned|rejected|because .* issue|失败|放弃|问题)\b", re.I),
            CandidateCategory.FAILED_ATTEMPT,
        ),
        (re.compile(r"\b(goal|objective|implement|build|实现|目标)\b", re.I), CandidateCategory.GOAL),
        (re.compile(r"\b(prefer|preference|希望|偏好|不要|不想)\b", re.I), CandidateCategory.USER_PREFERENCE),
    )
    _noise_patterns: tuple[re.Pattern[str], ...] = (
        re.compile(r"^(npm|pnpm|yarn|pip|uv)\s+(install|update|add|remove)\b", re.I),
        re.compile(r"^(grep|rg|find|ls|pwd|cat|head|tail)\b", re.I),
        re.compile(r"^(traceback|error:|warning:|npm warn|debug:)\b", re.I),
        re.compile(r"\b(resolved|fixed|temporary)\b.*\b(error|issue|debug|syntax)\b", re.I),
    )

    def inspect(self, messages: Iterable[ConversationMessage], policy: ReviewPolicy) -> list[MemoryCandidate]:
        candidates: list[MemoryCandidate] = []
        for index, raw_message in enumerate(normalize_messages(messages)):
            message = ConversationMessage.model_validate(raw_message)
            if not is_source_allowed(message):
                continue
            content = message.content.strip()
            if not content:
                continue
            source_id = message.id or f"message_{index + 1:04d}"
            for sentence in self._atomic_lines(content):
                sentence = sentence.strip()
                if not sentence:
                    continue
                category, importance, confidence, reason = self._classify(message, sentence)
                candidate_id = self._candidate_id(source_id, sentence, category)
                candidates.append(
                    policy.apply(
                        MemoryCandidate(
                            id=candidate_id,
                            content=sentence,
                            category=category,
                            importance=importance,
                            confidence=confidence,
                            suggested_action=ReviewAction.REVIEW,
                            reason=reason,
                            source_message_ids=[source_id],
                        )
                    )
                )
        return self._deduplicate(candidates)

    def _classify(
        self, message: ConversationMessage, content: str
    ) -> tuple[CandidateCategory, float, float, str]:
        if message.role in {"tool", "toolResult", "tool_result", "bashExecution"} or message.tool_name:
            if message.is_error:
                return (
                    CandidateCategory.FAILED_ATTEMPT,
                    0.72,
                    0.63,
                    "An error result may explain a failed approach.",
                )
            return (
                CandidateCategory.TOOL_OUTPUT,
                0.08,
                0.96,
                "Tool output is usually transient execution detail.",
            )
        for pattern, category in self._high_signal_patterns:
            if pattern.search(content):
                importance = (
                    0.91 if category in {CandidateCategory.CONSTRAINT, CandidateCategory.DECISION} else 0.82
                )
                confidence = (
                    0.9 if category in {CandidateCategory.CONSTRAINT, CandidateCategory.DECISION} else 0.82
                )
                return category, importance, confidence, f"Matched a high-signal {category.value} phrase."
        if any(pattern.search(content) for pattern in self._noise_patterns):
            return (
                CandidateCategory.TEMPORARY,
                0.08,
                0.95,
                "Looks like a transient command, log, or diagnostic.",
            )
        if message.role == "user":
            return (
                CandidateCategory.IMPORTANT_FACT,
                0.55,
                0.45,
                "User-authored context without a stronger signal.",
            )
        return CandidateCategory.TEMPORARY, 0.2, 0.45, "No durable-memory signal was detected."

    @staticmethod
    def _atomic_lines(content: str) -> list[str]:
        normalized = re.sub(r"[ \t]+", " ", content).strip()
        parts = re.split(r"\n+|(?<=[.!?。！？])\s+|(?<=;)\s+", normalized)
        return [part.strip(" -\t") for part in parts if part.strip(" -\t")]

    @staticmethod
    def _candidate_id(source_id: str, content: str, category: CandidateCategory) -> str:
        digest = hashlib.sha1(f"{source_id}|{category.value}|{content}".encode()).hexdigest()[:12]
        return f"memory_{digest}"

    @staticmethod
    def _deduplicate(candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
        seen: set[tuple[str, CandidateCategory]] = set()
        result: list[MemoryCandidate] = []
        for candidate in candidates:
            key = (candidate.content.casefold(), candidate.category)
            if key in seen:
                continue
            seen.add(key)
            result.append(candidate)
        return result


class ContextGuardian:
    """High-level API for inspection, review decisions, and guidance."""

    def __init__(
        self,
        provider: ModelProvider | None = None,
        *,
        policy: ReviewPolicy | None = None,
        rule_inspector: RuleBasedInspector | None = None,
    ):
        self.provider = provider
        self.policy = policy or ReviewPolicy()
        self.rule_inspector = rule_inspector or RuleBasedInspector()

    def inspect(self, messages: Iterable[ConversationMessage | dict]) -> InspectionResult:
        normalized = [ConversationMessage.model_validate(message) for message in messages]
        if self.provider is None:
            candidates = self.rule_inspector.inspect(normalized, self.policy)
            return InspectionResult.from_candidates(
                candidates, mode="rules", policy_version=self.policy.version
            )

        prompt = self._build_inspection_prompt(
            [message for message in normalized if is_source_allowed(message)]
        )
        try:
            batch = self.provider.generate_structured(prompt, CandidateBatch)
            candidates = [self.policy.apply(candidate) for candidate in batch.candidates]
            return InspectionResult.from_candidates(
                candidates, mode="provider", policy_version=self.policy.version
            )
        except ProviderError:
            raise

    def inspect_with_fallback(self, messages: Iterable[ConversationMessage | dict]) -> InspectionResult:
        normalized = [ConversationMessage.model_validate(message) for message in messages]
        try:
            return self.inspect(normalized)
        except Exception as error:
            candidates = self.rule_inspector.inspect(normalized, self.policy)
            message = (
                f"Host-model inspection failed ({type(error).__name__}); degraded to local rules."
            )
            return InspectionResult.from_candidates(
                candidates,
                mode="rules",
                policy_version=self.policy.version,
                degraded=True,
                diagnostics=[message],
            )

    def audit_preview(
        self,
        messages: Iterable[ConversationMessage | dict],
        *,
        preview: str,
        previous_summary: str = "",
        retained_context: str = "",
        language: str | None = None,
        max_review_questions: int | None = None,
    ) -> ReviewPlan:
        """Audit a host-native preview without generating a replacement summary.

        A configured provider receives a bounded, source-backed audit prompt. The
        local path uses conservative rules and is intentionally usable without an
        API key, which is also the adapter fail-open fallback.
        """
        from .audit import PreviewAuditor
        from .review import configured_max_review_questions

        budget = configured_max_review_questions(max_review_questions)
        return PreviewAuditor(
            policy=self.policy,
            rule_inspector=self.rule_inspector,
            provider=self.provider,
        ).audit(
            messages,
            preview=preview,
            previous_summary=previous_summary,
            retained_context=retained_context,
            language=language,
            max_review_questions=budget,
        )

    def audit_preview_with_fallback(
        self,
        messages: Iterable[ConversationMessage | dict],
        *,
        preview: str,
        previous_summary: str = "",
        retained_context: str = "",
        language: str | None = None,
        max_review_questions: int | None = None,
    ) -> ReviewPlan:
        """Run preview audit and degrade to deterministic local rules on failure."""
        normalized = [ConversationMessage.model_validate(message) for message in messages]
        try:
            return self.audit_preview(
                normalized,
                preview=preview,
                previous_summary=previous_summary,
                retained_context=retained_context,
                language=language,
                max_review_questions=max_review_questions,
            )
        except Exception as error:
            from .audit import PreviewAuditor
            from .review import configured_max_review_questions

            fallback = PreviewAuditor(
                policy=self.policy,
                rule_inspector=self.rule_inspector,
            ).audit(
                normalized,
                preview=preview,
                previous_summary=previous_summary,
                retained_context=retained_context,
                language=language,
                max_review_questions=configured_max_review_questions(max_review_questions),
            )
            selected_language = fallback.language
            message = (
                f"宿主模型审计失败（{type(error).__name__}）；已降级到本地规则，未使用未经验证的模型结果。"
                if selected_language == "zh-CN"
                else (
                    f"Host-model audit failed ({type(error).__name__}); degraded to local rules "
                    "without using unverified model output."
                )
            )
            return fallback.model_copy(update={
                "audit_status": "rules_fallback",
                "degraded": True,
                "degradation_reason": type(error).__name__,
                "diagnostics": [*fallback.diagnostics, message][:5],
            })

    def build_revision_guidance(
        self,
        *,
        review_plan: ReviewPlan,
        answers: Iterable[dict] = (),
    ) -> CompactionGuidance:
        """Build only incremental corrections for a second native compaction call."""
        from .guidance import build_revision_guidance

        return build_revision_guidance(review_plan, answers)

    def build_reviewed_facts(
        self,
        *,
        review_plan: ReviewPlan,
        answers: Iterable[dict] = (),
        messages: Iterable[ConversationMessage | dict] | None = None,
    ) -> ReviewedFactsAppendix:
        """Build the deterministic facts appended after one native preview."""
        from .reviewed_facts import build_reviewed_facts

        return build_reviewed_facts(review_plan, answers, messages)

    def append_reviewed_facts(
        self,
        *,
        preview: str,
        appendix: ReviewedFactsAppendix,
    ) -> str:
        from .reviewed_facts import append_reviewed_facts

        return append_reviewed_facts(preview, appendix)

    def finalize_preview(
        self,
        *,
        preview: str,
        review_plan: ReviewPlan,
        answers: Iterable[dict] = (),
        messages: Iterable[ConversationMessage | dict] | None = None,
    ) -> PreviewFinalization:
        """Finalize a host preview without invoking a second model call."""
        from .reviewed_facts import finalize_preview

        return finalize_preview(
            preview=preview,
            review_plan=review_plan,
            answers=answers,
            messages=messages,
        )

    def apply_decisions(
        self,
        candidates: Iterable[MemoryCandidate],
        decisions: Iterable[ReviewDecision | dict],
        *,
        unresolved_action: ReviewAction = ReviewAction.REVIEW,
    ) -> list[MemoryCandidate]:
        decision_map = {
            item.candidate_id: item.action
            for item in (ReviewDecision.model_validate(decision) for decision in decisions)
        }
        result: list[MemoryCandidate] = []
        for candidate in candidates:
            action = decision_map.get(candidate.id)
            if action:
                result.append(candidate.model_copy(update={"suggested_action": ReviewAction(action)}))
            elif candidate.suggested_action is ReviewAction.REVIEW:
                result.append(candidate.model_copy(update={"suggested_action": unresolved_action}))
            else:
                result.append(candidate)
        return result

    def build_guidance(
        self,
        candidates: Iterable[MemoryCandidate],
        decisions: Iterable[ReviewDecision | dict] = (),
        *,
        unresolved_action: ReviewAction = ReviewAction.REVIEW,
    ) -> CompactionGuidance:
        from .guidance import build_guidance

        resolved = self.apply_decisions(candidates, decisions, unresolved_action=unresolved_action)
        return build_guidance(resolved)

    def build_checkpoint(
        self,
        candidates: Iterable[MemoryCandidate],
        decisions: Iterable[ReviewDecision | dict] = (),
        *,
        unresolved_action: ReviewAction = ReviewAction.KEEP,
    ) -> ContextCheckpoint:
        """Build a durable checkpoint from the same reviewed candidates as guidance."""
        from .checkpoint import build_checkpoint

        resolved = self.apply_decisions(candidates, decisions, unresolved_action=unresolved_action)
        return build_checkpoint(resolved, unresolved_action=unresolved_action)

    @staticmethod
    def _build_inspection_prompt(messages: list[ConversationMessage]) -> str:
        serialized = "\n".join(f"[{message.role}] {message.content}" for message in messages)
        return f"""You are the inspection stage of Context Guardian.

Extract only future-relevant, atomic memory candidates from the conversation below.
Do not summarize the whole conversation. Do not invent facts. Keep exact constraints,
decisions, rejected approaches and unfinished work. Mark logs and transient tool output
as temporary or tool_output. Return only the requested structured schema.

Conversation:
<conversation>
{serialized}
</conversation>"""
