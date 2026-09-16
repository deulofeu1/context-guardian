import { BlockAssembler, createUserMessage, LlmError } from "@deepseek-ai/dsh-llm";
const STRUCTURED_MAX_TOKENS = 8192;
function extractJson(text) {
    const trimmed = text.trim();
    const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
    try {
        return JSON.parse(fenced?.[1] ?? trimmed);
    }
    catch (error) {
        throw new Error(`structured extraction returned invalid JSON: ${error instanceof Error ? error.message : String(error)}`);
    }
}
function routeFor(agent) {
    const config = agent.session.requestHeader()?.config;
    if (config === undefined || config.provider.length === 0 || config.model.length === 0) {
        throw new Error("DeepSeek Harness has no active provider/model route");
    }
    return { provider: config.provider, model: config.model };
}
function textFromBlocks(blocks) {
    return blocks
        // Reasoning is deliberately excluded. On DeepSeek it can consume the
        // entire output budget while producing no JSON visible to the bridge.
        .filter((block) => block.type === "text")
        .map((block) => block.text ?? "")
        .join("\n")
        .trim();
}
function chooseReasoningEffort(info) {
    const efforts = info?.reasoning?.efforts ?? [];
    const disabled = efforts.find((effort) => /^(off|disabled|none|false)$/i.test(String(effort.id)));
    if (disabled)
        return disabled.id;
    // If the adapter exposes no disabled mode, use its least expensive advertised
    // effort rather than inheriting the user's main-session reasoning setting.
    const preferred = ["minimal", "low", "medium", "high", "xhigh", "max"];
    return preferred.map((name) => efforts.find((effort) => String(effort.id).toLowerCase() === name)).find(Boolean)?.id
        ?? efforts[0]?.id;
}
function debug(message) {
    if (process.env.CONTEXT_GUARDIAN_DEBUG === "1")
        console.error(`context guardian: ${message}`);
}
export async function generateStructuredWithHost(ctx, agent, prompt, schema, signal) {
    const route = routeFor(agent);
    const modelInfo = typeof ctx.llm.resolveModelInfo === "function"
        ? await ctx.llm.resolveModelInfo(route.provider, route.model, signal)
        : undefined;
    const reasoningEffort = chooseReasoningEffort(modelInfo);
    debug(`host_request provider=${route.provider} model=${route.model} maxTokens=${STRUCTURED_MAX_TOKENS} reasoningEffort=${String(reasoningEffort ?? "omitted")}`);
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
        ...(reasoningEffort === undefined ? {} : { reasoningEffort }),
        maxTokens: STRUCTURED_MAX_TOKENS,
        sessionId: agent.session.id,
        purpose: "compaction",
        signal,
    });
    for await (const chunk of request)
        assembler.push(chunk);
    const finish = assembler.finish;
    if (finish.kind === "error" || finish.kind === "aborted") {
        throw new LlmError(finish.failure.message, finish.failure.code);
    }
    if (finish.kind === "max-tokens") {
        throw new Error(`structured Context Guardian extraction reached the ${STRUCTURED_MAX_TOKENS}-token cap`);
    }
    const text = textFromBlocks(assembler.blocks());
    debug(`host_response finish=${finish.kind} textChars=${text.length} reasoningChars=${assembler.blocks().filter((block) => block.type === "reasoning").reduce((total, block) => total + (block.text?.length ?? 0), 0)}`);
    if (text.length === 0)
        throw new Error("DeepSeek Harness returned no visible structured extraction text");
    return extractJson(text);
}
//# sourceMappingURL=host-model.js.map