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
type UiMessageKey = "auditUnavailable" | "reviewCancelled" | "revisionUnavailable" | "finalFailed" | "guardianUnavailable";

const UI_MESSAGES: Record<UiLanguage, Record<UiMessageKey, string>> = {
  en: {
    auditUnavailable: "Context Guardian audit unavailable; using the successful native preview.",
    reviewCancelled: "Context Guardian review unavailable; using the successful native preview.",
    revisionUnavailable: "Context Guardian revision unavailable; using the successful native preview.",
    finalFailed: "Context Guardian final compaction failed; using the successful native preview.",
    guardianUnavailable: "Context Guardian unavailable; continuing with native compaction.",
  },
  "zh-CN": {
    auditUnavailable: "Context Guardian 审计不可用；将使用已经成功生成的原生预览。",
    reviewCancelled: "Context Guardian 人工审查不可用；将使用已经成功生成的原生预览。",
    revisionUnavailable: "Context Guardian 修正指导不可用；将使用已经成功生成的原生预览。",
    finalFailed: "Context Guardian 最终压缩失败；将使用已经成功生成的原生预览。",
    guardianUnavailable: "Context Guardian 不可用；继续使用宿主原生压缩。",
  },
};

function uiMessage(language: UiLanguage, key: UiMessageKey): string {
  return UI_MESSAGES[language][key];
}

function auditNotice(plan: ReviewPlan): string {
  return plan.language === "zh-CN"
    ? `${plan.overview} 自动修正：${String(plan.auto_corrections.length)} 项 · 人工问题：${String(plan.review_questions.length)} 个`
    : `${plan.overview} Auto corrections: ${String(plan.auto_corrections.length)} · `
      + `Review questions: ${String(plan.review_questions.length)}`;
}

function configuredReviewBudget(): number {
  const value = Number(process.env.CONTEXT_GUARDIAN_MAX_REVIEW_QUESTIONS ?? MAX_REVIEW_QUESTIONS);
  return Number.isInteger(value) && value >= 0 && value <= MAX_REVIEW_QUESTIONS ? value : MAX_REVIEW_QUESTIONS;
}

function questionBody(question: ReviewQuestion): string {
  const options = question.options.map((option) => `${option.label}: ${option.description}`).join("\n");
  return `${question.question}\n\n${question.context}\n\n${question.why_it_matters}\n\n${options}`;
}

export function answersForNoUi(plan: ReviewPlan): Array<{
  question_id: string;
  topic_id: string;
  action: "keep" | "drop";
}> {
  return plan.review_questions.map((question) => ({
    question_id: question.id,
    topic_id: question.topic_id,
    action: question.recommendation,
  }));
}

export function needsRevision(plan: ReviewPlan, answers: readonly { action: "keep" | "drop" }[]): boolean {
  return plan.auto_corrections.length > 0 || answers.some((answer) => answer.action === "keep");
}

async function answerReviewQuestions(
  ctx: ExtensionContext,
  plan: ReviewPlan,
  signal: AbortSignal,
): Promise<Array<{ question_id: string; topic_id: string; action: "keep" | "drop" }>> {
  if (!ctx.hasUI) return answersForNoUi(plan);

  const answers: Array<{ question_id: string; topic_id: string; action: "keep" | "drop" }> = [];
  for (const question of plan.review_questions.slice(0, MAX_REVIEW_QUESTIONS)) {
    if (signal.aborted) throw new Error("review aborted");
    const keep = await ctx.ui.confirm(question.title, questionBody(question));
    answers.push({
      question_id: question.id,
      topic_id: question.topic_id,
      action: keep ? "keep" : "drop",
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
  if (!ctx.model) return;

  const messages = normalizePiMessages(
    event.preparation.messagesToSummarize,
    event.preparation.previousSummary,
  );
  let uiLanguage: UiLanguage = preferredLanguage(messages);

  try {
    const auth = await ctx.modelRegistry.getApiKeyAndHeaders(ctx.model);
    if (!auth.ok) return;

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
      if (ctx.hasUI) {
        ctx.ui.notify(uiMessage(uiLanguage, "auditUnavailable"), "warning");
      }
      return { compaction: preview };
    }

    uiLanguage = plan.language;

    if (ctx.hasUI) {
      ctx.ui.notify(auditNotice(plan), "info");
    }

    let answers;
    try {
      answers = await answerReviewQuestions(ctx, plan, event.signal);
    } catch (error) {
      if (ctx.hasUI) {
        ctx.ui.notify(uiMessage(uiLanguage, "reviewCancelled"), "warning");
      }
      return { compaction: preview };
    }
    if (!needsRevision(plan, answers)) return { compaction: preview };

    let guidance;
    try {
      guidance = await bridge.revisionGuidance(ctx, plan, answers, event.signal);
    } catch (error) {
      if (ctx.hasUI) {
        ctx.ui.notify(uiMessage(uiLanguage, "revisionUnavailable"), "warning");
      }
      return { compaction: preview };
    }
    if (!guidance.text) return { compaction: preview };

    try {
      const customInstructions = [event.customInstructions, guidance.text].filter(Boolean).join("\n\n");
      const finalResult = await compact(
        event.preparation,
        ctx.model,
        auth.apiKey,
        headers,
        customInstructions,
        event.signal,
        ctx.thinkingLevel,
      );
      return { compaction: finalResult };
    } catch (error) {
      if (ctx.hasUI) {
        ctx.ui.notify(uiMessage(uiLanguage, "finalFailed"), "warning");
      }
      return { compaction: preview };
    }
  } catch (error) {
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
