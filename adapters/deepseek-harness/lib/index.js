import { BasicCompactionEngine } from "@deepseek-ai/dsh-compaction-basic";
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
        factsUnavailable: "Context Guardian reviewed facts unavailable; accepting the successful native preview.",
    },
    "zh-CN": {
        auditUnavailable: "Context Guardian 审计不可用；接受已经成功生成的原生预览。",
        reviewCancelled: "Context Guardian 人工审查不可用；接受已经成功生成的原生预览。",
        factsUnavailable: "Context Guardian Reviewed Facts 不可用；接受已经成功生成的原生预览。",
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
        action: question.operation === "replace"
            ? "keep_preview"
            : question.operation === "add"
                ? "drop"
                : question.recommendation,
    }));
}
export function reviewQuestionsForUi(plan) {
    const chinese = plan.language === "zh-CN";
    return plan.review_questions.slice(0, MAX_REVIEW_QUESTIONS).map((question, index) => {
        const evidence = question.evidence_snippets?.length
            ? `${chinese ? "来源证据（原文，仅用于核对" : "Source evidence (verbatim, for verification"}`
                + `${question.source_message_ids?.length ? ` · ${chinese ? "消息" : "messages"} ${question.source_message_ids.join(", ")}` : ""}）：\n`
                + question.evidence_snippets.join("\n")
            : "";
        const detailParts = [
            ...(index === 0 && plan.overview ? [plan.overview] : []),
            question.context,
            question.why_it_matters
                ? `${chinese ? "原因" : "Why it matters"}：${question.why_it_matters}`
                : "",
            evidence,
            chinese
                ? "这只会影响上面列出的关键结论，不会保留完整原始对话。"
                : "This affects only the key conclusion shown above; the full original conversation is not preserved.",
        ].filter(Boolean);
        return {
            id: question.id,
            header: question.title,
            question: question.question,
            detail: detailParts.join("\n\n"),
            options: question.options.map((option) => ({
                label: option.label,
                description: option.description,
            })),
        };
    });
}
export async function answerReviewQuestions(ctx, agent, plan, signal) {
    if (plan.review_questions.length === 0)
        return [];
    const explicitNoUi = process.env.CONTEXT_GUARDIAN_NO_UI === "1";
    // `Context.get()` deliberately bypasses a plugin's injected dependency map.
    // Compaction is an isolated Cordis plugin, so read the injected property
    // instead; otherwise the Web answerer is present in the host but invisible
    // to this adapter and every review silently takes the no-UI fallback.
    let interaction;
    try {
        interaction = ctx.userQuestions;
    }
    catch (error) {
        debug(ctx, `Review UI unavailable: cannot access live userQuestions (${errorCode(error) ?? "missing"})`);
        if (explicitNoUi)
            return answersForNoUi(plan);
        throw Object.assign(new Error("Context Guardian Review UI unavailable: live userQuestions is not accessible"), { code: "UI_UNAVAILABLE" });
    }
    if (interaction === undefined) {
        debug(ctx, "Review UI unavailable: live userQuestions capability is missing from the isolated compaction scope");
        if (explicitNoUi)
            return answersForNoUi(plan);
        throw Object.assign(new Error("Context Guardian Review UI unavailable: live userQuestions capability is missing"), { code: "UI_UNAVAILABLE" });
    }
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
        debug(ctx, `Review UI request failed: ${code ?? "unknown"}`);
        if (explicitNoUi && code === "NO_PROVIDER")
            return answersForNoUi(plan);
        throw error;
    }
}
function errorCode(error) {
    return typeof error === "object" && error !== null && "code" in error
        ? String(error.code)
        : undefined;
}
function normalizeInput(input) {
    const candidate = input;
    return normalizeDeepSeekMessages(candidate.system, input.messages);
}
function textFromSummary(result) {
    const blocks = result.summary;
    return blocks
        .filter((block) => block?.type === "text")
        .map((block) => block.text ?? "")
        .join("\n")
        .trim();
}
export function applyFinalizationToSummary(summary, finalization) {
    const blocks = summary.map((block) => ({ ...block }));
    for (const edit of finalization.edits.filter((item) => item.status === "applied")) {
        const candidates = blocks
            .map((block, index) => ({ block, index }))
            .filter(({ block }) => block.type === "text" && typeof block.text === "string" && block.text.includes(edit.target));
        // Never apply an edit that spans blocks or has an ambiguous host match.
        if (candidates.length !== 1)
            continue;
        candidates[0].block.text = candidates[0].block.text.replace(edit.target, edit.replacement);
    }
    if (finalization.appendix.text) {
        const alreadyPresent = blocks.some((block) => typeof block.text === "string" && block.text.includes(finalization.appendix.text));
        if (!alreadyPresent) {
            const lastText = [...blocks].reverse().find((block) => block.type === "text");
            if (lastText && typeof lastText.text === "string") {
                lastText.text = `${lastText.text}\n\n${finalization.appendix.text}`;
            }
            else {
                blocks.push({ type: "text", text: finalization.appendix.text });
            }
        }
    }
    return blocks;
}
/**
 * Decorates the native DeepSeek Harness compactor. The native engine owns the
 * single transaction; this override only performs an uncommitted preview,
 * an external audit, and a deterministic append to the returned summary.
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
        if (plan.diagnostics?.length) {
            this.ctx.logger.warn(plan.diagnostics.join("\n"));
        }
        let answers;
        try {
            answers = await answerReviewQuestions(this.ctx, agent, plan, operationSignal);
        }
        catch (error) {
            this.ctx.logger.warn(uiMessageWithError(uiLanguage, "reviewCancelled", error));
            return preview;
        }
        let finalization;
        try {
            finalization = await bridge.finalizePreview(this.ctx, agent, plan, answers, textFromSummary(preview), messages, operationSignal);
        }
        catch (error) {
            this.ctx.logger.warn(uiMessageWithError(uiLanguage, "factsUnavailable", error));
            return preview;
        }
        if (!finalization.changed) {
            debug(this.ctx, "native_compaction_calls=1 reviewed_facts_auto=0 reviewed_facts_human=0 reviewed_facts_total=0 preview_changed=false");
            return preview;
        }
        if (finalization.diagnostics?.length)
            this.ctx.logger.warn(finalization.diagnostics.join("\n"));
        const summary = applyFinalizationToSummary(preview.summary, finalization);
        debug(this.ctx, `native_compaction_calls=1 reviewed_facts_auto=${String(finalization.appendix.facts.filter((fact) => fact.origin === "auto_correction").length)} `
            + `reviewed_facts_human=${String(finalization.appendix.facts.filter((fact) => fact.origin === "human_keep").length)} `
            + `reviewed_facts_total=${String(finalization.appendix.facts.length)} edits=${String(finalization.edits.length)} preview_changed=true`);
        return { ...preview, summary };
    }
}
export default ContextGuardianCompactionEngine;
//# sourceMappingURL=index.js.map