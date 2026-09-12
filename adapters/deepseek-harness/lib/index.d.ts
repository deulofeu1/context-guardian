import { BasicCompactionEngine } from "@deepseek-ai/dsh-compaction-basic";
import type { Agent } from "@deepseek-ai/dsh-agent";
import type { ReviewPlan } from "./types.js";
export declare const name = "context-guardian-deepseek-harness";
type NativeSummarize = BasicCompactionEngine["summarize"];
type NativeSummarizeInput = Parameters<NativeSummarize>[0];
type NativeSummarizeResult = Awaited<ReturnType<NativeSummarize>>;
export declare function answersForNoUi(plan: ReviewPlan): Array<{
    question_id: string;
    topic_id: string;
    action: "keep" | "drop";
}>;
export declare function needsRevision(plan: ReviewPlan, answers: readonly {
    action: "keep" | "drop";
}[]): boolean;
/**
 * Decorates the native DeepSeek Harness compactor. The native engine owns the
 * single transaction; this override only performs an uncommitted preview,
 * an external audit, and (when needed) one guided native retry.
 */
export declare class ContextGuardianCompactionEngine extends BasicCompactionEngine {
    protected summarize(input: NativeSummarizeInput, agent: Agent, signal?: AbortSignal): Promise<NativeSummarizeResult>;
}
export default ContextGuardianCompactionEngine;
//# sourceMappingURL=index.d.ts.map