import { createInterface } from "node:readline";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { generateStructuredWithHost } from "./host-model.ts";
import type { Guidance, GuardianMessage, InspectionResult, MemoryCandidate, ProtocolFrame, ReviewPlan } from "./types.ts";

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

function configuredTimeoutMs(): number {
  const value = Number(process.env.CONTEXT_GUARDIAN_TIMEOUT_MS ?? DEFAULT_TIMEOUT_MS);
  return Number.isFinite(value) && value > 0 ? Math.min(Math.floor(value), MAX_TIMEOUT_MS) : DEFAULT_TIMEOUT_MS;
}

function requestTimeoutMs(value: number): number {
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

function serializeMessage(message: any, index: number): GuardianMessage {
  const role = message.role === "toolResult" || message.role === "tool_result" ? "tool" : message.role;
  const content = typeof message.content === "string" ? message.content : JSON.stringify(message.content ?? "");
  return {
    role,
    content,
    id: `pi_message_${String(index + 1).padStart(4, "0")}`,
    is_error: Boolean(message.isError),
    tool_name: message.toolName,
  };
}

export function normalizePiMessages(messages: readonly any[], previousSummary?: string): GuardianMessage[] {
  const normalized = messages.map(serializeMessage);
  if (previousSummary) {
    normalized.unshift({ role: "assistant", content: previousSummary, id: "pi_previous_summary" });
  }
  return normalized;
}

export function preferredLanguage(messages: readonly GuardianMessage[]): "zh-CN" | "en" {
  const userText = messages
    .filter((message) => message.role === "user")
    .map((message) => message.content)
    .join(" ");
  const chinese = (userText.match(/[\u4e00-\u9fff]/g) ?? []).length;
  const latin = (userText.match(/[A-Za-z]/g) ?? []).length;
  return chinese > latin ? "zh-CN" : "en";
}

export class GuardianBridge {
  async inspect(
    ctx: ExtensionContext,
    messages: GuardianMessage[],
    signal: AbortSignal,
    timeoutMs = configuredTimeoutMs(),
  ): Promise<InspectionResult> {
    const result = await this.request(ctx, "inspect", { messages, provider: "host" }, signal, timeoutMs);
    return result as InspectionResult;
  }

  async guidance(
    ctx: ExtensionContext,
    candidates: MemoryCandidate[],
    decisions: Array<{ candidate_id: string; action: "keep" | "drop" }>,
    signal: AbortSignal,
    timeoutMs = configuredTimeoutMs(),
  ): Promise<Guidance> {
    const result = await this.request(ctx, "guidance", { candidates, decisions, provider: "rules" }, signal, timeoutMs);
    return result as Guidance;
  }

  async auditPreview(
    ctx: ExtensionContext,
    messages: GuardianMessage[],
    preview: string,
    previousSummary: string | undefined,
    retainedContext: string,
    signal: AbortSignal,
    maxReviewQuestions = 3,
    timeoutMs = configuredTimeoutMs(),
  ): Promise<ReviewPlan> {
    const result = await this.request(ctx, "audit_preview", {
      messages,
      preview,
      previous_summary: previousSummary ?? "",
      retained_context: retainedContext,
      max_review_questions: maxReviewQuestions,
      language: preferredLanguage(messages),
      provider: "host",
    }, signal, timeoutMs);
    return result as ReviewPlan;
  }

  async revisionGuidance(
    ctx: ExtensionContext,
    reviewPlan: ReviewPlan,
    answers: Array<{ question_id: string; topic_id: string; action: "keep" | "drop" }>,
    signal: AbortSignal,
    timeoutMs = configuredTimeoutMs(),
  ): Promise<Guidance> {
    const result = await this.request(ctx, "revision_guidance", {
      review_plan: reviewPlan,
      answers,
    }, signal, timeoutMs);
    return result as Guidance;
  }

  private async request(
    ctx: ExtensionContext,
    operation: "inspect" | "guidance" | "audit_preview" | "revision_guidance",
    body: Record<string, unknown>,
    signal: AbortSignal,
    timeoutMs: number,
  ): Promise<unknown> {
    const command = pythonCommand();
    const child = spawn(command, ["-m", "context_guardian", "bridge", "--stdio"], {
      cwd: ctx.cwd,
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
    child.stderr.on("data", (chunk) => {
      stderr = `${stderr}${String(chunk)}`.slice(-4000);
    });

    const abort = () => child.kill("SIGTERM");
    signal.addEventListener("abort", abort, { once: true });
    const limit = requestTimeoutMs(timeoutMs);
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
    }, limit);

    try {
      child.stdin.write(
        JSON.stringify({ protocol_version: PROTOCOL_VERSION, type: "request", request_id: requestId, operation, ...body }) + "\n",
      );

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
            const data = await generateStructuredWithHost(ctx, frame.prompt ?? "", frame.schema ?? {}, signal);
            child.stdin.write(
              JSON.stringify({
                protocol_version: PROTOCOL_VERSION,
                type: "provider_response",
                request_id: frame.request_id,
                ok: true,
                data,
              }) + "\n",
            );
          } catch (error) {
            child.stdin.write(
              JSON.stringify({
                protocol_version: PROTOCOL_VERSION,
                type: "provider_response",
                request_id: frame.request_id,
                ok: false,
                error: error instanceof Error ? error.message : String(error),
              }) + "\n",
            );
          }
          continue;
        }

        if (frame.type !== "result" || frame.request_id !== requestId) {
          throw new GuardianBridgeError("Context Guardian returned an unrelated response", "protocol");
        }
        if (!frame.ok) throw new GuardianBridgeError(frame.error ?? "Context Guardian request failed", "protocol");
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
