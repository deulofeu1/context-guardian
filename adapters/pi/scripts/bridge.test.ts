import assert from "node:assert/strict";
import { resolve } from "node:path";
import test from "node:test";
import {
  GuardianBridge,
  normalizePiMessages,
  pythonCommand,
  pythonEnvironment,
} from "../src/bridge.ts";

const repositoryRoot = resolve(new URL("../../../", import.meta.url).pathname);

test("Pi message normalization keeps stable ids and previous summaries", () => {
  const messages = normalizePiMessages([
    { role: "user", content: "Implement OAuth." },
    { role: "toolResult", content: "temporary failure", isError: true, toolName: "grep" },
  ], "The project must keep the public API unchanged.");

  assert.equal(messages[0].id, "pi_previous_summary");
  assert.equal(messages[0].content, "The project must keep the public API unchanged.");
  assert.equal(messages[1].id, "pi_message_0001");
  assert.equal(messages[2].role, "tool");
  assert.equal(messages[2].id, "pi_message_0002");
  assert.equal(messages[2].is_error, true);
  assert.equal(messages[2].tool_name, "grep");
});

test("Pi bridge keeps Windows runtime variables without forwarding provider secrets", () => {
  const environment = pythonEnvironment({
    PATH: "C:\\Python;C:\\Windows",
    SystemRoot: "C:\\Windows",
    windir: "C:\\Windows",
    TEMP: "C:\\Temp",
    CONTEXT_GUARDIAN_PYTHONPATH: "C:\\ContextGuardian",
    OPENAI_API_KEY: "must-not-cross-process-boundary",
  }, "win32");

  assert.equal(environment.PATH, "C:\\Python;C:\\Windows");
  assert.equal(environment.SystemRoot, "C:\\Windows");
  assert.equal(environment.windir, "C:\\Windows");
  assert.equal(environment.TEMP, "C:\\Temp");
  assert.equal(environment.PYTHONPATH, "C:\\ContextGuardian");
  assert.equal(environment.OPENAI_API_KEY, undefined);
});

test("Pi bridge uses the platform Python launcher unless configured", () => {
  assert.equal(pythonCommand({}, "win32"), "python");
  assert.equal(pythonCommand({}, "linux"), "python3");
  assert.equal(pythonCommand({ CONTEXT_GUARDIAN_PYTHON: "D:\\Python\\python.exe" }, "win32"), "D:\\Python\\python.exe");
});

test("Pi bridge does not add Windows-only variables on other platforms", () => {
  const environment = pythonEnvironment({ SystemRoot: "C:\\Windows", windir: "C:\\Windows" }, "linux");
  assert.equal(environment.SystemRoot, undefined);
  assert.equal(environment.windir, undefined);
});

test("Pi bridge classifies interpreter startup failures", async () => {
  const previousPython = process.env.CONTEXT_GUARDIAN_PYTHON;
  process.env.CONTEXT_GUARDIAN_PYTHON = "context-guardian-python-does-not-exist";
  try {
    await assert.rejects(
      () => new GuardianBridge().inspect({ cwd: repositoryRoot } as never, [], new AbortController().signal, 500),
      (error: any) => error?.code === "spawn" && /failed to start/.test(error.message),
    );
  } finally {
    if (previousPython === undefined) delete process.env.CONTEXT_GUARDIAN_PYTHON;
    else process.env.CONTEXT_GUARDIAN_PYTHON = previousPython;
  }
});
