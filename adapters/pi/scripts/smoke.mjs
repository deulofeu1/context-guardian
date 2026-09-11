import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(packageRoot, "../..");
const extension = resolve(packageRoot, "extensions/context-guardian.ts");
const piCommand = process.env.CONTEXT_GUARDIAN_PI ||
  (existsSync(resolve(repositoryRoot, "node_modules/.bin/pi"))
    ? resolve(repositoryRoot, "node_modules/.bin/pi")
    : "pi");
const pythonCandidates = [
  process.env.CONTEXT_GUARDIAN_PYTHON,
  resolve(repositoryRoot, ".venv313/bin/python"),
  resolve(repositoryRoot, ".venv/bin/python"),
  "python3",
  "python",
].filter(Boolean);

function requestLine(command, args, input, isMatch, timeoutMs = 10_000) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, { cwd: repositoryRoot, stdio: ["pipe", "pipe", "pipe"] });
    let buffer = "";
    let stderr = "";
    let settled = false;
    const finish = (callback) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      child.kill("SIGTERM");
      callback();
    };
    const timer = setTimeout(() => finish(() => reject(new Error(`${command} smoke test timed out`))), timeoutMs);
    child.stdout.on("data", (chunk) => {
      buffer += String(chunk);
      while (buffer.includes("\n")) {
        const newline = buffer.indexOf("\n");
        const line = buffer.slice(0, newline).replace(/\r$/, "");
        buffer = buffer.slice(newline + 1);
        if (line && isMatch(line)) finish(() => resolvePromise(line));
      }
    });
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("error", (error) => {
      finish(() => reject(error));
    });
    child.on("close", (code) => {
      if (settled) return;
      finish(() => reject(new Error(`${command} exited with ${code}: ${stderr || buffer}`)));
    });
    child.stdin.end(input);
  });
}

async function checkPiLoad() {
  const response = await requestLine(
    piCommand,
    ["--mode", "rpc", "--no-session", "--no-extensions", "-e", extension],
    '{"id":"context-guardian-smoke","type":"get_state"}\n',
    (line) => {
      try {
        const frame = JSON.parse(line);
        return frame.id === "context-guardian-smoke" && frame.type === "response";
      } catch {
        return false;
      }
    },
  );
  const frame = JSON.parse(response);
  if (!frame?.success) throw new Error("Pi did not return a successful RPC state response");
  return true;
}

async function checkBridge() {
  let lastError;
  for (const python of pythonCandidates) {
    try {
      const output = await requestLine(
        python,
        ["-m", "context_guardian", "bridge", "--stdio"],
        JSON.stringify({
          protocol_version: 1,
          type: "request",
          request_id: "context-guardian-bridge-smoke",
          operation: "inspect",
          provider: "rules",
          messages: [{ role: "user", content: "The goal is to keep the public API unchanged." }],
        }) + "\n",
        (line) => line.trim().startsWith('{"protocol_version":'),
      );
      const frame = JSON.parse(output);
      if (!frame.ok || frame.request_id !== "context-guardian-bridge-smoke") {
        throw new Error("Python bridge returned an unsuccessful response");
      }
      return true;
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("No Python interpreter was available");
}

try {
  await checkBridge();
  await checkPiLoad();
  console.log(JSON.stringify({ passed: true, checks: { python_bridge: true, pi_rpc_extension_load: true } }));
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
