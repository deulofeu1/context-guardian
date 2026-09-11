import { createInterface } from "node:readline";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import type { Context } from "@deepseek-ai/cordis";
import type { Agent } from "@deepseek-ai/dsh-agent";
import { generateStructuredWithHost } from "./host-model.js";
import type { Guidance, GuardianMessage, InspectionResult, MemoryCandidate, ProtocolFrame } from "./types.js";

const PROTOCOL_VERSION = 1;
const DEFAULT_TIMEOUT_MS = 30_000;

export class GuardianBridgeError extends Error {}

function pythonCommand(): string {
  return process.env.CONTEXT_GUARDIAN_PYTHON || "python3";
}

function timeoutMs(): number {
  const value = Number(process.env.CONTEXT_GUARDIAN_TIMEOUT_MS ?? DEFAULT_TIMEOUT_MS);
  return Number.isFinite(value) && value > 0 ? Math.min(Math.floor(value), 120_000) : DEFAULT_TIMEOUT_MS;
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

  private async request(
    ctx: Context,
    agent: Agent,
    operation: "inspect" | "guidance",
    body: Record<string, unknown>,
    signal: AbortSignal,
  ): Promise<unknown> {
    const child = spawn(pythonCommand(), ["-m", "context_guardian", "bridge", "--stdio"], {
      cwd: agent.session.header.cwd ?? process.cwd(),
      shell: false,
      env: pythonEnvironment(),
      stdio: ["pipe", "pipe", "pipe"],
    });
    const requestId = randomUUID();
    const readline = createInterface({ input: child.stdout });
    let stderr = "";
    child.stderr.on("data", (chunk) => { stderr = `${stderr}${String(chunk)}`.slice(-4000); });

    const abort = () => child.kill("SIGTERM");
    signal.addEventListener("abort", abort, { once: true });
    const timer = setTimeout(() => child.kill("SIGTERM"), timeoutMs());

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
          throw new GuardianBridgeError("Context Guardian returned invalid JSON");
        }
        if (frame.protocol_version !== PROTOCOL_VERSION) {
          throw new GuardianBridgeError("Context Guardian returned an unsupported protocol version");
        }
        if (frame.type === "error") throw new GuardianBridgeError(frame.error ?? "Context Guardian protocol error");

        if (frame.type === "provider_request") {
          if (!frame.request_id || !frame.prompt || !frame.schema) {
            throw new GuardianBridgeError("Context Guardian provider request is malformed");
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
          throw new GuardianBridgeError("Context Guardian returned an unrelated response");
        }
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
