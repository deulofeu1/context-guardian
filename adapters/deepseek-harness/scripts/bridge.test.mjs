import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";
import { GuardianBridge, normalizeDeepSeekMessages, preferredLanguage, pythonCommand, pythonEnvironment } from "../lib/bridge.js";
import { ContextGuardianCompactionEngine, answersForNoUi, needsRevision } from "../lib/index.js";

const repositoryRoot = resolve(new URL("../../../", import.meta.url).pathname);
const pythonCandidates = [
  process.env.CONTEXT_GUARDIAN_PYTHON,
  resolve(repositoryRoot, ".venv313/bin/python"),
  resolve(repositoryRoot, ".venv/bin/python"),
  process.platform === "win32" ? "python" : "python3",
].filter((value, index, all) => value !== undefined && all.indexOf(value) === index);
const python = pythonCandidates.find((value) => {
  if (value !== "python" && value !== "python3" && !existsSync(value)) return false;
  const probe = spawnSync(value, ["-c", "import context_guardian"], {
    cwd: repositoryRoot,
    env: { ...process.env, PYTHONPATH: repositoryRoot },
    stdio: "ignore",
  });
  return probe.status === 0;
});

function fakeContext() {
  const calls = [];
  return {
    calls,
    llm: {
      stream(options) {
        calls.push(options);
        return (async function* () {
          yield {
            type: "block-end",
            index: 0,
            block: {
              type: "text",
              text: JSON.stringify({
                candidates: [{
                  id: "model_goal",
                  content: "The project goal is to preserve OAuth compatibility.",
                  category: "goal",
                  importance: 0.9,
                  confidence: 0.9,
                  suggested_action: "review",
                  reason: "User-authored goal.",
                  source_message_ids: ["m1"],
                }],
              }),
            },
          };
          yield { type: "finish", reason: { kind: "stop" } };
        })();
      },
    },
  };
}

function fakeAgent() {
  return {
    session: {
      id: "session-context-guardian-test",
      header: { cwd: repositoryRoot },
      requestHeader: () => ({ config: { provider: "deepseek-official", model: "deepseek-v4-flash" } }),
    },
  };
}

test("DeepSeek message normalization keeps stable ids and tool errors", () => {
  const messages = normalizeDeepSeekMessages("System policy", [
    { id: "m1", role: "user", content: [{ type: "text", text: "Implement OAuth." }] },
    {
      id: "m2",
      role: "user",
      source: { kind: "tool", callId: "call-1" },
      content: [{ type: "tool-result", isError: true, content: [{ type: "text", text: "temporary failure" }] }],
    },
  ]);

  assert.equal(messages[0].id, "m1");
  assert.equal(messages[1].role, "tool");
  assert.equal(messages[1].is_error, true);
});

test("DeepSeek bridge detects language from user messages only", () => {
  assert.equal(preferredLanguage([
    { role: "assistant", content: "中文 assistant text", id: "a1" },
    { role: "user", content: "请保留当前目标和约束", id: "u1" },
  ]), "zh-CN");
  assert.equal(preferredLanguage([
    { role: "assistant", content: "中文输出", id: "a2" },
    { role: "user", content: "Keep the API compatible", id: "u2" },
  ]), "en");
});

test("DeepSeek no-UI resolution follows recommendations and preserves corrections", () => {
  const plan = {
    auto_corrections: ["auth.py is incomplete."],
    review_questions: [{ id: "q1", topic_id: "t1", recommendation: "keep" }],
  };
  assert.deepEqual(answersForNoUi(plan), [{ question_id: "q1", topic_id: "t1", action: "keep" }]);
  assert.equal(needsRevision(plan, [{ action: "drop" }]), true);
});

test("Python bridge keeps the minimal environment and Windows runtime variables", () => {
  const environment = pythonEnvironment({
    PATH: "C:\\Python;C:\\Windows",
    SystemRoot: "C:\\Windows",
    windir: "C:\\Windows",
    TEMP: "C:\\Temp",
    CONTEXT_GUARDIAN_PYTHONPATH: "C:\\ContextGuardian",
    DEEPSEEK_API_KEY: "must-not-cross-process-boundary",
  }, "win32");

  assert.equal(environment.PATH, "C:\\Python;C:\\Windows");
  assert.equal(environment.SystemRoot, "C:\\Windows");
  assert.equal(environment.windir, "C:\\Windows");
  assert.equal(environment.TEMP, "C:\\Temp");
  assert.equal(environment.PYTHONPATH, "C:\\ContextGuardian");
  assert.equal(environment.DEEPSEEK_API_KEY, undefined);
});

test("Python bridge uses the Windows launcher unless an interpreter is configured", () => {
  assert.equal(pythonCommand({}, "win32"), "python");
  assert.equal(pythonCommand({}, "linux"), "python3");
  assert.equal(pythonCommand({ CONTEXT_GUARDIAN_PYTHON: "D:\\Python\\python.exe" }, "win32"), "D:\\Python\\python.exe");
});

test("Python bridge does not add Windows-only variables on other platforms", () => {
  const environment = pythonEnvironment({ SystemRoot: "C:\\Windows", windir: "C:\\Windows" }, "linux");
  assert.equal(environment.SystemRoot, undefined);
  assert.equal(environment.windir, undefined);
});

test("DeepSeek bridge classifies interpreter startup failures", async () => {
  const previousPython = process.env.CONTEXT_GUARDIAN_PYTHON;
  process.env.CONTEXT_GUARDIAN_PYTHON = "context-guardian-python-does-not-exist";
  try {
    await assert.rejects(
      () => new GuardianBridge().inspect(fakeContext(), fakeAgent(), [], new AbortController().signal),
      (error) => error?.code === "spawn" && /failed to start/.test(error.message),
    );
  } finally {
    if (previousPython === undefined) delete process.env.CONTEXT_GUARDIAN_PYTHON;
    else process.env.CONTEXT_GUARDIAN_PYTHON = previousPython;
  }
});

test("DeepSeek bridge performs host-provider inspection and local guidance", { skip: !python }, async () => {
  const previousPython = process.env.CONTEXT_GUARDIAN_PYTHON;
  const previousPath = process.env.CONTEXT_GUARDIAN_PYTHONPATH;
  process.env.CONTEXT_GUARDIAN_PYTHON = python;
  process.env.CONTEXT_GUARDIAN_PYTHONPATH = repositoryRoot;
  try {
    const ctx = fakeContext();
    const agent = fakeAgent();
    const bridge = new GuardianBridge();
    const signal = new AbortController().signal;
    const inspection = await bridge.inspect(ctx, agent, [
      { role: "user", content: "Implement OAuth.", id: "m1" },
    ], signal);
    assert.equal(inspection.mode, "provider");
    assert.equal(inspection.candidates[0].id, "model_goal");
    assert.equal(ctx.calls[0].provider, "deepseek-official");
    assert.equal(ctx.calls[0].model, "deepseek-v4-flash");

    const guidance = await bridge.guidance(ctx, agent, inspection.candidates, [
      { candidate_id: "model_goal", action: "keep" },
    ], signal);
    assert.match(guidance.text, /Must preserve:/);
    assert.match(guidance.text, /OAuth compatibility/);
    assert.equal(ContextGuardianCompactionEngine.name, "ContextGuardianCompactionEngine");
  } finally {
    if (previousPython === undefined) delete process.env.CONTEXT_GUARDIAN_PYTHON;
    else process.env.CONTEXT_GUARDIAN_PYTHON = previousPython;
    if (previousPath === undefined) delete process.env.CONTEXT_GUARDIAN_PYTHONPATH;
    else process.env.CONTEXT_GUARDIAN_PYTHONPATH = previousPath;
  }
});
