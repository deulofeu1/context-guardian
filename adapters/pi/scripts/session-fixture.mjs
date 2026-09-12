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

export function createSession(sourcePath, tempDir, fillerTurns = 96) {
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
      append({ role: "user", content: message.content, timestamp });
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
      append(assistantMessage(message.content, timestamp));
    }
  }

  // A deliberately weak, user-authored side topic gives the native Preview
  // something that may reasonably require one bounded human decision. It is
  // never a raw command or tool log and is safe to omit from project memory.
  append({
    role: "user",
    content: "Side discussion: what is the basic purpose of npm in a JavaScript project?",
    timestamp: Date.now() + sequence * 1000,
  });
  append(assistantMessage(
    "npm installs packages and runs project scripts; this is unrelated to the OAuth design.",
    Date.now() + sequence * 1000,
  ));

  const filler =
    "Background implementation note: this is deliberately repetitive padding for the " +
    "Context Guardian fixture smoke test. It represents ordinary progress that can be " +
    "summarized without changing the important project decision. ";
  for (let index = 0; index < fillerTurns; index += 1) {
    const detail = `${filler}turn=${index}; ${filler}`;
    append({
      role: "user",
      content: `Continue tracking routine progress. ${detail}`,
      timestamp: Date.now() + sequence * 1000,
    });
    append(assistantMessage(`Routine progress recorded. ${detail}`, Date.now() + sequence * 1000));
  }

  return entries;
}

export async function writeSessionFixture(sourcePath, tempDir, sessionPath, fillerTurns = 96) {
  const entries = createSession(sourcePath, tempDir, fillerTurns);
  await writeFile(sessionPath, entries.map((entry) => JSON.stringify(entry)).join("\n") + "\n", "utf8");
  return entries;
}

export function defaultSourcePath(repositoryRoot) {
  return resolve(repositoryRoot, "examples/conversation.json");
}
