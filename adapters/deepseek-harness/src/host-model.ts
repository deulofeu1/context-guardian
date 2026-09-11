import type { Context } from "@deepseek-ai/cordis";
import type { Agent } from "@deepseek-ai/dsh-agent";
import { BlockAssembler, createUserMessage, LlmError } from "@deepseek-ai/dsh-llm";

function extractJson(text: string): unknown {
  const trimmed = text.trim();
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
  return JSON.parse(fenced?.[1] ?? trimmed);
}

function routeFor(agent: Agent): { provider: string; model: string } {
  const config = agent.session.requestHeader()?.config;
  if (config === undefined || config.provider.length === 0 || config.model.length === 0) {
    throw new Error("DeepSeek Harness has no active provider/model route");
  }
  return { provider: config.provider, model: config.model };
}

function textFromBlocks(blocks: readonly { type: string; text?: string }[]): string {
  return blocks
    .filter((block) => block.type === "text" || block.type === "reasoning")
    .map((block) => block.text ?? "")
    .join("\n")
    .trim();
}

export async function generateStructuredWithHost(
  ctx: Context,
  agent: Agent,
  prompt: string,
  schema: Record<string, unknown>,
  signal: AbortSignal,
): Promise<unknown> {
  const route = routeFor(agent);
  const assembler = new BlockAssembler();
  const request = ctx.llm.stream({
    provider: route.provider,
    model: route.model,
    system: "You are a structured extraction service. Return only valid JSON matching the supplied JSON Schema. Do not use tools.",
    messages: [createUserMessage({
      content: [{
        type: "text",
        text: `${prompt}\n\nJSON Schema:\n${JSON.stringify(schema)}`,
      }],
      source: { kind: "plugin", plugin: "context-guardian-deepseek-harness" },
    })],
    maxTokens: 4096,
    sessionId: agent.session.id,
    purpose: "compaction",
    signal,
  });

  for await (const chunk of request) assembler.push(chunk);
  const finish = assembler.finish;
  if (finish.kind === "error" || finish.kind === "aborted") {
    throw new LlmError(finish.failure.message, finish.failure.code);
  }
  if (finish.kind === "max-tokens") {
    throw new Error("structured Context Guardian extraction reached the token cap");
  }

  const text = textFromBlocks(assembler.blocks());
  if (text.length === 0) throw new Error("DeepSeek Harness returned no structured extraction text");
  return extractJson(text);
}
