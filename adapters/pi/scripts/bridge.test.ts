import assert from "node:assert/strict";
import { resolve } from "node:path";
import test from "node:test";
import {
  GuardianBridge,
  normalizePiMessages,
  preferredLanguage,
  pythonCommand,
  pythonEnvironment,
} from "../src/bridge.ts";
import { answersForNoUi } from "../extensions/context-guardian.ts";
import { appendReviewedFacts } from "../src/reviewed-facts.ts";

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

test("Pi bridge detects language from user messages only", () => {
  assert.equal(preferredLanguage([
    { role: "assistant", content: "中文 assistant text", id: "a1" },
    { role: "user", content: "请保留当前目标和约束", id: "u1" },
  ]), "zh-CN");
  assert.equal(preferredLanguage([
    { role: "assistant", content: "中文输出", id: "a2" },
    { role: "user", content: "Keep the API compatible", id: "u2" },
  ]), "en");
  assert.equal(preferredLanguage([
    { role: "assistant", content: "English assistant output", id: "a3" },
    {
      role: "user",
      content: "目标是让 Context Guardian fixture smoke test 支持 public API 兼容。请保留当前约束。",
      id: "u3",
    },
  ]), "zh-CN");
});

test("Pi no-UI resolution follows topic recommendations", () => {
  const plan = {
    auto_corrections: ["auth.py is incomplete."],
    review_questions: [{ id: "q1", topic_id: "t1", recommendation: "keep" }],
  } as any;
  assert.deepEqual(answersForNoUi(plan), [{ question_id: "q1", topic_id: "t1", action: "keep" }]);
});

test("Pi appends reviewed facts without a second native summary", () => {
  const preview = "Native Pi preview";
  const appendix = {
    version: "1" as const,
    language: "en" as const,
    facts: [{ id: "fact-1", text: "SQLite was abandoned due to concurrency.", origin: "auto_correction" as const }],
    text: "<!-- context-guardian:reviewed-facts:v1 -->\n- SQLite was abandoned due to concurrency.\n<!-- /context-guardian:reviewed-facts -->",
  };
  const finalSummary = appendReviewedFacts(preview, appendix);
  assert.equal(finalSummary.startsWith(preview), true);
  assert.equal(finalSummary.includes("SQLite was abandoned"), true);
  assert.equal(appendReviewedFacts(finalSummary, appendix), finalSummary);
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
