import type { Context } from "@deepseek-ai/cordis";
import type { Agent } from "@deepseek-ai/dsh-agent";
import type { Guidance, GuardianMessage, InspectionResult, MemoryCandidate, ReviewPlan, ReviewedFactsAppendix } from "./types.js";
export type GuardianBridgeErrorCode = "spawn" | "timeout" | "aborted" | "protocol" | "process_exit";
export declare class GuardianBridgeError extends Error {
    readonly code: GuardianBridgeErrorCode;
    constructor(message: string, code: GuardianBridgeErrorCode);
}
export declare function pythonCommand(source?: NodeJS.ProcessEnv, platform?: NodeJS.Platform): string;
export declare function pythonEnvironment(source?: NodeJS.ProcessEnv, platform?: NodeJS.Platform): NodeJS.ProcessEnv;
export declare function normalizeDeepSeekMessages(_system: string | undefined, messages: readonly any[]): GuardianMessage[];
export declare function preferredLanguage(messages: readonly GuardianMessage[]): "zh-CN" | "en";
export declare class GuardianBridge {
    inspect(ctx: Context, agent: Agent, messages: GuardianMessage[], signal: AbortSignal): Promise<InspectionResult>;
    guidance(ctx: Context, agent: Agent, candidates: MemoryCandidate[], decisions: Array<{
        candidate_id: string;
        action: "keep" | "drop";
    }>, signal: AbortSignal): Promise<Guidance>;
    auditPreview(ctx: Context, agent: Agent, messages: GuardianMessage[], preview: string, previousSummary: string, retainedContext: string, signal: AbortSignal, maxReviewQuestions?: number): Promise<ReviewPlan>;
    revisionGuidance(ctx: Context, agent: Agent, reviewPlan: ReviewPlan, answers: Array<{
        question_id: string;
        topic_id: string;
        action: "keep" | "drop";
    }>, signal: AbortSignal): Promise<Guidance>;
    buildReviewedFacts(ctx: Context, agent: Agent, reviewPlan: ReviewPlan, answers: Array<{
        question_id: string;
        topic_id: string;
        action: "keep" | "drop";
    }>, messages: GuardianMessage[], signal: AbortSignal): Promise<ReviewedFactsAppendix>;
    private request;
}
//# sourceMappingURL=bridge.d.ts.map