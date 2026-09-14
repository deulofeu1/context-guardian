import { BasicCompactionEngine } from "@deepseek-ai/dsh-compaction-basic";
import { createUserMessage } from "@deepseek-ai/dsh-llm";
import { GuardianBridge, normalizeDeepSeekMessages, preferredLanguage } from "./bridge.js";
export const name = "context-guardian-deepseek-harness";
const MAX_REVIEW_QUESTIONS = 3;
if (process.env.CONTEXT_GUARDIAN_DEBUG === "1") {
    console.error("context guardian: adapter module loaded");
}
const bridge = new GuardianBridge();
const UI_MESSAGES = {
    en: {
        auditUnavailable: "Context Guardian audit unavailable; accepting the successful native preview.",
        reviewCancelled: "Context Guardian review unavailable; accepting the successful native preview.",
        revisionUnavailable: "Context Guardian revision unavailable; accepting the successful native preview.",
        finalFailed: "Context Guardian final compaction failed; accepting the successful native preview.",
    },
    "zh-CN": {
        auditUnavailable: "Context Guardian 审计不可用；接受已经成功生成的原生预览。",
        reviewCancelled: "Context Guardian 人工审查不可用；接受已经成功生成的原生预览。",
        revisionUnavailable: "Context Guardian 修正指导不可用；接受已经成功生成的原生预览。",
        finalFailed: "Context Guardian 最终压缩失败；接受已经成功生成的原生预览。",
    },
};
function uiMessage(language, key) {
    return UI_MESSAGES[language][key];
}
export function uiMessageWithError(language, key, error) {
    const detail = error instanceof Error ? error.message : String(error);
    const normalized = detail.replace(/\s+/g, " ").trim().slice(0, 300);
    return normalized ? `${uiMessage(language, key)} Details: ${normalized}` : uiMessage(language, key);
}
function debug(ctx, message) {
    if (process.env.CONTEXT_GUARDIAN_DEBUG === "1") {
        const line = `context guardian: ${message}`;
        console.error(line);
        ctx.logger.info(line);
    }
}
function configuredReviewBudget() {
    const value = Number(process.env.CONTEXT_GUARDIAN_MAX_REVIEW_QUESTIONS ?? MAX_REVIEW_QUESTIONS);
    return Number.isInteger(value) && value >= 0 && value <= MAX_REVIEW_QUESTIONS ? value : MAX_REVIEW_QUESTIONS;
}
export function answersForNoUi(plan) {
    return plan.review_questions.map((question) => ({
        question_id: question.id,
        topic_id: question.topic_id,
        action: question.recommendation,
    }));
}
export function needsRevision(plan, answers) {
    return plan.auto_corrections.length > 0 || answers.some((answer) => answer.action === "keep");
}
function reviewQuestionsForUi(plan) {
    return plan.review_questions.slice(0, MAX_REVIEW_QUESTIONS).map((question) => ({
        id: question.id,
        header: question.title,
        question: question.question,
        detail: `${plan.overview}\n\n${question.context}\n\n${question.why_it_matters}\n\n${question.options.map((option) => `${option.label}: ${option.description}`).join("\n")}`,
        options: question.options.map((option) => ({
            label: option.label,
            description: option.description,
        })),
    }));
}
async function answerReviewQuestions(ctx, agent, plan, signal) {
    if (plan.review_questions.length === 0)
        return [];
    // `Context.get()` deliberately bypasses a plugin's injected dependency map.
    // Compaction is an isolated Cordis plugin, so read the injected property
    // instead; otherwise the Web answerer is present in the host but invisible
    // to this adapter and every review silently takes the no-UI fallback.
    let interaction;
    try {
        interaction = ctx.userQuestions;
    }
    catch (error) {
        debug(ctx, `userQuestions unavailable; policy fallback ${errorCode(error) ?? "missing"}`);
        return answersForNoUi(plan);
    }
    if (interaction === undefined)
        return answersForNoUi(plan);
    try {
        const answer = await interaction.ask({
            questions: reviewQuestionsForUi(plan),
            agent,
            signal,
        });
        const byId = new Map(answer.answers.map((item) => [item.id, item]));
        return plan.review_questions.slice(0, MAX_REVIEW_QUESTIONS).map((question) => {
            const item = byId.get(question.id);
            if (item?.custom !== undefined || item?.selected.length !== 1) {
                throw new Error(`Context Guardian received an invalid answer for ${question.id}`);
            }
            const selected = item.selected[0];
            const option = question.options.find((candidate) => candidate.label === selected);
            if (!option)
                throw new Error(`Context Guardian received an unknown answer for ${question.id}`);
            return {
                question_id: question.id,
                topic_id: question.topic_id,
                action: option.id,
            };
        });
    }
    catch (error) {
        const code = errorCode(error);
        debug(ctx, `userQuestions unavailable; policy fallback ${code ?? "unknown"}`);
        if (code === "NO_PROVIDER")
            return answersForNoUi(plan);
        throw error;
    }
}
function errorCode(error) {
    return typeof error === "object" && error !== null && "code" in error
        ? String(error.code)
        : undefined;
}
function nativeInputWithGuidance(input, text) {
    const guidanceMessage = createUserMessage({
        content: [{ type: "text", text }],
        source: { kind: "plugin", plugin: name },
    });
    return {
        ...input,
        messages: [...input.messages, guidanceMessage],
    };
}
function normalizeInput(input) {
    const candidate = input;
    return normalizeDeepSeekMessages(candidate.system, input.messages);
}
function textFromSummary(result) {
    const blocks = result.summary;
    return blocks
        .filter((block) => block?.type === "text" || block?.type === "reasoning")
        .map((block) => block.text ?? "")
        .join("\n")
        .trim();
}
/**
 * Decorates the native DeepSeek Harness compactor. The native engine owns the
 * single transaction; this override only performs an uncommitted preview,
 * an external audit, and (when needed) one guided native retry.
 */
export class ContextGuardianCompactionEngine extends BasicCompactionEngine {
    // Compaction runs in its own isolated Cordis scope. Declare the human
    // question capability explicitly so the Web answerer is visible there;
    // without this dependency the adapter silently took its no-UI fallback.
    static inject = [...BasicCompactionEngine.inject, "userQuestions"];
    async summarize(input, agent, signal) {
        const operationSignal = signal ?? new AbortController().signal;
        const preview = await super.summarize(input, agent, signal);
        const messages = normalizeInput(input);
        let uiLanguage = preferredLanguage(messages);
        let plan;
        try {
            plan = await bridge.auditPreview(this.ctx, agent, messages, textFromSummary(preview), "", "", operationSignal, configuredReviewBudget());
            debug(this.ctx, `preview ready: findings=${String(plan.findings.length)}, topics=${String(plan.audit_topics.length)}, `
                + `auto_corrections=${String(plan.auto_corrections.length)}, accepted=${String(plan.accepted_omissions.length)}, `
                + `questions=${String(plan.review_questions.length)}`);
        }
        catch (error) {
            this.ctx.logger.warn(uiMessageWithError(uiLanguage, "auditUnavailable", error));
            return preview;
        }
        uiLanguage = plan.language;
        let answers;
        try {
            answers = await answerReviewQuestions(this.ctx, agent, plan, operationSignal);
        }
        catch (error) {
            this.ctx.logger.warn(uiMessageWithError(uiLanguage, "reviewCancelled", error));
            return preview;
        }
        if (!needsRevision(plan, answers)) {
            debug(this.ctx, "native preview reused; final compaction not needed");
            return preview;
        }
        let guidance;
        try {
            guidance = await bridge.revisionGuidance(this.ctx, agent, plan, answers, operationSignal);
        }
        catch (error) {
            this.ctx.logger.warn(uiMessageWithError(uiLanguage, "revisionUnavailable", error));
            return preview;
        }
        if (!guidance.text)
            return preview;
        try {
            debug(this.ctx, "running one guided native final compaction");
            return await super.summarize(nativeInputWithGuidance(input, guidance.text), agent, signal);
        }
        catch (error) {
            this.ctx.logger.warn(uiMessageWithError(uiLanguage, "finalFailed", error));
            return preview;
        }
    }
}
export default ContextGuardianCompactionEngine;
//# sourceMappingURL=index.js.map