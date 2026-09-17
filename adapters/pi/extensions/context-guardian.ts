import {
  compact,
  type ExtensionAPI,
  type ExtensionContext,
  type SessionBeforeCompactEvent,
} from "@earendil-works/pi-coding-agent";
import { GuardianBridge, normalizePiMessages, preferredLanguage } from "../src/bridge.ts";
import type { ReviewPlan, ReviewQuestion } from "../src/types.ts";

const bridge = new GuardianBridge();
const MAX_REVIEW_QUESTIONS = 3;
type UiLanguage = "zh-CN" | "en";
type UiMessageKey = "auditUnavailable" | "reviewCancelled" | "factsUnavailable" | "guardianUnavailable";

const UI_MESSAGES: Record<UiLanguage, Record<UiMessageKey, string>> = {
  en: {
    auditUnavailable: "Context Guardian audit unavailable; using the successful native preview.",
    reviewCancelled: "Context Guardian review unavailable; using the successful native preview.",
    factsUnavailable: "Context Guardian reviewed facts unavailable; using the successful native preview.",
    guardianUnavailable: "Context Guardian unavailable; continuing with native compaction.",
  },
  "zh-CN": {
    auditUnavailable: "Context Guardian 审计不可用；将使用已经成功生成的原生预览。",
    reviewCancelled: "Context Guardian 人工审查不可用；将使用已经成功生成的原生预览。",
    factsUnavailable: "Context Guardian Reviewed Facts 不可用；将使用已经成功生成的原生预览。",
    guardianUnavailable: "Context Guardian 不可用；继续使用宿主原生压缩。",
  },
};

function uiMessage(language: UiLanguage, key: UiMessageKey): string {
  return UI_MESSAGES[language][key];
}

function auditNotice(plan: ReviewPlan): string {
  return plan.language === "zh-CN"
    ? `${plan.overview} 原生压缩调用：1 次 · 自动校正：${String(plan.auto_corrections.length)} 项 · 人工问题：${String(plan.review_questions.length)} 个`
    : `${plan.overview} Native compaction calls: 1 · Auto corrections: ${String(plan.auto_corrections.length)} · `
      + `Review questions: ${String(plan.review_questions.length)}`;
}

function configuredReviewBudget(): number {
  const value = Number(process.env.CONTEXT_GUARDIAN_MAX_REVIEW_QUESTIONS ?? MAX_REVIEW_QUESTIONS);
  return Number.isInteger(value) && value >= 0 && value <= MAX_REVIEW_QUESTIONS ? value : MAX_REVIEW_QUESTIONS;
}

function debug(message: string): void {
  if (process.env.CONTEXT_GUARDIAN_DEBUG === "1") {
    console.error(`context guardian: ${message}`);
  }
}

export function questionBody(question: ReviewQuestion): string {
  const chinese = /[\u4e00-\u9fff]/.test(
    `${question.question} ${question.context} ${question.why_it_matters}`,
  );
  const evidence = question.evidence_snippets?.length
    ? chinese
      ? `\n\n来源证据（原文，仅用于核对）：\n${question.evidence_snippets.join("\n")}`
      : `\n\nSource evidence (verbatim, for verification):\n${question.evidence_snippets.join("\n")}`
    : "";
  return `${question.question}\n\n${question.context}\n\n${chinese ? "原因：" : "Why it matters: "}${question.why_it_matters}`
    + `${evidence}\n\n${chinese ? "请选择下方操作；这不会保留完整原始对话。" : "Choose an action below; the full original conversation is not preserved."}`;
}

export function answersForNoUi(plan: ReviewPlan): Array<{
  question_id: string;
  topic_id: string;
  action: "keep" | "drop" | "correct" | "keep_preview" | "add";
}> {
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

export async function answerReviewQuestions(
  ctx: ExtensionContext,
  plan: ReviewPlan,
  signal: AbortSignal,
): Promise<Array<{ question_id: string; topic_id: string; action: "keep" | "drop" | "correct" | "keep_preview" | "add" }>> {
  if (!ctx.hasUI) return answersForNoUi(plan);

  const answers: Array<{ question_id: string; topic_id: string; action: "keep" | "drop" | "correct" | "keep_preview" | "add" }> = [];
  for (const question of plan.review_questions.slice(0, MAX_REVIEW_QUESTIONS)) {
    if (signal.aborted) throw new Error("review aborted");
    let optionIndex: number;
    if (typeof ctx.ui.select === "function") {
      const selected = await ctx.ui.select(
        questionBody(question),
        question.options.map((option) => `${option.label} — ${option.description}`),
        { signal },
      );
      if (selected === undefined) throw new Error("review cancelled");
      optionIndex = question.options.findIndex(
        (option) => selected === `${option.label} — ${option.description}`,
      );
    } else {
      // Compatibility fallback for older/mocked hosts. Current Pi exposes
      // select(), so real installations still show both explicit actions.
      const accepted = await ctx.ui.confirm(question.title, questionBody(question), { signal });
      optionIndex = accepted ? 0 : 1;
    }
    if (optionIndex < 0) throw new Error(`unknown review option for ${question.id}`);
    answers.push({
      question_id: question.id,
      topic_id: question.topic_id,
      action: question.options[optionIndex].id,
    });
  }
  return answers;
}

function summaryFromPreview(preview: { summary?: unknown }): string {
  return typeof preview.summary === "string" ? preview.summary : "";
}

function retainedContextFromPreparation(preparation: SessionBeforeCompactEvent["preparation"]): string {
  const messages = preparation.turnPrefixMessages ?? [];
  return normalizePiMessages(messages).map((message) => message.content).join("\n");
}

async function handleBeforeCompact(event: SessionBeforeCompactEvent, ctx: ExtensionContext) {
  debug("session_before_compact received");
  if (!ctx.model) {
    debug("skipping: host model unavailable");
    return;
  }

  const messages = normalizePiMessages(
    event.preparation.messagesToSummarize,
    event.preparation.previousSummary,
  );
  let uiLanguage: UiLanguage = preferredLanguage(messages);

  try {
    const auth = await ctx.modelRegistry.getApiKeyAndHeaders(ctx.model);
    if (!auth.ok) {
      debug("skipping: host model authentication unavailable");
      return;
    }

    const headers = auth.headers
      ? Object.fromEntries(
          Object.entries(auth.headers).filter(
            (entry): entry is [string, string] => entry[1] !== null,
          ),
        )
      : undefined;
    // The first native call is the user's preview. It is never committed by this
    // hook; the session manager commits only the result returned below.
    const preview = await compact(
      event.preparation,
      ctx.model,
      auth.apiKey,
      headers,
      event.customInstructions,
      event.signal,
      ctx.thinkingLevel,
    );
    debug(`native preview received chars=${String(summaryFromPreview(preview).length)}`);

    let plan: ReviewPlan;
    try {
      plan = await bridge.auditPreview(
        ctx,
        messages,
        summaryFromPreview(preview),
        event.preparation.previousSummary,
        retainedContextFromPreparation(event.preparation),
        event.signal,
        configuredReviewBudget(),
      );
    } catch (error) {
      debug(`audit failed: ${error instanceof Error ? error.message : String(error)}`);
      if (ctx.hasUI) {
        ctx.ui.notify(uiMessage(uiLanguage, "auditUnavailable"), "warning");
      }
      return { compaction: preview };
    }

    uiLanguage = plan.language;
    if (ctx.hasUI) {
      ctx.ui.notify(auditNotice(plan), "info");
      if (plan.diagnostics?.length) {
        ctx.ui.notify(plan.diagnostics.join("\n"), "warning");
      }
    }

    let answers;
    try {
      answers = await answerReviewQuestions(ctx, plan, event.signal);
    } catch (error) {
      debug(`review failed: ${error instanceof Error ? error.message : String(error)}`);
      if (ctx.hasUI) {
        ctx.ui.notify(uiMessage(uiLanguage, "reviewCancelled"), "warning");
      }
      return { compaction: preview };
    }
    let finalization;
    try {
      finalization = await bridge.finalizePreview(
        ctx,
        plan,
        answers,
        summaryFromPreview(preview),
        messages,
        event.signal,
      );
    } catch (error) {
      debug(`finalization failed: ${error instanceof Error ? error.message : String(error)}`);
      if (ctx.hasUI) {
        ctx.ui.notify(uiMessage(uiLanguage, "factsUnavailable"), "warning");
      }
      return { compaction: preview };
    }
    const originalSummary = summaryFromPreview(preview);
    const finalSummary = finalization.final_summary;
    if (finalization.diagnostics?.length && ctx.hasUI) {
      ctx.ui.notify(finalization.diagnostics.join("\n"), "warning");
    }
    debug(
      `native_compaction_calls=1 reviewed_facts_auto=${String(finalization.appendix.facts.filter((fact) => fact.origin === "auto_correction").length)} `
        + `reviewed_facts_human=${String(finalization.appendix.facts.filter((fact) => fact.origin === "human_keep").length)} `
        + `reviewed_facts_total=${String(finalization.appendix.facts.length)} edits=${String(finalization.edits.length)} preview_changed=${String(finalSummary !== originalSummary)}`,
    );
    if (finalSummary === originalSummary) return { compaction: preview };
    return { compaction: { ...preview, summary: finalSummary } };
  } catch (error) {
    debug(`guardian hook failed: ${error instanceof Error ? error.message : String(error)}`);
    if (ctx.hasUI) {
      ctx.ui.notify(uiMessage(uiLanguage, "guardianUnavailable"), "warning");
    }
    // If the preview itself failed, returning undefined lets Pi run its normal
    // native path. A successful preview is always preferred over a failed retry.
    return undefined;
  }
}

export default function contextGuardianExtension(pi: ExtensionAPI) {
  pi.on("session_before_compact", handleBeforeCompact);
}
