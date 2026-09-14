import { createInterface } from "node:readline";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import type { Context } from "@deepseek-ai/cordis";
import type { Agent } from "@deepseek-ai/dsh-agent";
import { generateStructuredWithHost } from "./host-model.js";
import type {
  Guidance,
  GuardianMessage,
  InspectionResult,
  MemoryCandidate,
  ProtocolFrame,
  ReviewPlan,
  ReviewedFactsAppendix,
} from "./types.js";

const PROTOCOL_VERSION = 1;
const DEFAULT_TIMEOUT_MS = 120_000;
const MAX_TIMEOUT_MS = 120_000;
const BASE_ENVIRONMENT_NAMES = ["PATH", "LANG", "LC_ALL", "TMPDIR", "TMP", "TEMP"] as const;
const WINDOWS_ENVIRONMENT_NAMES = ["SystemRoot", "windir"] as const;

export type GuardianBridgeErrorCode = "spawn" | "timeout" | "protocol" | "process_exit";

export class GuardianBridgeError extends Error {
  constructor(message: string, readonly code: GuardianBridgeErrorCode) {
    super(message);
    this.name = "GuardianBridgeError";
  }
}

export function pythonCommand(
  source: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
): string {
  return source.CONTEXT_GUARDIAN_PYTHON || (platform === "win32" ? "python" : "python3");
}

function timeoutMs(): number {
  const value = Number(process.env.CONTEXT_GUARDIAN_TIMEOUT_MS ?? DEFAULT_TIMEOUT_MS);
  return Number.isFinite(value) && value > 0 ? Math.min(Math.floor(value), MAX_TIMEOUT_MS) : DEFAULT_TIMEOUT_MS;
}

export function pythonEnvironment(
  source: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
): NodeJS.ProcessEnv {
  const environment: NodeJS.ProcessEnv = {};
  const names = platform === "win32"
    ? [...WINDOWS_ENVIRONMENT_NAMES, ...BASE_ENVIRONMENT_NAMES]
    : BASE_ENVIRONMENT_NAMES;
  for (const name of names) {
    const value = source[name];
    if (value !== undefined) environment[name] = value;
  }
  const pythonPath = source.CONTEXT_GUARDIAN_PYTHONPATH;
  if (pythonPath !== undefined) environment.PYTHONPATH = pythonPath;
  return environment;
}

export function normalizeDeepSeekMessages(
  _system: string | undefined,
  messages: readonly any[],
): GuardianMessage[] {
  const result: GuardianMessage[] = [];

  for (const [index, message] of messages.entries()) {
    if (message.role === "system") continue;
    const sourceKind = message.source?.kind;
    const role = sourceKind === "tool" ? "tool" : String(message.role ?? "unknown");
    const blocks = Array.isArray(message.content) ? message.content : [message.content];
    const content = blocks.map((block: any) => {
      if (typeof block === "string") return block;
      if (block?.type === "text" || block?.type === "reasoning") return String(block.text ?? "");
      if (block?.type === "tool-call") return `Tool call ${String(block.name ?? "")}: ${String(block.arguments ?? "")}`;
      if (block?.type === "tool-result") {
        const inner = Array.isArray(block.content) ? block.content : [];
        return inner.map((item: any) => item?.type === "text" ? String(item.text ?? "") : "").join("\n");
      }
      return "";
    }).filter(Boolean).join("\n").trim();
    if (!content) continue;

    const error = blocks.some((block: any) => block?.type === "tool-result" && block.isError === true);
    result.push({
      role,
      content,
      id: String(message.id ?? `dsh_message_${String(index + 1).padStart(4, "0")}`),
      is_error: error,
      metadata: { source: sourceKind },
    });
  }
  return result;
}

export function preferredLanguage(messages: readonly GuardianMessage[]): "zh-CN" | "en" {
  const userText = messages
    .filter((message) => message.role === "user")
    .map((message) => message.content)
    .join(" ");
  const chinese = (userText.match(/[\u4e00-\u9fff]/g) ?? []).length;
  // Count Latin words rather than individual letters. Technical names such as
  // "Context Guardian" and "public API" must not outweigh Chinese prose.
  const latin = (userText.match(/\b[A-Za-z][A-Za-z0-9_'-]*\b/g) ?? []).length;
  return chinese > latin ? "zh-CN" : "en";
}

export class GuardianBridge {
  async inspect(
    ctx: Context,
    agent: Agent,
    messages: GuardianMessage[],
    signal: AbortSignal,
  ): Promise<InspectionResult> {
    const result = await this.request(ctx, agent, "inspect", { messages, provider: "host" }, signal);
    return result as InspectionResult;
  }

  async guidance(
    ctx: Context,
    agent: Agent,
    candidates: MemoryCandidate[],
    decisions: Array<{ candidate_id: string; action: "keep" | "drop" }>,
    signal: AbortSignal,
  ): Promise<Guidance> {
    const result = await this.request(ctx, agent, "guidance", {
      candidates,
      decisions,
      provider: "rules",
    }, signal);
    return result as Guidance;
  }

  async auditPreview(
    ctx: Context,
    agent: Agent,
    messages: GuardianMessage[],
    preview: string,
    previousSummary: string,
    retainedContext: string,
    signal: AbortSignal,
    maxReviewQuestions = 3,
  ): Promise<ReviewPlan> {
    const result = await this.request(ctx, agent, "audit_preview", {
      messages,
      preview,
      previous_summary: previousSummary,
      retained_context: retainedContext,
      max_review_questions: maxReviewQuestions,
      language: preferredLanguage(messages),
      provider: "host",
    }, signal);
    return result as ReviewPlan;
  }

  async revisionGuidance(
    ctx: Context,
    agent: Agent,
    reviewPlan: ReviewPlan,
    answers: Array<{ question_id: string; topic_id: string; action: "keep" | "drop" }>,
    signal: AbortSignal,
  ): Promise<Guidance> {
    const result = await this.request(ctx, agent, "revision_guidance", {
      review_plan: reviewPlan,
      answers,
    }, signal);
    return result as Guidance;
  }

  async buildReviewedFacts(
    ctx: Context,
    agent: Agent,
    reviewPlan: ReviewPlan,
    answers: Array<{ question_id: string; topic_id: string; action: "keep" | "drop" }>,
    signal: AbortSignal,
  ): Promise<ReviewedFactsAppendix> {
    const result = await this.request(ctx, agent, "build_reviewed_facts", {
      review_plan: reviewPlan,
      answers,
    }, signal);
    return result as ReviewedFactsAppendix;
  }

  private async request(
    ctx: Context,
    agent: Agent,
    operation: "inspect" | "guidance" | "audit_preview" | "revision_guidance" | "build_reviewed_facts",
    body: Record<string, unknown>,
    signal: AbortSignal,
  ): Promise<unknown> {
    const command = pythonCommand();
    const child = spawn(command, ["-m", "context_guardian", "bridge", "--stdio"], {
      cwd: agent.session.header.cwd ?? process.cwd(),
      shell: false,
      env: pythonEnvironment(),
      stdio: ["pipe", "pipe", "pipe"],
    });
    const requestId = randomUUID();
    const readline = createInterface({ input: child.stdout });
    let stderr = "";
    let childError: Error | undefined;
    let timedOut = false;
    child.once("error", (error) => { childError = error; });
    child.stderr.on("data", (chunk) => { stderr = `${stderr}${String(chunk)}`.slice(-4000); });

    const abort = () => child.kill("SIGTERM");
    signal.addEventListener("abort", abort, { once: true });
    const limit = timeoutMs();
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
    }, limit);

    try {
      child.stdin.write(JSON.stringify({
        protocol_version: PROTOCOL_VERSION,
        type: "request",
        request_id: requestId,
        operation,
        ...body,
      }) + "\n");

      for await (const line of readline) {
        if (!line.trim()) continue;
        let frame: ProtocolFrame;
        try {
          frame = JSON.parse(line) as ProtocolFrame;
        } catch {
          throw new GuardianBridgeError("Context Guardian returned invalid JSON", "protocol");
        }
        if (frame.protocol_version !== PROTOCOL_VERSION) {
          throw new GuardianBridgeError("Context Guardian returned an unsupported protocol version", "protocol");
        }
        if (frame.type === "error") {
          throw new GuardianBridgeError(frame.error ?? "Context Guardian protocol error", "protocol");
        }

        if (frame.type === "provider_request") {
          if (!frame.request_id || !frame.prompt || !frame.schema) {
            throw new GuardianBridgeError("Context Guardian provider request is malformed", "protocol");
          }
          try {
            const data = await generateStructuredWithHost(ctx, agent, frame.prompt, frame.schema, signal);
            child.stdin.write(JSON.stringify({
              protocol_version: PROTOCOL_VERSION,
              type: "provider_response",
              request_id: frame.request_id,
              ok: true,
              data,
            }) + "\n");
          } catch (error) {
            child.stdin.write(JSON.stringify({
              protocol_version: PROTOCOL_VERSION,
              type: "provider_response",
              request_id: frame.request_id,
              ok: false,
              error: error instanceof Error ? error.message : String(error),
            }) + "\n");
          }
          continue;
        }

        if (frame.type !== "result" || frame.request_id !== requestId) {
          throw new GuardianBridgeError("Context Guardian returned an unrelated response", "protocol");
        }
        if (!frame.ok) {
          throw new GuardianBridgeError(frame.error ?? "Context Guardian request failed", "protocol");
        }
        return frame.result;
      }
      if (childError) {
        throw new GuardianBridgeError(
          `Context Guardian failed to start ${JSON.stringify(command)}: ${childError.message}`,
          "spawn",
        );
      }
      if (timedOut) {
        throw new GuardianBridgeError(`Context Guardian timed out after ${String(limit)} ms`, "timeout");
      }
      throw new GuardianBridgeError(stderr || "Context Guardian process exited without a result", "process_exit");
    } finally {
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      readline.close();
      if (!child.killed) child.kill("SIGTERM");
    }
  }
}
