import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const repositoryRoot = resolve(packageRoot, "../..");
const pythonCandidates = [
  process.env.CONTEXT_GUARDIAN_PYTHON,
  resolve(repositoryRoot, ".venv313/bin/python"),
  resolve(repositoryRoot, ".venv/bin/python"),
].filter(Boolean);
const python = pythonCandidates.find((candidate) => existsSync(candidate)) || "python3";

function runCheckpoint(input, output) {
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(python, ["-m", "context_guardian", "checkpoint", input, "--output", output], {
      cwd: repositoryRoot,
      env: { ...process.env, PYTHONPATH: repositoryRoot },
      stdio: "inherit",
    });
    child.once("error", rejectRun);
    child.once("close", (code) => {
      if (code === 0) resolveRun();
      else rejectRun(new Error(`Codex checkpoint fixture exited with ${String(code)}`));
    });
  });
}

const tempDir = await mkdtemp(resolve(tmpdir(), "context-guardian-codex-fixture-") + "-");
const input = resolve(tempDir, "messages.json");
const output = resolve(tempDir, ".agents/context-guardian.md");
const source = JSON.parse(await readFile(resolve(repositoryRoot, "examples/conversation.json"), "utf8"));
const messages = Array.from({ length: 8 }, () => source.messages).flat();
await writeFile(input, JSON.stringify({ messages }, null, 2) + "\n", "utf8");

console.log("Injected a pre-seeded Codex task conversation into the manual checkpoint path.");
console.log("Answer the Keep/Drop questions in this terminal.");
try {
  await runCheckpoint(input, output);
  const text = await readFile(output, "utf8");
  for (const expected of ["OAuth", "public API", "PostgreSQL", "SQLite", "auth.py"]) {
    if (!text.toLowerCase().includes(expected.toLowerCase())) throw new Error(`checkpoint is missing ${expected}`);
  }
  if (text.toLowerCase().includes("grep -r oauth")) throw new Error("checkpoint retained transient grep output");
  console.log(`PASS: reviewed Codex checkpoint written at ${output}`);
} finally {
  if (process.env.CONTEXT_GUARDIAN_KEEP_FIXTURE !== "1") await rm(tempDir, { recursive: true, force: true });
  else console.log(`Fixture kept at ${tempDir}`);
}
