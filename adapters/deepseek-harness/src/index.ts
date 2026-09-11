import type { Context } from "@deepseek-ai/cordis";
import { BasicCompactionEngine } from "@deepseek-ai/dsh-compaction-basic";
import type { Agent } from "@deepseek-ai/dsh-agent";
import { createUserMessage } from "@deepseek-ai/dsh-llm";
import type {} from "@deepseek-ai/dsh-user-questions";
import type { GuardianMessage, InspectionResult, MemoryCandidate } from "./types.js";
import { GuardianBridge, normalizeDeepSeekMessages } from "./bridge.js";

export const name = "context-guardian-deepseek-harness";

if (process.env.CONTEXT_GUARDIAN_DEBUG === "1") {
  console.error("context guardian: adapter module loaded");
}

type NativeSummarize = BasicCompactionEngine["summarize"];
type NativeSummarizeInput = Parameters<NativeSummarize>[0];
type NativeSummarizeResult = Awaited<ReturnType<NativeSummarize>>;

const bridge = new GuardianBridge();
const KEEP = "Keep";
const DROP = "Drop";

function debug(ctx: Context, message: string): void {
  if (process.env.CONTEXT_GUARDIAN_DEBUG === "1") {
    const line = `context guardian: ${message}`;
    console.error(line);
    ctx.logger.info(line);
  }
}

function candidateDetail(candidate: MemoryCandidate): string {
  const reason = candidate.reason ? `\n\nReason: ${candidate.reason}` : "";
  return `Category: ${candidate.category}\nImportance: ${candidate.importance.toFixed(2)} · Confidence: ${candidate.confidence.toFixed(2)}\n\n${candidate.content}${reason}`;
}

function reviewQuestions(candidates: readonly MemoryCandidate[]) {
  return candidates.map((candidate) => ({
    id: candidate.id,
    header: `Context Guardian · ${candidate.category}`,
    question: "Keep this memory in the compaction guidance?",
    detail: candidateDetail(candidate),
    options: [
      { label: KEEP, description: "Tell the native compactor to preserve this item." },
      { label: DROP, description: "Tell the native compactor this item may be discarded." },
    ],
  }));
}

function keepAll(candidates: readonly MemoryCandidate[]): Array<{ candidate_id: string; action: "keep" }> {
  return candidates.map((candidate) => ({ candidate_id: candidate.id, action: "keep" as const }));
}

function errorCode(error: unknown): string | undefined {
  return typeof error === "object" && error !== null && "code" in error
    ? String((error as { code?: unknown }).code)
    : undefined;
}

async function review(
  ctx: Context,
  agent: Agent,
  candidates: readonly MemoryCandidate[],
  signal: AbortSignal,
): Promise<Array<{ candidate_id: string; action: "keep" | "drop" }>> {
  if (candidates.length === 0) return [];
  const mode = process.env.CONTEXT_GUARDIAN_REVIEW_MODE;
  if (mode === "keep") return keepAll(candidates);
  if (mode === "drop") return candidates.map((candidate) => ({ candidate_id: candidate.id, action: "drop" as const }));

  const interaction = ctx.get("userQuestions");
  debug(ctx, `reviewing ${String(candidates.length)} candidate(s); userQuestions=${interaction === undefined ? "unavailable" : "available"}`);
  if (interaction === undefined) return keepAll(candidates);
  try {
    const answer = await interaction.ask({
      questions: reviewQuestions(candidates),
      agent,
      signal,
    });
    const byId = new Map(answer.answers.map((item) => [item.id, item]));
    return candidates.map((candidate) => {
      const item = byId.get(candidate.id);
      if (item?.custom !== undefined || item?.selected.length !== 1) {
        throw new Error(`Context Guardian received an invalid answer for ${candidate.id}`);
      }
      if (item.selected[0] === KEEP) return { candidate_id: candidate.id, action: "keep" as const };
      if (item.selected[0] === DROP) return { candidate_id: candidate.id, action: "drop" as const };
      throw new Error(`Context Guardian received an unknown answer for ${candidate.id}`);
    });
  } catch (error) {
    debug(ctx, `userQuestions failed with ${errorCode(error) ?? (error instanceof Error ? error.message : String(error))}`);
    // Headless compositions commonly provide the service seam without a UI
    // answerer. Treat that case conservatively; an explicit cancellation or
    // protocol failure is allowed to fail open to native compaction below.
    if (errorCode(error) === "NO_PROVIDER") return keepAll(candidates);
    throw error;
  }
}

function nativeInputWithGuidance(input: NativeSummarizeInput, text: string): NativeSummarizeInput {
  const guidanceMessage = createUserMessage({
    content: [{ type: "text", text }],
    source: { kind: "plugin", plugin: name },
  });
  return {
    ...input,
    messages: [...input.messages, guidanceMessage],
  } as NativeSummarizeInput;
}

function normalizeInput(input: NativeSummarizeInput): GuardianMessage[] {
  const candidate = input as NativeSummarizeInput & { system?: string };
  return normalizeDeepSeekMessages(candidate.system, input.messages);
}

/**
 * Decorates DeepSeek Harness's native backend with Context Guardian review.
 * The inherited engine still owns selection, shrink checks, durable markers,
 * session replacement, and the final structured checkpoint summary.
 */
export class ContextGuardianCompactionEngine extends BasicCompactionEngine {
  protected override async summarize(
    input: NativeSummarizeInput,
    agent: Agent,
    signal?: AbortSignal,
  ): Promise<NativeSummarizeResult> {
    let guidedInput: NativeSummarizeInput;
    try {
      const operationSignal = signal ?? new AbortController().signal;
      const inspection: InspectionResult = await bridge.inspect(
        this.ctx,
        agent,
        normalizeInput(input),
        operationSignal,
      );
      debug(this.ctx, `inspection returned ${String(inspection.candidates.length)} candidate(s), ${String(inspection.review.length)} for review`);
      const decisions = [
        ...keepAll(inspection.auto_keep),
        ...inspection.auto_drop.map((candidate) => ({ candidate_id: candidate.id, action: "drop" as const })),
        ...await review(this.ctx, agent, inspection.review, operationSignal),
      ];
      const guidance = await bridge.guidance(
        this.ctx,
        agent,
        inspection.candidates,
        decisions,
        operationSignal,
      );
      guidedInput = nativeInputWithGuidance(input, guidance.text);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.ctx.logger.warn(`context guardian unavailable; continuing native compaction: ${message}`);
      return super.summarize(input, agent, signal);
    }
    return super.summarize(guidedInput, agent, signal);
  }
}

export default ContextGuardianCompactionEngine;
