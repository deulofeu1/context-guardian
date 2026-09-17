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
import { answerReviewQuestions, answersForNoUi, questionBody } from "../extensions/context-guardian.ts";
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

test("Pi normalization marks host metadata and execution records as non-evidence", () => {
  const messages = normalizePiMessages([
    { role: "custom", customType: "fixture-planning", content: "Creates task_plan.md, findings.md, and progress.md", display: false },
    { role: "bashExecution", command: "rg --files", output: "mechanical output", exitCode: 0 },
    { role: "compactionSummary", summary: "previous native metadata", tokensBefore: 100 },
    { role: "user", content: "The API must remain compatible." },
  ]);
  assert.equal(messages[0].provenance?.plugin_internal, true);
  assert.equal(messages[0].provenance?.planning, true);
  assert.equal(messages[1].provenance?.source_kind, "execution_noise");
  assert.equal(messages[2].provenance?.compaction_metadata, true);
  assert.equal(messages[3].provenance?.user_authored, true);
});

test("Pi normalization keeps text blocks only and never serializes wrapper payloads", () => {
  const messages = normalizePiMessages([{
    role: "assistant",
    content: [
      { type: "text", text: "PostgreSQL is selected." },
      { type: "toolCall", name: "grep", arguments: { pattern: "OAuth" } },
      { type: "json", path: "/tmp/raw.json", payload: { hidden: true } },
    ],
  }]);
  assert.equal(messages.length, 1);
  assert.equal(messages[0].content, "PostgreSQL is selected.");
  assert.equal(messages[0].content.includes("raw.json"), false);
  assert.equal(messages[0].metadata?.pi_unknown_block_count, 1);
  assert.equal(messages[0].provenance?.source_kind, "execution_noise");
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

test("Pi review UI separates localized summary from verbatim source evidence", () => {
  const body = questionBody({
    id: "q1",
    topic_id: "t1",
    title: "Optional adapter",
    question: "Should the compaction preserve this topic?",
    context: "该适配器应保持可选。",
    why_it_matters: "这会影响后续部署。",
    recommendation: "keep",
    options: [
      { id: "keep", label: "保留", description: "保留关键结论。" },
      { id: "drop", label: "丢弃", description: "接受原生预览。" },
    ],
    evidence_snippets: ["The adapter should remain optional for future deployments."],
    source_message_ids: ["source-1"],
  });
  assert.match(body, /该适配器应保持可选/);
  assert.match(body, /来源证据（原文，仅用于核对/);
  assert.match(body, /The adapter should remain optional/);
});

test("Pi review path invokes the UI confirmation when a question exists", async () => {
  const calls: Array<{ title: string; body: string }> = [];
  const plan = {
    review_questions: [{
      id: "q1",
      topic_id: "t1",
      title: "Optional adapter",
      question: "Should this be kept?",
      context: "The adapter is optional.",
      why_it_matters: "It may affect later deployments.",
      recommendation: "drop",
      options: [
        { id: "keep", label: "Keep", description: "Keep the conclusion." },
        { id: "drop", label: "Drop", description: "Accept the preview." },
      ],
    }],
  } as any;
  const answers = await answerReviewQuestions(
    { hasUI: true, ui: { confirm: async (title: string, body: string) => {
      calls.push({ title, body });
      return true;
    } } } as any,
    plan,
    new AbortController().signal,
  );
  assert.equal(calls.length, 1);
  assert.match(calls[0].body, /Should this be kept/);
  assert.deepEqual(answers, [{ question_id: "q1", topic_id: "t1", action: "keep" }]);
});

test("Pi review path uses explicit selector actions when the host exposes select", async () => {
  const plan = {
    review_questions: [{
      id: "q1",
      topic_id: "t1",
      title: "Test status",
      question: "Apply this correction?",
      context: "Current summary: complete.\n\nProposed text: not verified.",
      why_it_matters: "The current status may mislead future work.",
      recommendation: "correct",
      operation: "replace",
      options: [
        { id: "correct", label: "Apply correction", description: "Replace the current status." },
        { id: "keep_preview", label: "Keep current summary", description: "Leave it unchanged." },
      ],
    }],
  } as any;
  let selectedTitle = "";
  const answers = await answerReviewQuestions(
    { hasUI: true, ui: {
      select: async (title: string, options: string[]) => {
        selectedTitle = title;
        assert.equal(options.length, 2);
        return options[0];
      },
      confirm: async () => false,
    } } as any,
    plan,
    new AbortController().signal,
  );
  assert.match(selectedTitle, /Current summary: complete/);
  assert.deepEqual(answers, [{ question_id: "q1", topic_id: "t1", action: "correct" }]);
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
