import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(packageRoot, "../..");
const pythonCandidates = [
  process.env.CONTEXT_GUARDIAN_PYTHON,
  resolve(repositoryRoot, ".venv313/bin/python"),
  resolve(repositoryRoot, ".venv/bin/python"),
].filter(Boolean);
const python = pythonCandidates.find((candidate) => existsSync(candidate)) || "python3";
const hook = resolve(packageRoot, "hooks/precompact.py");

function shellQuote(value) {
  return `'${String(value).replaceAll("'", "'\\''")}'`;
}

function runHook(input, cwd, tempDir, label, choices) {
  return new Promise((resolveRun, rejectRun) => {
    const inputPath = resolve(tempDir, `${label}.input.json`);
    const outputPath = resolve(tempDir, `${label}.output.json`);
    writeFile(inputPath, JSON.stringify(input) + "\n", "utf8").then(() => {
      const command = `${shellQuote(python)} ${shellQuote(hook)} < ${shellQuote(inputPath)} > ${shellQuote(outputPath)}`;
      const child = spawn("sh", ["-c", command], {
        cwd,
        env: {
          ...process.env,
          PYTHONPATH: repositoryRoot,
          ...(choices ? { CONTEXT_GUARDIAN_REVIEW_CHOICES: choices.join(",") } : {}),
        },
        stdio: "inherit",
      });
      child.once("error", rejectRun);
      child.once("close", async (code) => {
        if (code !== 0) {
          rejectRun(new Error(`Claude Code fixture hook exited with ${String(code)}`));
          return;
        }
        const output = await readFile(outputPath, "utf8");
        resolveRun(output.trim() ? JSON.parse(output.trim().split("\n").at(-1)) : {});
      });
    });
  });
}

async function chooseReviewCandidates() {
  if (process.env.CONTEXT_GUARDIAN_REVIEW_MODE === "keep") return ["keep", "keep"];
  if (process.env.CONTEXT_GUARDIAN_REVIEW_MODE === "drop") return ["drop", "drop"];
  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    console.log("No terminal detected; the fixture keeps unresolved candidates conservatively.");
    return ["keep", "keep"];
  }
  const { createInterface } = await import("node:readline/promises");
  const readline = createInterface({ input: process.stdin, output: process.stdout });
  const choices = [];
  try {
    console.log("Review candidate 1: SQLite failed attempt");
    choices.push((await readline.question("Keep it? [Y/n] ")).trim().toLowerCase() === "n" ? "drop" : "keep");
    console.log("Review candidate 2: unfinished auth.py state");
    choices.push((await readline.question("Keep it? [Y/n] ")).trim().toLowerCase() === "n" ? "drop" : "keep");
    return choices;
  } finally {
    readline.close();
  }
}

const tempDir = await mkdtemp(resolve(tmpdir(), "context-guardian-claude-fixture-") + "-");
const cwd = resolve(tempDir, "workspace");
const transcript = resolve(tempDir, "transcript.jsonl");
await import("node:fs/promises").then(({ mkdir }) => mkdir(cwd, { recursive: true }));

const source = JSON.parse(await readFile(resolve(repositoryRoot, "examples/conversation.json"), "utf8"));
const transcriptLines = source.messages.map((message, index) => JSON.stringify({
  type: message.role === "tool" ? "tool_result" : message.role,
  uuid: `claude-fixture-${String(index + 1).padStart(4, "0")}`,
  message: {
    role: message.role,
    content: message.content,
    name: message.tool_name,
    is_error: message.is_error,
  },
}));
await writeFile(transcript, transcriptLines.join("\n") + "\n", "utf8");

console.log("Injected a pre-seeded Claude Code transcript into the real PreCompact hook.");
console.log("Answer the Keep/Drop questions in this terminal.");
console.log("The first hook call must block and write a checkpoint; the second must allow native compaction.");

try {
  const choices = await chooseReviewCandidates();
  const first = await runHook({
    session_id: "claude-fixture-session",
    transcript_path: transcript,
    cwd,
    hook_event_name: "PreCompact",
    trigger: "manual",
    custom_instructions: null,
  }, cwd, tempDir, "first", choices);
  if (first.decision !== "block") throw new Error("first PreCompact call did not block after review");

  const checkpoint = resolve(cwd, ".claude/context-guardian.md");
  const text = await readFile(checkpoint, "utf8");
  for (const expected of ["OAuth", "public API", "PostgreSQL", "SQLite", "auth.py"]) {
    if (!text.toLowerCase().includes(expected.toLowerCase())) {
      throw new Error(`checkpoint is missing ${expected}`);
    }
  }
  if (text.toLowerCase().includes("grep -r oauth")) throw new Error("checkpoint retained transient grep output");

  const second = await runHook({
    session_id: "claude-fixture-session",
    transcript_path: transcript,
    cwd,
    hook_event_name: "PreCompact",
    trigger: "manual",
    custom_instructions: `Read ${checkpoint} and preserve every reviewed item.`,
  }, cwd, tempDir, "second");
  if (Object.keys(second).length !== 0) throw new Error("second PreCompact call did not allow native compaction");
  console.log(`PASS: checkpoint written at ${checkpoint}; native compaction may proceed on the second call.`);
} finally {
  if (process.env.CONTEXT_GUARDIAN_KEEP_FIXTURE !== "1") await rm(tempDir, { recursive: true, force: true });
  else console.log(`Fixture kept at ${tempDir}`);
}
