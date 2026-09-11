import { createInterface } from "node:readline";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { generateStructuredWithHost } from "./host-model.ts";
import type { Guidance, GuardianMessage, InspectionResult, MemoryCandidate, ProtocolFrame } from "./types.ts";

const PROTOCOL_VERSION = 1;
const DEFAULT_TIMEOUT_MS = 30_000;

export class GuardianBridgeError extends Error {}

function pythonCommand(): string {
  return process.env.CONTEXT_GUARDIAN_PYTHON || "python3";
}

function pythonEnvironment(): NodeJS.ProcessEnv {
  const environment: NodeJS.ProcessEnv = {};
  for (const name of ["PATH", "LANG", "LC_ALL", "TMPDIR", "TMP", "TEMP"]) {
    const value = process.env[name];
    if (value !== undefined) environment[name] = value;
  }
  const pythonPath = process.env.CONTEXT_GUARDIAN_PYTHONPATH;
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

export class GuardianBridge {
  async inspect(
    ctx: ExtensionContext,
    messages: GuardianMessage[],
    signal: AbortSignal,
    timeoutMs = DEFAULT_TIMEOUT_MS,
  ): Promise<InspectionResult> {
    const result = await this.request(ctx, "inspect", { messages, provider: "host" }, signal, timeoutMs);
    return result as InspectionResult;
  }

  async guidance(
    ctx: ExtensionContext,
    candidates: MemoryCandidate[],
    decisions: Array<{ candidate_id: string; action: "keep" | "drop" }>,
    signal: AbortSignal,
    timeoutMs = DEFAULT_TIMEOUT_MS,
  ): Promise<Guidance> {
    const result = await this.request(ctx, "guidance", { candidates, decisions, provider: "rules" }, signal, timeoutMs);
    return result as Guidance;
  }

  private async request(
    ctx: ExtensionContext,
    operation: "inspect" | "guidance",
    body: Record<string, unknown>,
    signal: AbortSignal,
    timeoutMs: number,
  ): Promise<unknown> {
    const child = spawn(pythonCommand(), ["-m", "context_guardian", "bridge", "--stdio"], {
      cwd: ctx.cwd,
      shell: false,
      env: pythonEnvironment(),
      stdio: ["pipe", "pipe", "pipe"],
    });

    const requestId = randomUUID();
    const readline = createInterface({ input: child.stdout });
    let stderr = "";
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk).slice(-4000);
    });

    const abort = () => child.kill("SIGTERM");
    signal.addEventListener("abort", abort, { once: true });
    const timer = setTimeout(() => child.kill("SIGTERM"), timeoutMs);

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
          throw new GuardianBridgeError("Context Guardian returned invalid JSON");
        }

        if (frame.type === "error") {
          throw new GuardianBridgeError(frame.error ?? "Context Guardian protocol error");
        }

        if (frame.type === "provider_request") {
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

        if (frame.type !== "result" || frame.request_id !== requestId) continue;
        if (!frame.ok) throw new GuardianBridgeError(frame.error ?? "Context Guardian request failed");
        return frame.result;
      }
      throw new GuardianBridgeError(stderr || "Context Guardian process exited without a result");
    } finally {
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      readline.close();
      if (!child.killed) child.kill("SIGTERM");
    }
  }
}
