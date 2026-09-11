import {
  compact,
  type ExtensionAPI,
  type ExtensionContext,
  type SessionBeforeCompactEvent,
} from "@earendil-works/pi-coding-agent";
import { GuardianBridge, normalizePiMessages } from "../src/bridge.ts";
import type { MemoryCandidate } from "../src/types.ts";

const bridge = new GuardianBridge();

function formatCandidate(candidate: MemoryCandidate): string {
  const reason = candidate.reason ? `\n\nReason: ${candidate.reason}` : "";
  const scores = `Importance: ${candidate.importance.toFixed(2)} · Confidence: ${candidate.confidence.toFixed(2)}`;
  return `[${candidate.category}]\n${candidate.content}\n\n${scores}${reason}`;
}

async function reviewCandidates(
  ctx: ExtensionContext,
  candidates: MemoryCandidate[],
  signal: AbortSignal,
): Promise<Array<{ candidate_id: string; action: "keep" | "drop" }>> {
  if (!ctx.hasUI) {
    return candidates.map((candidate) => ({ candidate_id: candidate.id, action: "keep" as const }));
  }

  const decisions: Array<{ candidate_id: string; action: "keep" | "drop" }> = [];
  for (const candidate of candidates) {
    if (signal.aborted) throw new Error("review aborted");
    const keep = await ctx.ui.confirm("Context Guardian review", `Keep this memory?\n\n${formatCandidate(candidate)}`);
    decisions.push({ candidate_id: candidate.id, action: keep ? "keep" : "drop" });
  }
  return decisions;
}

async function handleBeforeCompact(event: SessionBeforeCompactEvent, ctx: ExtensionContext) {
  try {
    if (!ctx.model) return;

    const messages = normalizePiMessages(event.preparation.messagesToSummarize, event.preparation.previousSummary);
    const inspection = await bridge.inspect(ctx, messages, event.signal);
    if (ctx.hasUI) {
      ctx.ui.notify(
        `Context Guardian: ${inspection.auto_keep.length} keep · ${inspection.auto_drop.length} drop · ` +
          `${inspection.review.length} review`,
        "info",
      );
    }

    const decisions = await reviewCandidates(ctx, inspection.review, event.signal);
    const guidance = await bridge.guidance(ctx, inspection.candidates, decisions, event.signal);
    const auth = await ctx.modelRegistry.getApiKeyAndHeaders(ctx.model);
    if (!auth.ok) return;

    const headers = auth.headers
      ? Object.fromEntries(Object.entries(auth.headers).filter((entry): entry is [string, string] => entry[1] !== null))
      : undefined;
    const customInstructions = [event.customInstructions, guidance.text].filter(Boolean).join("\n\n");
    const nativeResult = await compact(
      event.preparation,
      ctx.model,
      auth.apiKey,
      headers,
      customInstructions,
      event.signal,
      ctx.thinkingLevel,
    );
    return { compaction: nativeResult };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (ctx.hasUI) {
      ctx.ui.notify(`Context Guardian unavailable; continuing native compaction (${message})`, "warning");
    }
    // Fail open: returning undefined lets Pi run its normal compaction path.
    return undefined;
  }
}

export default function contextGuardianExtension(pi: ExtensionAPI) {
  pi.on("session_before_compact", handleBeforeCompact);
}
