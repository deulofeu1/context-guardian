import { BasicCompactionEngine } from "@deepseek-ai/dsh-compaction-basic";
import { createUserMessage } from "@deepseek-ai/dsh-llm";
import { GuardianBridge, normalizeDeepSeekMessages } from "./bridge.js";
export const name = "context-guardian-deepseek-harness";
const MAX_REVIEW_QUESTIONS = 3;
if (process.env.CONTEXT_GUARDIAN_DEBUG === "1") {
    console.error("context guardian: adapter module loaded");
}
const bridge = new GuardianBridge();
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
function reviewQuestionsForUi(questions) {
    return questions.slice(0, MAX_REVIEW_QUESTIONS).map((question) => ({
        id: question.id,
        header: question.title,
        question: question.question,
        detail: `${question.context}\n\n${question.why_it_matters}\n\n${question.options.map((option) => `${option.label}: ${option.description}`).join("\n")}`,
        options: question.options.map((option) => ({
            label: option.label,
            description: option.description,
        })),
    }));
}
async function answerReviewQuestions(ctx, agent, plan, signal) {
    if (plan.review_questions.length === 0)
        return [];
    const interaction = ctx.get("userQuestions");
    if (interaction === undefined)
        return answersForNoUi(plan);
    try {
        const answer = await interaction.ask({
            questions: reviewQuestionsForUi(plan.review_questions),
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
        debug(ctx, `userQuestions failed with ${code ?? (error instanceof Error ? error.message : String(error))}`);
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
    async summarize(input, agent, signal) {
        const operationSignal = signal ?? new AbortController().signal;
        const preview = await super.summarize(input, agent, signal);
        const messages = normalizeInput(input);
        let plan;
        try {
            plan = await bridge.auditPreview(this.ctx, agent, messages, textFromSummary(preview), "", "", operationSignal, configuredReviewBudget());
            debug(this.ctx, `native preview audited: ${String(plan.findings.length)} finding(s), ${String(plan.review_questions.length)} question(s)`);
        }
        catch (error) {
            this.ctx.logger.warn(`context guardian audit unavailable; accepting native preview: ${error instanceof Error ? error.message : String(error)}`);
            return preview;
        }
        let answers;
        try {
            answers = await answerReviewQuestions(this.ctx, agent, plan, operationSignal);
        }
        catch (error) {
            this.ctx.logger.warn(`context guardian review cancelled; accepting native preview: ${error instanceof Error ? error.message : String(error)}`);
            return preview;
        }
        if (!needsRevision(plan, answers))
            return preview;
        let guidance;
        try {
            guidance = await bridge.revisionGuidance(this.ctx, agent, plan, answers, operationSignal);
        }
        catch (error) {
            this.ctx.logger.warn(`context guardian revision unavailable; accepting native preview: ${error instanceof Error ? error.message : String(error)}`);
            return preview;
        }
        if (!guidance.text)
            return preview;
        try {
            return await super.summarize(nativeInputWithGuidance(input, guidance.text), agent, signal);
        }
        catch (error) {
            this.ctx.logger.warn(`context guardian final compaction failed; accepting native preview: ${error instanceof Error ? error.message : String(error)}`);
            return preview;
        }
    }
}
export default ContextGuardianCompactionEngine;
//# sourceMappingURL=index.js.map