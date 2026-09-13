"""Bounded, topic-level review planning for host adapters."""

from __future__ import annotations

import hashlib
import os
import re
from collections import Counter
from collections.abc import Iterable

from .models import (
    CandidateCategory,
    ConversationMessage,
    MemoryCandidate,
    ReviewAction,
    ReviewDecision,
    ReviewPlan,
    ReviewTopic,
    ReviewTopicDecision,
)
from .policy import ReviewPolicy

DEFAULT_MAX_REVIEW_QUESTIONS = 3
MAX_REVIEW_QUESTIONS = 3

_COMMAND_START = re.compile(
    r"^\s*(?:\$|PS\s*[>:]|"
    r"(?:npm|pnpm|yarn|pip|uv)\s+(?:install|update|add|remove|ci|run|publish|audit|test)\b|"
    r"(?:grep|rg|find|ls|pwd|cat|head|tail)\s+(?:[-/]|[A-Za-z0-9_.]))",
    re.I,
)
_COMMAND_SENTENCE = re.compile(
    r"\b(?:ran|run|executed|execute|运行|执行)\s+(?:npm|pnpm|yarn|pip|uv|grep|rg|find|ls|pwd|cat)\b",
    re.I,
)
_LOG_LINE = re.compile(r"^\s*(?:traceback|error:|warning:|npm\s+(?:warn|notice|error)|debug:)\b", re.I)
_PATH_OR_HASH = re.compile(
    r"(?:^|\s)(?:[A-Za-z]:\\|/(?:Users|private|tmp|var|home)/|\.\.?/)[^\s]*"
    r"|\b[a-f0-9]{32,}\b",
    re.I,
)
_PERMISSION_BOILERPLATE = re.compile(
    r"operations that require approval may ask through the configured answers|"
    r"capability(?:ies)? (?:are|is) (?:not )?available",
    re.I,
)
_DURABLE_CONCLUSION = re.compile(
    r"\b(?:caused|because|due to|abandoned|rejected|failed|instead|selected|chosen|"
    r"決定|放弃|因为|由于|导致|改用)\b",
    re.I,
)
_TOKEN = re.compile(r"[a-z][a-z0-9_.-]{2,}|[\u4e00-\u9fff]+", re.I)
_LATIN_WORD = re.compile(r"\b[A-Za-z][A-Za-z0-9_'-]*\b")

_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "agent",
        "also",
        "been",
        "because",
        "being",
        "could",
        "current",
        "from",
        "have",
        "into",
        "more",
        "only",
        "project",
        "should",
        "that",
        "the",
        "their",
        "there",
        "this",
        "through",
        "with",
        "would",
        "以及",
        "一个",
        "可以",
        "当前",
        "相关",
        "项目",
        "问题",
        "讨论",
    }
)


def configured_max_review_questions(value: str | int | None = None) -> int:
    """Return a safe 0-3 review budget; malformed configuration uses the default."""

    raw = os.getenv("CONTEXT_GUARDIAN_MAX_REVIEW_QUESTIONS") if value is None else value
    if raw is None:
        return DEFAULT_MAX_REVIEW_QUESTIONS
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_REVIEW_QUESTIONS
    if 0 <= parsed <= MAX_REVIEW_QUESTIONS:
        return parsed
    return DEFAULT_MAX_REVIEW_QUESTIONS


def detect_language(messages: Iterable[ConversationMessage | dict]) -> str:
    """Detect language from user-authored messages only, with English fallback.

    Count Chinese characters but Latin words. Technical identifiers and product
    names such as ``Context Guardian`` or ``public API`` should not outweigh a
    Chinese sentence merely because they contain many individual letters.
    """

    user_text = " ".join(
        ConversationMessage.model_validate(message).content
        for message in messages
        if ConversationMessage.model_validate(message).role == "user"
    )
    chinese = len(re.findall(r"[\u4e00-\u9fff]", user_text))
    latin = len(_LATIN_WORD.findall(user_text))
    return "zh-CN" if chinese > latin else "en"


class ReviewPlanner:
    """Build a deterministic, bounded review plan from inspected candidates."""

    def __init__(self, max_review_questions: int | None = None):
        self.max_review_questions = configured_max_review_questions(max_review_questions)

    def build(
        self,
        messages: Iterable[ConversationMessage | dict],
        candidates: Iterable[MemoryCandidate],
    ) -> ReviewPlan:
        normalized_messages = [ConversationMessage.model_validate(message) for message in messages]
        normalized_candidates = list(candidates)
        language = detect_language(normalized_messages)
        source_roles = self._source_roles(normalized_messages)
        review_candidates = [
            candidate
            for candidate in normalized_candidates
            if candidate.suggested_action is ReviewAction.REVIEW
            and not self._is_noise(candidate, source_roles)
        ]
        clusters = self._cluster(review_candidates)
        topics = [self._topic(cluster, language) for cluster in clusters]
        topics.sort(key=lambda topic: (-self._topic_score(topic, normalized_candidates), topic.id))
        topics = topics[: self.max_review_questions]

        auto_keep = [
            candidate
            for candidate in normalized_candidates
            if candidate.suggested_action is ReviewAction.KEEP
        ]
        return ReviewPlan(
            language=language,
            overview=self._overview(language, len(topics)),
            auto_preserve_summary=self._auto_preserve_summary(auto_keep, language),
            review_topics=topics,
        )

    @staticmethod
    def _source_roles(messages: list[ConversationMessage]) -> dict[str, str]:
        roles: dict[str, str] = {}
        for index, message in enumerate(messages):
            roles[message.id or f"message_{index + 1:04d}"] = message.role
        return roles

    @classmethod
    def _is_noise(cls, candidate: MemoryCandidate, source_roles: dict[str, str]) -> bool:
        if candidate.category in {CandidateCategory.TOOL_OUTPUT, CandidateCategory.TEMPORARY}:
            return True
        content = candidate.content.strip()
        if _COMMAND_START.search(content) or _COMMAND_SENTENCE.search(content):
            return True
        if _LOG_LINE.search(content) or _PERMISSION_BOILERPLATE.search(content):
            return True
        if _PATH_OR_HASH.search(content) and not re.search(
            r"\b(?:incomplete|unfinished|TODO|未完成|待办|实现)\b", content, re.I
        ):
            return True
        roles = [source_roles.get(source_id) for source_id in candidate.source_message_ids]
        if roles and all(
            role in {"tool", "toolResult", "tool_result", "bashExecution"} for role in roles
        ):
            is_durable_failure = _DURABLE_CONCLUSION.search(content)
            return candidate.category is not CandidateCategory.FAILED_ATTEMPT or not is_durable_failure
        return False

    @classmethod
    def _tokens(cls, content: str) -> set[str]:
        tokens: set[str] = set()
        for token in _TOKEN.findall(content.casefold()):
            if re.fullmatch(r"[\u4e00-\u9fff]+", token):
                tokens.update(token[index : index + 2] for index in range(len(token) - 1))
            elif token not in _STOPWORDS:
                tokens.add(token)
        return {token for token in tokens if token not in _STOPWORDS and len(token) > 1}

    @classmethod
    def _cluster(cls, candidates: list[MemoryCandidate]) -> list[list[MemoryCandidate]]:
        clusters: list[list[MemoryCandidate]] = []
        cluster_tokens: list[set[str]] = []
        for candidate in candidates:
            tokens = cls._tokens(candidate.content)
            matching_index = next(
                (
                    index
                    for index, existing_tokens in enumerate(cluster_tokens)
                    if tokens and existing_tokens and len(tokens & existing_tokens) >= 1
                ),
                None,
            )
            if matching_index is None:
                clusters.append([candidate])
                cluster_tokens.append(set(tokens))
            else:
                clusters[matching_index].append(candidate)
                cluster_tokens[matching_index].update(tokens)
        return clusters

    @classmethod
    def _topic(cls, cluster: list[MemoryCandidate], language: str) -> ReviewTopic:
        candidate_ids = [candidate.id for candidate in cluster]
        digest = hashlib.sha1("|".join(candidate_ids).encode()).hexdigest()[:12]
        recommendation = "keep" if cls._recommendation_score(cluster) >= 0.65 else "drop"
        snippets = [cls._clean_for_ui(candidate.content) for candidate in cluster[:3]]
        summary = "；".join(snippets) if language in {"zh", "zh-CN"} else "; ".join(snippets)
        if recommendation == "keep":
            why = (
                "该主题可能影响后续实现，但当前归属或重要性仍不完全确定。"
                if language in {"zh", "zh-CN"}
                else "This topic may affect future work, but its importance or scope is still uncertain."
            )
        else:
            why = (
                "该主题与当前主任务关联较弱，默认不要求压缩器特别保留。"
                if language in {"zh", "zh-CN"}
                else "This topic appears weakly related to the main task and is not specially "
                "preserved by default."
            )
        return ReviewTopic(
            id=f"review_topic_{digest}",
            title=cls._title(cluster, language),
            summary=summary,
            why_it_matters=why,
            recommendation=recommendation,
            candidate_ids=candidate_ids,
            evidence_snippets=snippets,
        )

    @classmethod
    def _title(cls, cluster: list[MemoryCandidate], language: str) -> str:
        tokens = Counter(token for candidate in cluster for token in cls._tokens(candidate.content))
        common = {token for token, _ in tokens.most_common(8)}
        if "npm" in common:
            return (
                "npm 基础概念的旁支讨论"
                if language in {"zh", "zh-CN"}
                else "npm fundamentals side discussion"
            )
        if "python" in common:
            return (
                "Python 基础概念的旁支讨论"
                if language in {"zh", "zh-CN"}
                else "Python fundamentals side discussion"
            )
        if "sqlite" in common or "postgresql" in common or "database" in common:
            return (
                "数据库方案旁支讨论"
                if language in {"zh", "zh-CN"}
                else "Database approach side discussion"
            )
        if all(candidate.category is CandidateCategory.FAILED_ATTEMPT for candidate in cluster):
            return (
                "已放弃方案的旁支讨论"
                if language in {"zh", "zh-CN"}
                else "Rejected approach side discussion"
            )
        return "相关旁支主题" if language in {"zh", "zh-CN"} else "Related side discussion"

    @staticmethod
    def _recommendation_score(cluster: list[MemoryCandidate]) -> float:
        return max(
            candidate.importance * 0.7
            + (1 - candidate.confidence) * 0.3
            + (0.08 if candidate.category in {
                CandidateCategory.CONSTRAINT,
                CandidateCategory.DECISION,
                CandidateCategory.TODO,
                CandidateCategory.FAILED_ATTEMPT,
            } else 0)
            for candidate in cluster
        )

    @staticmethod
    def _topic_score(topic: ReviewTopic, candidates: list[MemoryCandidate]) -> float:
        candidate_map = {candidate.id: candidate for candidate in candidates}
        score = max(
            candidate_map[candidate_id].importance * 0.7
            + (1 - candidate_map[candidate_id].confidence) * 0.3
            for candidate_id in topic.candidate_ids
            if candidate_id in candidate_map
        )
        return score + (0.05 if topic.recommendation == "keep" else 0)

    @staticmethod
    def _clean_for_ui(content: str) -> str:
        return re.sub(r"\s+", " ", content).strip()[:240]

    @staticmethod
    def _overview(language: str, topic_count: int) -> str:
        if language == "zh-CN":
            if topic_count:
                return (
                    "本次压缩将自动保留明确的项目目标、约束、决定和未完成工作。"
                    f"还有 {topic_count} 个旁支主题需要你判断。"
                )
            return "本次压缩将自动保留明确的项目目标、约束、决定和未完成工作。没有需要人工判断的旁支主题。"
        if topic_count:
            return (
                "This compaction will automatically preserve explicit goals, constraints, decisions, "
                f"and unfinished work. {topic_count} side topic(s) need your judgment."
            )
        return (
            "This compaction will automatically preserve explicit goals, constraints, decisions, "
            "and unfinished work. No side topics need your judgment."
        )

    @staticmethod
    def _auto_preserve_summary(candidates: list[MemoryCandidate], language: str) -> str:
        if language == "zh-CN":
            return "明确的项目目标、用户约束、关键决定和未完成工作将自动保留。"
        return (
            "Explicit project goals, user constraints, key decisions, and unfinished work will be "
            "preserved automatically."
        )


def expand_topic_decisions(
    plan: ReviewPlan,
    decisions: Iterable[ReviewTopicDecision | dict],
) -> list[ReviewDecision]:
    """Map topic answers to every atomic candidate contained in each topic."""

    topic_map = {topic.id: topic for topic in plan.review_topics}
    mapped: dict[str, ReviewAction] = {}
    for raw_decision in decisions:
        decision = ReviewTopicDecision.model_validate(raw_decision)
        topic = topic_map.get(decision.topic_id)
        if topic is None:
            raise ValueError(f"unknown review topic: {decision.topic_id}")
        action = ReviewAction(decision.action)
        for candidate_id in topic.candidate_ids:
            previous = mapped.get(candidate_id)
            if previous is not None and previous is not action:
                raise ValueError(f"conflicting decisions for candidate: {candidate_id}")
            mapped[candidate_id] = action
    return [
        ReviewDecision(candidate_id=candidate_id, action=action.value)
        for candidate_id, action in mapped.items()
    ]


def resolve_review_decisions(
    candidates: Iterable[MemoryCandidate],
    plan: ReviewPlan,
    topic_decisions: Iterable[ReviewTopicDecision | dict] = (),
    *,
    policy: ReviewPolicy | None = None,
) -> list[ReviewDecision]:
    """Resolve topic answers and safely handle review candidates outside the budget."""

    candidate_list = list(candidates)
    explicit = {item.candidate_id: item.action for item in expand_topic_decisions(plan, topic_decisions)}
    review_policy = policy or ReviewPolicy()
    decisions: list[ReviewDecision] = []
    for candidate in candidate_list:
        if candidate.suggested_action is ReviewAction.KEEP:
            action = ReviewAction.KEEP
        elif candidate.suggested_action is ReviewAction.DROP:
            action = ReviewAction.DROP
        elif candidate.id in explicit:
            action = ReviewAction(explicit[candidate.id])
        elif (
            candidate.category in review_policy.preserve_categories
            or candidate.importance >= review_policy.keep_importance - 0.15
        ):
            action = ReviewAction.KEEP
        else:
            action = ReviewAction.DROP
        decisions.append(ReviewDecision(candidate_id=candidate.id, action=action.value))
    return decisions
