import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
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
const replayProvider = "context-guardian-replay";
const replayModel = "guardian-fixture";

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
  push("request/header", {
    header: {
      config: { provider: replayProvider, model: replayModel },
    },
    reason: "initial",
  });

  const durableTurns = [
    "Goal: implement OAuth without changing the public API.",
    "Constraint: existing API compatibility must be preserved.",
    "Decision: PostgreSQL is the final database choice.",
    "SQLite was considered but abandoned because concurrent writes caused locking problems.",
    "TODO: auth.py is still incomplete and needs the OAuth callback implementation.",
    "Working state: the provider abstraction is wired, but the callback path is not finished.",
    "User preference: keep the patch small and avoid adding a new service.",
    "The migration tests cover the existing public API and must continue to pass.",
    "We should document the OAuth redirect URI and the production callback environment variables.",
    "The rejected SQLite approach should not be tried again unless the concurrency design changes.",
    "The next implementation step is to finish auth.py and then run the compatibility suite.",
    "Current status: the main design is settled; only the callback and final verification remain.",
  ];
  const noisyTurns = [
    "grep -R OAuth src/",
    "npm install completed successfully.",
    "Temporary syntax error fixed during local debugging.",
    "npm warn deprecated package output from the install command.",
    "rg --files | head -50",
  ];
  const allTurns = [...durableTurns, ...noisyTurns, ...durableTurns, ...noisyTurns];
  for (let index = 0; index < allTurns.length; index += 1) {
    const step = index + 1;
    if (index > 0) push("step/start", { turn: 1, step });
    const userText = allTurns[index];
    push("user/message", createUserMessage({
      content: [{ type: "text", text: userText }],
      source: { kind: "user" },
    }), { surfaceOp: "append" });

    const assistantText = userText.startsWith("grep") || userText.startsWith("npm") || userText.startsWith("rg")
      ? `Observed transient command output: ${userText}`
      : `Acknowledged project state: ${userText}`;
    const assistant = createAssistantMessage({
      content: [{ type: "text", text: assistantText }],
      source: { provider: replayProvider, model: replayModel },
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

  push("turn/end", { turn: 1, reason: { kind: "completed" } });
  return events;
}

async function seedSession(root, cwd) {
  const ctx = new Context();
  await ctx.plugin(JsonlSessionPersistence, { root, compression: "none" });
  const id = SessionId(`context-guardian-fixture-${randomUUID()}`);
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
    await handle.append(buildFixtureEvents());
    await handle.close();
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
  const dshHome = resolve(tempDir, ".dsh");
  const cwd = resolve(tempDir, "workspace");
  const sessionsRoot = resolve(tempDir, "sessions");
  const profile = "context-guardian-fixture";
  const fixturePath = resolve(tempDir, "replay-session.jsonl");
  const overridePath = resolve(tempDir, "replay.override.json");
  const patchPath = resolve(tempDir, "smoke.patch.yml");
  const agentPresetDir = resolve(dshHome, ".agent-presets", "context-guardian-fixture");
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
  await seedSession(sessionsRoot, cwd);

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
  await writeFile(fixturePath, JSON.stringify({
    version: 3,
    isSeeded: false,
    createdAt: 0,
    cwd,
    delegationDepth: 0,
    type: "session",
    id: "fixture-replay",
  }) + "\n", "utf8");
  const summary = "## Primary Request and Intent\n- Implement OAuth without changing the public API.\n\n## Key Technical Concepts\n- Preserve existing API compatibility.\n\n## Files and Code\n- auth.py: OAuth callback remains incomplete.\n\n## Errors and Fixes\n- SQLite was rejected because of concurrent-write locking problems.\n\n## Pending Jobs\n- Finish auth.py and run compatibility tests.\n\n## Current Work\n- The provider abstraction is wired; the callback remains.\n\n## Next Step\n- Implement the OAuth callback.\n\n## Critical Context\n- PostgreSQL is final; do not repeat the rejected SQLite path.\n";
  await writeFile(overridePath, JSON.stringify([
    {
      kind: "chunks",
      chunks: [
        { type: "block-start", index: 0, blockType: "text" },
        { type: "text-delta", index: 0, text: JSON.stringify(inspectionResult) },
        { type: "block-end", index: 0, block: { type: "text", text: JSON.stringify(inspectionResult) } },
        { type: "finish", reason: { kind: "stop" } },
      ],
    },
    {
      kind: "chunks",
      chunks: [
        { type: "block-start", index: 0, blockType: "text" },
        { type: "text-delta", index: 0, text: summary },
        { type: "block-end", index: 0, block: { type: "text", text: summary } },
        { type: "finish", reason: { kind: "stop" } },
      ],
    },
  ], null, 2) + "\n", "utf8");
  await writeFile(patchPath, [
    "- id: session-persistence-jsonl",
    "  config:",
    `    root: ${quoteYaml(sessionsRoot)}`,
    "    compression: none",
    "- id: agent-default-model",
    "  config:",
    `    provider: ${quoteYaml(replayProvider)}`,
    `    model: ${quoteYaml(replayModel)}`,
    "- id: llm-deepseek",
    "  disabled: true",
    "- id: agent-presets",
    "  config:",
    "    default: context-guardian-fixture",
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
  ].join("\n") + "\n", "utf8");

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
    await run(dsh, ["plugin", "--profile", profile, "add", packageTarball], { env: environment });
    await run(dsh, ["plugin", "--profile", profile, "add", "@deepseek-ai/dsh-llm-replay@0.1.5-rc.2"], { env: environment });

    console.log("");
    console.log("DeepSeek Harness Context Guardian fixture is ready.");
    console.log("Open the printed Web URL, select the seeded session, enter /compact, and choose Keep/Drop.");
    console.log("Expected Keep: goal, API constraint, PostgreSQL, SQLite failure, auth.py TODO.");
    console.log("Expected Drop: grep/npm output and the resolved temporary error.");
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
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
