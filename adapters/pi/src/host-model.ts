import { contentText } from "@earendil-works/pi-ai";
import { completeSimple } from "@earendil-works/pi-ai/compat";
import type { Context, Model, ThinkingLevel } from "@earendil-works/pi-ai/compat";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";

function extractJson(text: string): unknown {
  const trimmed = text.trim();
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
  return JSON.parse(fenced?.[1] ?? trimmed);
}
function cleanHeaders(headers: Record<string, string | null> | undefined): Record<string, string> | undefined {
  if (!headers) return undefined;
  return Object.fromEntries(Object.entries(headers).filter((entry): entry is [string, string] => entry[1] !== null));
}

function auditReasoning(model: Model<any>): ThinkingLevel | undefined {
  if (!model.reasoning || model.thinkingLevelMap?.off !== null) return undefined;
  const supported: ThinkingLevel[] = ["minimal", "low", "medium", "high", "xhigh", "max"];
  return supported.find((level) => model.thinkingLevelMap?.[level] !== null);
}

function debug(message: string): void {
  if (process.env.CONTEXT_GUARDIAN_DEBUG === "1") console.error(`context guardian: ${message}`);
}

export async function generateStructuredWithHost(
  ctx: ExtensionContext,
  prompt: string,
  schema: Record<string, unknown>,
  signal: AbortSignal,
): Promise<unknown> {
  const model = ctx.model as Model<any> | undefined;
  if (!model) throw new Error("Pi has no active model");

  const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model);
  if (!auth.ok) throw new Error(auth.error ?? "Pi could not resolve model authentication");

  const context: Context = {
    systemPrompt:
      "You are a structured extraction service. Return only valid JSON that matches the supplied JSON Schema. Do not use tools.",
    messages: [
      {
        role: "user",
        content: [
          {
            type: "text",
            text: `${prompt}\n\nJSON Schema:\n${JSON.stringify(schema)}`,
          },
        ],
        timestamp: Date.now(),
      },
    ],
  };

  const response = await completeSimple(model, context, {
    apiKey: auth.apiKey,
    headers: cleanHeaders(auth.headers),
    signal,
    // Keep audit extraction independent from the user's main-session budget.
    // Pi's API emits the provider's disabled-thinking request when reasoning is
    // omitted and the model advertises an `off` mapping.
    ...(auditReasoning(model) === undefined ? {} : { reasoning: auditReasoning(model) }),
    maxTokens: Math.min(model.maxTokens || 8192, 8192),
  });
  debug(`host_response provider=${model.provider} model=${model.id} stop=${response.stopReason} textChars=${contentText(response.content).length}`);
  if (response.stopReason === "error" || response.stopReason === "aborted") {
    throw new Error(response.errorMessage ?? `Host model stopped with ${response.stopReason}`);
  }
  if (response.stopReason === "length") {
    throw new Error("Pi structured Context Guardian extraction reached the token cap");
  }
  const text = contentText(response.content);
  if (!text.trim()) throw new Error("Pi returned no visible structured extraction text");
  return extractJson(text);
}
