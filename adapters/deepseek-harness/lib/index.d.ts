import { BasicCompactionEngine } from "@deepseek-ai/dsh-compaction-basic";
import type { Agent } from "@deepseek-ai/dsh-agent";
export declare const name = "context-guardian-deepseek-harness";
type NativeSummarize = BasicCompactionEngine["summarize"];
type NativeSummarizeInput = Parameters<NativeSummarize>[0];
type NativeSummarizeResult = Awaited<ReturnType<NativeSummarize>>;
/**
 * Decorates DeepSeek Harness's native backend with Context Guardian review.
 * The inherited engine still owns selection, shrink checks, durable markers,
 * session replacement, and the final structured checkpoint summary.
 */
export declare class ContextGuardianCompactionEngine extends BasicCompactionEngine {
    protected summarize(input: NativeSummarizeInput, agent: Agent, signal?: AbortSignal): Promise<NativeSummarizeResult>;
}
export default ContextGuardianCompactionEngine;
//# sourceMappingURL=index.d.ts.map