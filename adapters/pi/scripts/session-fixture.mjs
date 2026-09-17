import { readFileSync } from "node:fs";
import { writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";

function entryId(index) {
  return index.toString(16).padStart(8, "0");
}

function isoTime(index) {
  return new Date(Date.now() + index * 1000).toISOString();
}

function usage() {
  return {
    input: 0,
    output: 0,
    cacheRead: 0,
    cacheWrite: 0,
    totalTokens: 0,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
  };
}

function assistantMessage(text, timestamp, toolCall) {
  const content = toolCall
    ? [{ type: "toolCall", id: toolCall.id, name: toolCall.name, arguments: {} }]
    : [{ type: "text", text }];
  return {
    role: "assistant",
    content,
    api: "openai-responses",
    provider: "fixture",
    model: "fixture",
    usage: usage(),
    stopReason: toolCall ? "toolUse" : "stop",
    timestamp,
  };
}

const DEFAULT_FIXTURE_TRANSLATIONS = new Map([
  [
    "The goal is to implement OAuth without modifying the public API.",
    "目标：实现 OAuth，但不能修改 public API。",
  ],
  ["Let's stop using SQLite. Use PostgreSQL instead.", "决定：停止使用 SQLite，改用 PostgreSQL。"],
  ["I first tried SQLite for the auth state.", "我首先尝试使用 SQLite 保存认证状态。"],
  [
    "PostgreSQL is now the selected database. auth.py is still incomplete.",
    "PostgreSQL 已确定为数据库方案，auth.py 仍未完成。",
  ],
  ["A temporary syntax error was fixed.", "临时语法错误已解决。"],
]);

function localizeDefaultFixtureText(text) {
  return DEFAULT_FIXTURE_TRANSLATIONS.get(text) ?? text;
}

export function createSession(sourcePath, tempDir, fillerTurns = 320) {
  const source = JSON.parse(readFileSync(sourcePath, "utf8"));
  const sessionId = randomUUID();
  const entries = [
    {
      type: "session",
      version: 3,
      id: sessionId,
      timestamp: new Date().toISOString(),
      cwd: tempDir,
    },
  ];
  let parentId = null;
  let sequence = 0;

  const append = (message) => {
    const id = entryId(sequence++);
    entries.push({
      type: "message",
      id,
      parentId,
      timestamp: isoTime(sequence),
      message,
    });
    parentId = id;
  };

  for (const message of source.messages) {
    const timestamp = Date.now() + sequence * 1000;
    if (message.role === "user") {
      append({ role: "user", content: localizeDefaultFixtureText(message.content), timestamp });
    } else if (message.role === "tool") {
      const callId = `fixture-call-${sequence}`;
      append(assistantMessage("Running a diagnostic command.", timestamp, {
        id: callId,
        name: message.tool_name || "bash",
      }));
      append({
        role: "toolResult",
        toolCallId: callId,
        toolName: message.tool_name || "bash",
        content: [{ type: "text", text: message.content }],
        isError: Boolean(message.is_error),
        timestamp: timestamp + 1,
      });
    } else {
      append(assistantMessage(localizeDefaultFixtureText(message.content), timestamp));
    }
  }

  // Host-internal records that reproduce the provenance edge case from Issue
  // #9. The Pi adapter must carry them to the Core as metadata, never as user
  // evidence or Review questions.
  append({
    role: "custom",
    customType: "fixture-planning",
    content: "Creates task_plan.md, findings.md, and progress.md.",
    display: false,
    details: { internal: true },
    timestamp: Date.now() + sequence * 1000,
  });
  append({
    role: "bashExecution",
    command: "rg --files | head -50",
    output: "mechanical fixture output",
    exitCode: 0,
    cancelled: false,
    truncated: false,
    timestamp: Date.now() + sequence * 1000,
  });
  append({
    role: "compactionSummary",
    summary: "Internal previous compaction metadata for the fixture.",
    tokensBefore: 100,
    timestamp: Date.now() + sequence * 1000,
  });

  // A deliberately weak, user-authored side topic gives the native Preview
  // something that may reasonably require one bounded human decision. It is
  // never a raw command or tool log and is safe to omit from project memory.
  append({
    role: "user",
    content: "旁支讨论：npm 在 JavaScript 项目中的基本用途是什么？",
    timestamp: Date.now() + sequence * 1000,
  });
  append(assistantMessage(
    "npm 可以安装依赖并运行项目脚本，这与 OAuth 设计无关。",
    Date.now() + sequence * 1000,
  ));

  // A primary status conflict exercises Issue #19. The native model may
  // summarize the completion claim, while the source-backed audit must keep
  // the exact unresolved verification state as a separate correction choice.
  append({
    role: "user",
    content: "当前验证状态：原生 0.3.3 测试没有出现 Review 弹窗，因此验证尚未完成。",
    timestamp: Date.now() + sequence * 1000,
  });
  append(assistantMessage(
    "已记录验证状态：原生 0.3.3 测试没有出现 Review 弹窗，因此验证尚未完成。",
    Date.now() + sequence * 1000,
  ));

  // Issue #23 regression material: these are real user-authored turns, but
  // they are implementation diagnostics rather than durable project facts.
  append({
    role: "user",
    content: "REASONING_EFFORTS = [off, low, high, max]；chooseReasoningEffort 解释了弹窗为什么出现。这个诊断还列出了 _source_status_findings、_finding、_local_audit、_make_topics 的调用链。",
    timestamp: Date.now() + sequence * 1000,
  });
  append({
    role: "user",
    content: "<path>/Users/link/Documents/ChatGPT/ContextGuardian/context_guardian/audit.py</path><type>file</type><content>{\"path\":\"/tmp/audit.py\",\"type\":\"file\",\"content\":\"source inventory\"}</content>",
    timestamp: Date.now() + sequence * 1000,
  });
  append({
    role: "user",
    content: "结构化审计关闭 reasoning，将输出额度用于 JSON 结果。",
    timestamp: Date.now() + sequence * 1000,
  });

  const filler =
    "背景实现记录：这是 Context Guardian fixture smoke test 的重复填充，表示不会改变关键项目决定的常规进度，" +
    "压缩时可以安全概括。";
  for (let index = 0; index < fillerTurns; index += 1) {
    const detail = `${filler}turn=${index}; ${filler}`;
    append({
      role: "user",
      content: `继续记录常规进度。${detail}`,
      timestamp: Date.now() + sequence * 1000,
    });
    append(assistantMessage(`已记录常规进度。${detail}`, Date.now() + sequence * 1000));
  }

  return entries;
}

export async function writeSessionFixture(sourcePath, tempDir, sessionPath, fillerTurns = 320) {
  const entries = createSession(sourcePath, tempDir, fillerTurns);
  await writeFile(sessionPath, entries.map((entry) => JSON.stringify(entry)).join("\n") + "\n", "utf8");
  return entries;
}

export function defaultSourcePath(repositoryRoot) {
  return resolve(repositoryRoot, "examples/conversation.json");
}
