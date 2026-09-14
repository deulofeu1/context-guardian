import { BasicCompactionEngine } from "@deepseek-ai/dsh-compaction-basic";
import type { Agent } from "@deepseek-ai/dsh-agent";
import type { ReviewPlan } from "./types.js";
export declare const name = "context-guardian-deepseek-harness";
type NativeSummarize = BasicCompactionEngine["summarize"];
type NativeSummarizeInput = Parameters<NativeSummarize>[0];
type NativeSummarizeResult = Awaited<ReturnType<NativeSummarize>>;
type UiLanguage = "zh-CN" | "en";
type UiMessageKey = "auditUnavailable" | "reviewCancelled" | "factsUnavailable";
export declare function uiMessageWithError(language: UiLanguage, key: UiMessageKey, error: unknown): string;
export declare function answersForNoUi(plan: ReviewPlan): Array<{
    question_id: string;
    topic_id: string;
    action: "keep" | "drop";
}>;
/**
 * Decorates the native DeepSeek Harness compactor. The native engine owns the
 * single transaction; this override only performs an uncommitted preview,
 * an external audit, and a deterministic append to the returned summary.
 */
export declare class ContextGuardianCompactionEngine extends BasicCompactionEngine {
    static inject: string[];
    protected summarize(input: NativeSummarizeInput, agent: Agent, signal?: AbortSignal): Promise<NativeSummarizeResult>;
}
export default ContextGuardianCompactionEngine;
//# sourceMappingURL=index.d.ts.map