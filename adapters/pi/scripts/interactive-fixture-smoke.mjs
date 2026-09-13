import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import { defaultSourcePath, writeSessionFixture } from "./session-fixture.mjs";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(packageRoot, "../..");
const extension = resolve(packageRoot, "extensions/context-guardian.ts");
const piCommand = process.env.CONTEXT_GUARDIAN_PI ||
  (existsSync(resolve(repositoryRoot, "node_modules/.bin/pi"))
    ? resolve(repositoryRoot, "node_modules/.bin/pi")
    : "pi");
const pythonCandidates = [
  process.env.CONTEXT_GUARDIAN_PYTHON,
  resolve(repositoryRoot, ".venv313/bin/python"),
  resolve(repositoryRoot, ".venv/bin/python"),
].filter(Boolean);
const python = pythonCandidates.find((candidate) => existsSync(candidate));
const environment = { ...process.env };
if (!environment.CONTEXT_GUARDIAN_PYTHON && python) {
  environment.CONTEXT_GUARDIAN_PYTHON = python;
}
// Pi keeps roughly 20k recent tokens outside a compaction. The fixture must
// exceed that boundary so `/compact` exercises the real native path instead
// of returning "Nothing to compact (session too small)".
const requestedTurns = Number(process.env.CONTEXT_GUARDIAN_FIXTURE_TURNS || 320);
const fillerTurns = Number.isInteger(requestedTurns) && requestedTurns > 0 ? requestedTurns : 320;

const tempDir = await mkdtemp(resolve(tmpdir(), "context-guardian-fixture-") + "-");
const sessionPath = resolve(tempDir, "fixture.jsonl");
const entries = await writeSessionFixture(
  defaultSourcePath(repositoryRoot),
  tempDir,
  sessionPath,
  fillerTurns,
);

console.log(`Created ${entries.filter((entry) => entry.type === "message").length} messages.`);
console.log("Pi will open with the pre-seeded Context Guardian fixture.");
console.log("Run /compact and answer at most three topic-level Keep/Drop prompts.");
console.log("Expected automatic preservation: goal, API constraint, PostgreSQL decision, SQLite failure, and auth.py TODO.");
console.log("Expected: commands, logs, paths, hashes, and resolved temporary errors stay out of the UI.");
console.log("The npm fundamentals side discussion may appear as one bounded question.");
console.log("Then ask: What is the final database, why was SQLite rejected, and what is the auth.py status?");
console.log("Exit Pi with /quit when finished.");

const child = spawn(
  piCommand,
  ["--session", sessionPath, "--no-extensions", "-e", extension],
  { cwd: tempDir, env: environment, stdio: "inherit" },
);

const cleanup = async () => {
  if (process.env.CONTEXT_GUARDIAN_KEEP_FIXTURE === "1") {
    console.log(`Fixture kept at ${sessionPath}`);
    return;
  }
  await rm(tempDir, { recursive: true, force: true });
};

child.on("error", async (error) => {
  console.error(error instanceof Error ? error.message : String(error));
  await cleanup();
  process.exitCode = 1;
});

child.on("close", async (code, signal) => {
  await cleanup();
  if (signal) {
    process.exitCode = 1;
  } else if (code !== 0) {
    process.exitCode = code || 1;
  }
});
