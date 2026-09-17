import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { homedir, tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Context } from "@deepseek-ai/cordis";
import {
  createAssistantMessage,
  createMessage,
  createUserMessage,
} from "@deepseek-ai/dsh-llm";
import {
  SESSION_FORMAT_VERSION,
  SessionId,
  SessionSeq,
} from "@deepseek-ai/dsh-session";
import JsonlSessionPersistence from "@deepseek-ai/dsh-session-persistence-jsonl";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(packageRoot, "../..");
const pythonCandidates = [
  process.env.CONTEXT_GUARDIAN_PYTHON,
  resolve(repositoryRoot, ".venv313/bin/python"),
  resolve(repositoryRoot, ".venv/bin/python"),
].filter(Boolean);
const python = pythonCandidates.find((candidate) => existsSync(candidate));
const dsh = process.env.CONTEXT_GUARDIAN_DSH || "dsh";
const liveMode = process.env.CONTEXT_GUARDIAN_DSH_LIVE === "1";
const replayProvider = "context-guardian-replay";
const replayModel = "guardian-fixture";
const hostProvider = process.env.CONTEXT_GUARDIAN_DSH_PROVIDER || "deepseek-official";
const hostModel = process.env.CONTEXT_GUARDIAN_DSH_MODEL || "deepseek-v4-flash";
const fixtureProvider = liveMode ? hostProvider : replayProvider;
const fixtureModel = liveMode ? hostModel : replayModel;

function quoteYaml(value) {
  return `'${String(value).replaceAll("'", "''")}'`;
}

function run(command, args, options = {}) {
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(command, args, {
      ...options,
      stdio: options.stdio || ["ignore", "inherit", "inherit"],
    });
    child.once("error", rejectRun);
    child.once("close", (code, signal) => {
      if (signal) rejectRun(new Error(`${command} terminated by ${signal}`));
      else if (code !== 0) rejectRun(new Error(`${command} exited with code ${String(code)}`));
      else resolveRun();
    });
  });
}

function streamForText(text, time) {
  return [
    { type: "chunk", time, chunk: { type: "block-start", index: 0, blockType: "text" } },
    { type: "chunk", time, chunk: { type: "text-delta", index: 0, text } },
    { type: "chunk", time, chunk: { type: "block-end", index: 0, block: { type: "text", text } } },
    { type: "chunk", time, chunk: { type: "usage", usage: { inputTokens: 700, outputTokens: 60 } } },
    { type: "chunk", time, chunk: { type: "finish", reason: { kind: "stop" } } },
  ];
}

function buildFixtureEvents() {
  let sequence = 0;
  let time = 1_000;
  const events = [];
  const sourceIds = {};
  const push = (type, data, options = {}) => {
    events.push({ type, seq: SessionSeq(sequence++), time: time++, data, ...options });
  };

  push("turn/start", { turn: 1 });
  push("step/start", { turn: 1, step: 1 });
  push("system/message", {
    turn: 1,
    step: 1,
    message: createMessage({
      role: "system",
      content: [{ type: "text", text: "You are a coding agent running a Context Guardian fixture." }],
      source: { kind: "plugin", plugin: "@deepseek-ai/dsh-system-prompt" },
    }),
  }, { surfaceOp: "append" });
  // This mirrors the planning metadata that triggered Issue #9. It is a real
  // session event, but its plugin provenance must keep it out of review.
  push("user/message", createMessage({
    role: "user",
    content: [{ type: "text", text: "Creates task_plan.md, findings.md, and progress.md." }],
    source: { kind: "plugin", plugin: "fixture-planner", form: "notice" },
  }), { surfaceOp: "append" });
  push("request/header", {
    header: {
      config: { provider: fixtureProvider, model: fixtureModel },
    },
    reason: "initial",
  });

  const durableTurns = [
    "目标：实现 OAuth，但不能修改 public API。",
    "约束：必须保持现有 API 兼容。",
    "决定：PostgreSQL 是最终数据库方案。",
    "SQLite 曾被考虑，但因为并发写入导致锁问题而放弃。",
    "TODO：auth.py 仍未完成，需要实现 OAuth 回调。",
    "未决方向：未来是否引入 Redis 作为 session cache 尚未决定；这不是当前数据库方案，是否在压缩后保留由用户判断。",
    "当前状态：provider abstraction 已接入，但 callback 路径还未完成。",
    "当前验证状态：原生 0.3.3 测试没有出现 Review 弹窗，因此验证尚未完成。",
    "用户偏好：保持补丁小巧，不要新增服务。",
    "迁移测试覆盖现有 public API，必须继续通过。",
    "需要记录 OAuth redirect URI 和生产环境 callback 变量。",
    "除非并发设计发生变化，否则不要再次尝试被放弃的 SQLite 方案。",
    "下一步：完成 auth.py，然后运行兼容性测试。",
    "当前状态：主要设计已经确定，只剩 callback 和最终验证。",
    "旁支讨论：npm 的基本用途与当前数据库设计无关。",
  ];
  const noisyTurns = [
    "grep -R OAuth src/",
    "npm install completed successfully.",
    "Temporary syntax error fixed during local debugging.",
    "npm warn deprecated package output from the install command.",
    "rg --files | head -50",
    "REASONING_EFFORTS = [off, low, high, max]；chooseReasoningEffort 解释了弹窗为什么出现。这个诊断还列出了 _source_status_findings、_finding、_local_audit、_make_topics 的调用链。",
    "D:\\anaconda3\\Lib\\site-packages\\context_guardian\\audit.py /Users/link/Documents/ChatGPT/ContextGuardian/context_guardian/audit.py function inventory and call sites。",
    "<path>/Users/link/Documents/ChatGPT/ContextGuardian/context_guardian/audit.py</path><type>file</type><content>{\"path\":\"/tmp/audit.py\",\"type\":\"file\",\"content\":\"source inventory\"}</content>",
  ];
  const allTurns = [...durableTurns, ...noisyTurns, ...durableTurns, ...noisyTurns];
  for (let index = 0; index < allTurns.length; index += 1) {
    const step = index + 1;
    if (index > 0) push("step/start", { turn: 1, step });
    const userText = allTurns[index];
    const userMessage = createUserMessage({
      content: [{ type: "text", text: userText }],
      source: { kind: "user" },
    });
    if (userText.startsWith("目标：")) sourceIds.goal = userMessage.id;
    if (userText.startsWith("约束：")) sourceIds.constraint = userMessage.id;
    if (userText.startsWith("决定：")) sourceIds.postgres = userMessage.id;
    if (userText.startsWith("SQLite 曾")) sourceIds.sqlite = userMessage.id;
    if (userText.startsWith("TODO：")) sourceIds.auth = userMessage.id;
    if (userText.startsWith("当前验证状态：")) sourceIds.status = userMessage.id;
    if (userText.startsWith("旁支讨论：")) sourceIds.side = userMessage.id;
    if (userText.startsWith("REASONING_EFFORTS")) sourceIds.diagnostic = userMessage.id;
    push("user/message", userMessage, { surfaceOp: "append" });

    const assistantText = userText.startsWith("grep") || userText.startsWith("npm") || userText.startsWith("rg")
      ? `观察到临时命令输出：${userText}`
      : `已记录项目状态：${userText}`;
    const assistant = createAssistantMessage({
      content: [{ type: "text", text: assistantText }],
      source: { provider: fixtureProvider, model: fixtureModel },
    });
    push("assistant/message", {
      turn: 1,
      step,
      message: assistant,
      usage: { inputTokens: 700, outputTokens: 60 },
      stream: streamForText(assistantText, time),
    }, { surfaceOp: "append" });

    push("step/end", { turn: 1, step });
  }

  // Live mode adds one deliberately unresolved, future-relevant preference
  // only once and at the end of the history. Native compaction should be free
  // to omit it; the host audit must then either ground it as a Review topic or
  // explain why it is a safe omission. Replay remains deterministic and does
  // not depend on this model-sensitive prompt.
  if (liveMode) {
    const step = allTurns.length + 1;
    push("step/start", { turn: 1, step });
    const unresolvedText = "未决安全方向：OAuth callback 的 replay protection 是否需要单独引入 nonce ledger 尚未决定；这不是当前实现的一部分，但可能影响后续安全设计，压缩后是否保留由用户判断。";
    const unresolved = createUserMessage({
      content: [{ type: "text", text: unresolvedText }],
      source: { kind: "user" },
    });
    push("user/message", unresolved, { surfaceOp: "append" });
    const responseText = `已记录待确认项：${unresolvedText}`;
    const response = createAssistantMessage({
      content: [{ type: "text", text: responseText }],
      source: { provider: fixtureProvider, model: fixtureModel },
    });
    push("assistant/message", {
      turn: 1,
      step,
      message: response,
      usage: { inputTokens: 700, outputTokens: 60 },
      stream: streamForText(responseText, time),
    }, { surfaceOp: "append" });
    push("step/end", { turn: 1, step });
  }

  // Make the seeded session unmistakable in the Web session list. This is a
  // fallback title for the fixture, not a model call, so it cannot consume the
  // replay script before the user starts the compaction test.
  push("session/title", {
    title: "Context Guardian 预置长对话（请先选择）",
    messageSeqs: [SessionSeq(4)],
    source: { kind: "fallback" },
  });
  push("turn/end", { turn: 1, reason: { kind: "completed" } });
  return { events, sourceIds };
}

async function seedSession(root, cwd, id) {
  const ctx = new Context();
  await ctx.plugin(JsonlSessionPersistence, { root, compression: "none" });
  const header = {
    version: SESSION_FORMAT_VERSION,
    id,
    createdAt: Date.now() - 60_000,
    isSeeded: false,
    cwd,
    delegationDepth: 0,
  };
  try {
    const handle = await ctx.sessionPersistence.create(header);
    const fixture = buildFixtureEvents();
    await handle.append(fixture.events);
    await handle.close();
    return fixture.sourceIds;
  } finally {
    await ctx.fiber.dispose();
  }
}

async function main() {
  if (process.versions.node.split(".").map(Number)[0] < 22) {
    throw new Error("DeepSeek Harness smoke requires Node.js 22.19.0+");
  }
  if (!python) {
    throw new Error("Python core not found; set CONTEXT_GUARDIAN_PYTHON to a Python 3.11+ interpreter");
  }

  const tempDir = await mkdtemp(resolve(tmpdir(), "context-guardian-dsh-fixture-") + "-");
  // Replay uses an isolated DSH home. Live mode uses the existing DSH home so
  // the active Harness credential reference remains available.
  const dshHome = liveMode
    ? (process.env.DSH_HOME || resolve(homedir(), ".dsh"))
    : resolve(tempDir, ".dsh");
  // Use a distinctive directory name because DSH falls back to the working
  // directory basename in some Web session-list views, even when the seeded
  // session/title event is available.
  const cwd = resolve(tempDir, "context-guardian-fixture-long");
  const sessionsRoot = resolve(tempDir, "sessions");
  const profile = liveMode
    ? `context-guardian-live-${randomUUID().slice(0, 8)}`
    : "context-guardian-fixture";
  const fixturePath = resolve(tempDir, "replay-session.jsonl");
  const overridePath = resolve(tempDir, "replay.override.json");
  const patchPath = resolve(tempDir, "smoke.patch.yml");
  const agentPresetDir = resolve(dshHome, ".agent-presets", liveMode ? profile : "context-guardian-fixture");
  await mkdir(cwd, { recursive: true });
  await mkdir(agentPresetDir, { recursive: true });
  await writeFile(resolve(agentPresetDir, "preset.yml"), [
    "name: Context Guardian fixture",
    "description: Minimal fixture preset with Context Guardian compaction review.",
    "order: 0",
  ].join("\n") + "\n", "utf8");
  await writeFile(resolve(agentPresetDir, "agent.cordis.yml"), [
    "# Fixture-only agent composition: native compaction is replaced in this realm.",
    "- id: compaction",
    "  name: cordis:group",
    "  group: true",
    "  isolate:",
    "    compaction: true",
    "    toolResultPruner: true",
    "  config:",
    "    - id: context-guardian-compaction",
    "      name: context-guardian-deepseek-harness",
    "    - id: command-compact",
    "      name: '@deepseek-ai/dsh-command-compact'",
    "    - id: tool-result-pruner",
    "      name: '@deepseek-ai/dsh-compaction-tool-result-pruner'",
    "      config:",
    "        thresholdChars: 8192",
    "        headChars: 4096",
    "        tailChars: 1024",
  ].join("\n") + "\n", "utf8");
  const seededSessionId = SessionId(`context-guardian-fixture-${randomUUID()}`);
  const sourceIds = await seedSession(sessionsRoot, cwd, seededSessionId);

  const inspectionResult = {
    candidates: [
      {
        id: "fixture-goal",
        content: "The project goal is to implement OAuth without changing the public API.",
        category: "goal",
        importance: 0.95,
        confidence: 0.98,
        suggested_action: "keep",
        reason: "Explicit project goal.",
        source_message_ids: ["fixture-goal"],
      },
      {
        id: "fixture-constraint",
        content: "Existing API compatibility must be preserved.",
        category: "constraint",
        importance: 0.98,
        confidence: 0.98,
        suggested_action: "keep",
        reason: "Explicit user constraint.",
        source_message_ids: ["fixture-constraint"],
      },
      {
        id: "fixture-postgres",
        content: "PostgreSQL is the final database choice.",
        category: "decision",
        importance: 0.92,
        confidence: 0.97,
        suggested_action: "keep",
        reason: "Explicit final decision.",
        source_message_ids: ["fixture-postgres"],
      },
      {
        id: "fixture-sqlite",
        content: "SQLite was abandoned because concurrent writes caused locking problems.",
        category: "failed_attempt",
        importance: 0.79,
        confidence: 0.79,
        suggested_action: "review",
        reason: "Rejected approach and rationale.",
        source_message_ids: ["fixture-sqlite"],
      },
      {
        id: "fixture-auth",
        content: "auth.py is still incomplete and needs the OAuth callback implementation.",
        category: "todo",
        importance: 0.88,
        confidence: 0.95,
        suggested_action: "review",
        reason: "Explicit unfinished work.",
        source_message_ids: ["fixture-auth"],
      },
      {
        id: "fixture-grep",
        content: "grep output from a transient diagnostic command.",
        category: "tool_output",
        importance: 0.08,
        confidence: 0.98,
        suggested_action: "drop",
        reason: "Transient command output.",
        source_message_ids: ["fixture-grep"],
      },
      {
        id: "fixture-install",
        content: "npm install completed successfully.",
        category: "temporary",
        importance: 0.08,
        confidence: 0.95,
        suggested_action: "drop",
        reason: "Resolved setup noise.",
        source_message_ids: ["fixture-install"],
      },
    ],
  };
  const nativePreview = "目标：实现 OAuth，但不能修改 public API。\n决定：PostgreSQL 是最终数据库方案。\n当前 API 兼容约束仍然有效。\n当前验证与最终校验已完成。";
  const auditPlan = {
    language: "zh-CN",
    overview: "原生预览已经生成。发现 2 项明确修正，还有 1 个旁支主题需要你判断。",
    auto_preserve_summary: "当前目标、API 兼容约束和 PostgreSQL 决定已经被原生预览保留。",
    findings: [
      {
        id: "finding-status",
        issue_type: "incorrect",
        category: "working_state",
        summary: "当前验证状态：原生 0.3.3 测试没有出现 Review 弹窗，因此验证尚未完成。",
        why_it_matters: "当前摘要的完成状态可能误导后续验证与发布判断。",
        suggested_correction: "当前验证状态：原生 0.3.3 测试没有出现 Review 弹窗，因此验证尚未完成。",
        importance: 0.95,
        confidence: 0.98,
        source_message_ids: [sourceIds.status],
        evidence_snippets: ["当前验证状态：原生 0.3.3 测试没有出现 Review 弹窗，因此验证尚未完成。"],
        task_relation: "primary",
        operation: "replace",
        requires_user_confirmation: true,
        current_summary_text: "当前验证与最终校验已完成。",
        proposed_text: "当前验证状态：原生 0.3.3 测试没有出现 Review 弹窗，因此验证尚未完成。",
        effect_if_rejected: "当前摘要中的状态可能继续误导后续验证与发布判断。",
      },
      {
        id: "finding-sqlite",
        issue_type: "missing",
        category: "failed_attempt",
        summary: "SQLite 因并发写入导致锁问题而被放弃。",
        why_it_matters: "这可以避免再次走一条已经被否决的数据库路径。",
        suggested_correction: "SQLite 因并发写入导致锁问题而被放弃。",
        importance: 0.9,
        confidence: 0.95,
        source_message_ids: [sourceIds.sqlite],
        evidence_snippets: ["SQLite 曾被考虑，但因为并发写入导致锁问题而放弃。"],
      },
      {
        id: "finding-auth",
        issue_type: "missing",
        category: "todo",
        summary: "auth.py 仍未完成，需要实现 OAuth 回调。",
        why_it_matters: "这是当前下一个尚未完成的实现步骤。",
        suggested_correction: "auth.py 仍未完成，需要实现 OAuth 回调。",
        importance: 0.9,
        confidence: 0.95,
        source_message_ids: [sourceIds.auth],
        evidence_snippets: ["TODO：auth.py 仍未完成，需要实现 OAuth 回调。"],
      },
      {
        id: "finding-side",
        issue_type: "ambiguous",
        category: "important_fact",
        summary: "旁支讨论：npm 的基本用途与当前数据库设计无关。",
        why_it_matters: "这部分可能与当前主任务无关，但是否保留由用户决定。",
        suggested_correction: "旁支讨论：npm 的基本用途与当前数据库设计无关。",
        importance: 0.35,
        confidence: 0.45,
        source_message_ids: [sourceIds.side],
        evidence_snippets: ["旁支讨论：npm 的基本用途与当前数据库设计无关。"],
      },
      {
        id: "finding-diagnostic",
        issue_type: "ambiguous",
        category: "important_fact",
        summary: "REASONING_EFFORTS = [off, low, high, max]；chooseReasoningEffort 解释了弹窗为什么出现。",
        display_summary: "D:\\anaconda3\\Lib\\site-packages\\context_guardian\\audit.py _make_topics call site",
        why_it_matters: "raw diagnostic material",
        suggested_correction: "REASONING_EFFORTS = [off, low, high, max]；chooseReasoningEffort 解释了弹窗为什么出现。",
        importance: 0.3,
        confidence: 0.4,
        source_message_ids: [sourceIds.diagnostic],
        evidence_snippets: ["REASONING_EFFORTS = [off, low, high, max]；chooseReasoningEffort 解释了弹窗为什么出现。"],
      },
    ],
    audit_topics: [
      {
        id: "topic-corrections",
        title: "预览中缺失的项目状态",
        summary: "预览遗漏了被放弃的 SQLite 路径和未完成的 auth.py 工作。",
        finding_ids: ["finding-sqlite", "finding-auth"],
        impact: 0.95,
        confidence: 0.95,
        relevance_to_main_goal: 0.95,
        requires_user_preference: false,
        disposition: "auto_correct",
        recommended_action: "correct",
        suggested_correction: "SQLite 因并发写入导致锁问题而被放弃。auth.py 仍未完成，需要实现 OAuth 回调。",
      },
      {
        id: "topic-status",
        title: "测试验证状态可能不正确",
        summary: "原生预览将测试写成已完成，但来源显示 Review 弹窗没有出现。",
        finding_ids: ["finding-status"],
        impact: 0.95,
        confidence: 0.98,
        relevance_to_main_goal: 1,
        requires_user_preference: true,
        disposition: "ask_user",
        recommended_action: "correct",
        suggested_correction: "当前验证状态：原生 0.3.3 测试没有出现 Review 弹窗，因此验证尚未完成。",
        evidence_snippets: ["当前验证状态：原生 0.3.3 测试没有出现 Review 弹窗，因此验证尚未完成。"],
        task_relation: "primary",
        operation: "replace",
        current_summary_text: "当前验证与最终校验已完成。",
        proposed_text: "当前验证状态：原生 0.3.3 测试没有出现 Review 弹窗，因此验证尚未完成。",
        effect_if_rejected: "当前摘要中的状态可能继续误导后续验证与发布判断。",
      },
      {
        id: "topic-npm",
        title: "npm 基础概念旁支讨论",
        summary: "你在项目开发过程中讨论过 npm 的基本用途。",
        finding_ids: ["finding-side"],
        impact: 0.35,
        confidence: 0.72,
        relevance_to_main_goal: 0.2,
        requires_user_preference: true,
        disposition: "ask_user",
        recommended_action: "drop",
        suggested_correction: "npm 讨论属于旁支内容；只有在你明确需要时才保留其关键结论。",
      },
    ],
    auto_corrections: [
      "SQLite 因并发写入导致锁问题而被放弃。",
      "auth.py 仍未完成，需要实现 OAuth 回调。",
    ],
    accepted_omissions: ["临时工具输出、日志、路径、哈希和已解决的错误。"],
    review_questions: [
      {
        id: "question-status",
        topic_id: "topic-status",
        title: "测试验证状态可能不正确",
        question: "是否采用对「测试验证状态可能不正确」的摘要修正？",
        context: "主题说明：原生预览写成测试与最终校验已完成。\n\n当前摘要：当前验证与最终校验已完成。\n\n建议写入：当前验证状态：原生 0.3.3 测试没有出现 Review 弹窗，因此验证尚未完成。",
        why_it_matters: "当前摘要中的状态可能继续误导后续验证与发布判断。",
        recommendation: "correct",
        options: [
          { id: "correct", label: "采用修正", description: "替换当前摘要中的完成状态；不会保留完整原始对话。" },
          { id: "keep_preview", label: "保持当前摘要", description: "不修改当前摘要，也不追加这项修正。" },
        ],
        evidence_snippets: ["当前验证状态：原生 0.3.3 测试没有出现 Review 弹窗，因此验证尚未完成。"],
        task_relation: "primary",
        operation: "replace",
        current_summary_text: "当前验证与最终校验已完成。",
        proposed_text: "当前验证状态：原生 0.3.3 测试没有出现 Review 弹窗，因此验证尚未完成。",
        effect_if_rejected: "当前摘要中的状态可能继续误导后续验证与发布判断。",
      },
      {
        id: "question-npm",
        topic_id: "topic-npm",
        title: "npm 基础概念旁支讨论",
        question: "压缩后是否需要特别保留“npm 基础概念”这个旁支主题？",
        context: "你曾在项目开发过程中询问 npm 的基本用途。",
        why_it_matters: "这部分与当前实现任务的关系较弱。",
        recommendation: "drop",
        options: [
          { id: "keep", label: "保留关键结论", description: "要求最终摘要保留该主题的关键结论。" },
          { id: "drop", label: "无需特别保留", description: "接受原生预览对该主题的处理。" },
        ],
      },
    ],
  };
  await writeFile(fixturePath, JSON.stringify({
    version: 3,
    isSeeded: false,
    createdAt: 0,
    cwd,
    delegationDepth: 0,
    type: "session",
    id: seededSessionId,
  }) + "\n", "utf8");
  await writeFile(overridePath, JSON.stringify([
    {
      kind: "chunks",
      chunks: [
        { type: "block-start", index: 0, blockType: "text" },
        { type: "text-delta", index: 0, text: nativePreview },
        { type: "block-end", index: 0, block: { type: "text", text: nativePreview } },
        { type: "finish", reason: { kind: "stop" } },
      ],
    },
    {
      kind: "chunks",
      chunks: [
        { type: "block-start", index: 0, blockType: "text" },
        { type: "text-delta", index: 0, text: JSON.stringify(auditPlan) },
        { type: "block-end", index: 0, block: { type: "text", text: JSON.stringify(auditPlan) } },
        { type: "finish", reason: { kind: "stop" } },
      ],
    },
  ], null, 2) + "\n", "utf8");
  const patchLines = [
    "- id: session-persistence-jsonl",
    "  config:",
    `    root: ${quoteYaml(sessionsRoot)}`,
    "    compression: none",
    "- id: agent-default-model",
    "  config:",
    `    provider: ${quoteYaml(fixtureProvider)}`,
    `    model: ${quoteYaml(fixtureModel)}`,
    "- id: agent-presets",
    "  config:",
    `    default: ${profile}`,
  ];
  if (!liveMode) {
    patchLines.push(
      "- id: llm-deepseek",
      "  disabled: true",
      "- insert:",
      "    - id: llm-replay",
      "      name: '@deepseek-ai/dsh-llm-replay'",
      "      config:",
      `        file: ${quoteYaml(fixturePath)}`,
      `        overrideFile: ${quoteYaml(overridePath)}`,
      "        providers:",
      `          - id: ${replayProvider}`,
      "            models:",
      `              - id: ${replayModel}`,
      "                contextWindow: 8192",
    );
  }
  await writeFile(patchPath, patchLines.join("\n") + "\n", "utf8");

  const environment = {
    ...process.env,
    DSH_HOME: dshHome,
    CONTEXT_GUARDIAN_PYTHON: python,
    CONTEXT_GUARDIAN_TIMEOUT_MS: "60000",
    npm_config_cache: resolve(tempDir, "npm-cache"),
  };
  try {
    await run(dsh, ["--profile", profile, "--from-default-profile", "web", "--dump-config"], {
      env: environment,
      stdio: ["ignore", "ignore", "inherit"],
    });
    const packOutput = await new Promise((resolvePack, rejectPack) => {
      const child = spawn("npm", ["pack", "--pack-destination", tempDir], {
        cwd: packageRoot,
        env: environment,
        stdio: ["ignore", "pipe", "inherit"],
      });
      let output = "";
      child.stdout.on("data", (chunk) => { output += String(chunk); });
      child.once("error", rejectPack);
      child.once("close", (code) => {
        if (code !== 0) rejectPack(new Error(`npm pack exited with code ${String(code)}`));
        else resolvePack(output.trim().split("\n").at(-1));
      });
    });
    const packageTarball = resolve(tempDir, packOutput);
    const packageSpec = process.env.CONTEXT_GUARDIAN_FIXTURE_PACKAGE || packageTarball;
    await run(dsh, ["plugin", "--profile", profile, "add", packageSpec], { env: environment });
    if (!liveMode) {
      await run(dsh, ["plugin", "--profile", profile, "add", "@deepseek-ai/dsh-llm-replay@0.1.5-rc.2"], { env: environment });
    }

    console.log("");
    console.log(`DeepSeek Harness Context Guardian ${liveMode ? "live" : "replay"} fixture is ready.`);
    console.log("Open the printed Web URL, select 'Context Guardian 预置长对话（请先选择）' (or the context-guardian-fixture-long session), enter /compact, and answer at most three topic questions.");
    console.log("Expected automatic corrections: SQLite failure reason and the incomplete auth.py TODO.");
    console.log("Expected correction question: unresolved native-popup verification status; the npm fundamentals side discussion may appear as one bounded question; raw reasoning, paths, wrappers, and execution noise stay out of the UI.");
    console.log("Expected final result: one native Preview plus a Reviewed Facts block containing the selected corrections and no raw logs.");
    if (liveMode) console.log(`Live route: ${hostProvider}/${hostModel}; credentials stay inside DeepSeek Harness.`);
    console.log("Exit the Web process with Ctrl-C when finished.");
    console.log("");

    await new Promise((resolveProcess, rejectProcess) => {
      const child = spawn(dsh, ["--profile", profile, "--patch", patchPath, "--no-open", "--port", "0"], {
        cwd,
        env: environment,
        stdio: ["inherit", "pipe", "inherit"],
      });
      child.stdout.on("data", (chunk) => process.stdout.write(chunk));
      child.once("error", rejectProcess);
      child.once("close", (code, signal) => {
        if (signal === "SIGINT" || code === 0 || code === 130 || code === 143) resolveProcess();
        else rejectProcess(new Error(`dsh web exited with code ${String(code)}`));
      });
      const stop = () => child.kill("SIGINT");
      process.once("SIGINT", stop);
      process.once("SIGTERM", stop);
    });
  } finally {
    if (process.env.CONTEXT_GUARDIAN_KEEP_FIXTURE !== "1") {
      await rm(tempDir, { recursive: true, force: true });
    } else {
      console.log(`Fixture kept at ${tempDir}`);
    }
    if (liveMode) {
      await rm(resolve(dshHome, "profiles", profile), { recursive: true, force: true });
      await rm(agentPresetDir, { recursive: true, force: true });
    }
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
