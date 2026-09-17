import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";
import { GuardianBridge, normalizeDeepSeekMessages, preferredLanguage, pythonCommand, pythonEnvironment } from "../lib/bridge.js";
import { answerReviewQuestions, applyFinalizationToSummary, ContextGuardianCompactionEngine, answersForNoUi, reviewQuestionsForUi, uiMessageWithError } from "../lib/index.js";
import { appendReviewedFacts } from "../lib/reviewed-facts.js";

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
      resolveModelInfo() {
        return { reasoning: { efforts: [{ id: "off", name: "Off" }, { id: "high", name: "High" }] } };
      },
      stream(options) {
        calls.push(options);
        return (async function* () {
          yield {
            type: "block-end",
            index: 1,
            block: { type: "reasoning", text: "hidden reasoning that must not be parsed" },
          };
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

test("DeepSeek normalization excludes reasoning, tool calls, and unknown wrappers from evidence", () => {
  const messages = normalizeDeepSeekMessages(undefined, [
    {
      id: "mixed",
      role: "assistant",
      source: { kind: "model" },
      content: [
        { type: "reasoning", text: "hidden chain of thought" },
        { type: "text", text: "The API must remain compatible." },
        { type: "json", path: "/tmp/diagnostic.json", payload: { raw: true } },
      ],
    },
    {
      id: "reasoning-only",
      role: "assistant",
      source: { kind: "model" },
      content: [{ type: "reasoning", text: "hidden only" }],
    },
    {
      id: "tool-call",
      role: "assistant",
      content: [{ type: "tool-call", name: "grep", arguments: { pattern: "OAuth" } }],
    },
  ]);
  assert.equal(messages.length, 1);
  assert.equal(messages[0].content, "The API must remain compatible.");
  assert.equal(messages[0].content.includes("hidden"), false);
  assert.equal(messages[0].content.includes("diagnostic.json"), false);
  assert.equal(messages[0].metadata.reasoning_block_count, 1);
});

test("DeepSeek normalization excludes plugin planning metadata from evidence", () => {
  const messages = normalizeDeepSeekMessages(undefined, [
    {
      id: "plugin-plan",
      role: "assistant",
      source: { kind: "plugin", plugin: "fixture-planner", form: "notice" },
      content: [{ type: "text", text: "Creates task_plan.md, findings.md, and progress.md." }],
    },
    {
      id: "goal",
      role: "user",
      source: { kind: "user" },
      content: [{ type: "text", text: "The API must remain compatible." }],
    },
  ]);
  assert.equal(messages[0].provenance.plugin_internal, true);
  assert.equal(messages[0].provenance.planning, false);
  assert.equal(messages[1].provenance.user_authored, true);
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
  assert.equal(preferredLanguage([
    { role: "assistant", content: "English assistant output", id: "a3" },
    {
      role: "user",
      content: "目标是让 Context Guardian fixture smoke test 支持 public API 兼容。请保留当前约束。",
      id: "u3",
    },
  ]), "zh-CN");
});

test("DeepSeek no-UI resolution follows topic recommendations", () => {
  const plan = {
    auto_corrections: ["auth.py is incomplete."],
    review_questions: [{ id: "q1", topic_id: "t1", recommendation: "keep" }],
  };
  assert.deepEqual(answersForNoUi(plan), [{ question_id: "q1", topic_id: "t1", action: "keep" }]);
});

test("DeepSeek review UI separates localized summary from verbatim source evidence", () => {
  const questions = reviewQuestionsForUi({
    language: "zh-CN",
    overview: "本次压缩需要判断一个主题。",
    auto_preserve_summary: "",
    findings: [],
    audit_topics: [],
    auto_corrections: [],
    accepted_omissions: [],
    diagnostics: [],
    review_questions: [{
      id: "q1",
      topic_id: "t1",
      title: "可选适配器",
      question: "压缩后是否需要特别保留这个主题？",
      context: "该适配器应保持可选。",
      why_it_matters: "这会影响后续部署。",
      recommendation: "keep",
      options: [
        { id: "keep", label: "保留", description: "保留关键结论。" },
        { id: "drop", label: "丢弃", description: "接受原生预览。" },
      ],
      evidence_snippets: ["The adapter should remain optional for future deployments."],
    }],
  });
  assert.equal(questions.length, 1);
  assert.match(questions[0].detail, /该适配器应保持可选/);
  assert.match(questions[0].detail, /来源证据（原文，仅用于核对）/);
  assert.match(questions[0].detail, /The adapter should remain optional/);
  assert.equal(questions[0].detail.includes("压缩后是否需要特别保留这个主题？"), false);
});

test("DeepSeek review path invokes the host question capability when a question exists", async () => {
  let request;
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
  };
  const answers = await answerReviewQuestions(
    { userQuestions: { ask: async (value) => {
      request = value;
      return { answers: [{ id: "q1", selected: ["Keep"] }] };
    } } },
    {},
    plan,
    new AbortController().signal,
  );
  assert.equal(request.questions.length, 1);
  assert.match(request.questions[0].question, /Should this be kept/);
  assert.deepEqual(answers, [{ question_id: "q1", topic_id: "t1", action: "keep" }]);
});

test("DeepSeek appends reviewed facts to summary without a second native call", () => {
  const preview = "Native Harness preview";
  const appendix = {
    version: "1",
    language: "en",
    facts: [{ id: "fact-1", text: "SQLite was abandoned due to concurrency.", origin: "auto_correction" }],
    text: "<!-- context-guardian:reviewed-facts:v1 -->\n- SQLite was abandoned due to concurrency.\n<!-- /context-guardian:reviewed-facts -->",
  };
  const finalSummary = appendReviewedFacts(preview, appendix);
  assert.equal(finalSummary.startsWith(preview), true);
  assert.equal(finalSummary.includes("SQLite was abandoned"), true);
  assert.equal(appendReviewedFacts(finalSummary, appendix), finalSummary);
});

test("DeepSeek finalization preserves non-text summary blocks and metadata", () => {
  const summary = [
    { type: "text", text: "The delivery status is complete." },
    { type: "reasoning", text: "hidden reasoning", providerMetadata: { trace: "keep" } },
    { type: "tool-result", tool: "native", payload: { keep: true } },
  ];
  const result = applyFinalizationToSummary(summary, {
    original_preview: "The delivery status is complete.",
    final_summary: "The delivery status is not verified.",
    changed: true,
    edits: [{
      id: "edit-1",
      operation: "replace",
      target: "The delivery status is complete.",
      replacement: "The delivery status is not verified.",
      status: "applied",
      reason: "exact unique source-backed target",
    }],
    appendix: { version: "1", language: "en", facts: [], text: "" },
    diagnostics: [],
  });
  assert.equal(result[0].text, "The delivery status is not verified.");
  assert.deepEqual(result[1], summary[1]);
  assert.deepEqual(result[2], summary[2]);
});

test("DeepSeek fallback warnings preserve bridge error details", () => {
  assert.match(
    uiMessageWithError("en", "auditUnavailable", new Error("unsupported operation")),
    /unsupported operation/,
  );
  assert.match(
    uiMessageWithError("zh-CN", "auditUnavailable", "core is unavailable"),
    /core is unavailable/,
  );
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
    assert.equal(ctx.calls[0].reasoningEffort, "off");
    assert.equal(ctx.calls[0].maxTokens, 8192);

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
