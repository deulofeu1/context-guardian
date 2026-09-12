# Context Guardian

> Never let your coding agent forget the wrong thing.

[English](README.md) · [简体中文](README.zh-CN.md)

> Experimental Alpha: Context Guardian does not guarantee better context
> compression, summaries, or agent performance. It is an inspection and human-review
> layer around a host agent's native compaction, not a proven context optimizer.

Context Guardian adds a human review layer before an AI agent compacts its context.
It does not replace the agent's memory system, summarizer, token manager, or native
compaction engine. It makes the hidden keep/drop decision inspectable.

```text
Context
  ↓
Native Preview
  ↓
Semantic Audit
  ↓
Auto Correct / Accept Preview
  ↓
At most 3 Topic Questions
  ↓
Incremental Guidance
  ↓
Agent Native Compaction
```

## Why it exists

Agents often discard the reason a path was rejected. That can make them repeat the
same failed approach after compaction. Context Guardian audits the host's native
preview for durable decisions, constraints, failed attempts, unfinished work, and
transient noise. Human review is topic-level, not sentence-level.

## Experimental status and project scope

This is an experimental Alpha project. The current implementation is a practical
testbed for human-in-the-loop compaction control, not a claim that every real-world
conversation will produce a better summary or improve an agent's downstream work.
The review policy can make false-positive and false-negative decisions, and outcomes
depend on the host version, model, conversation, provider behavior, and human choices.

Use Context Guardian to explore the design, run repeatable fixtures, and build new
host adapters or policies on top of the core. Treat the output as advisory guidance
for the host's native compactor. Keep a rollback path and validate it on your own
workloads before relying on it for important sessions.

## Quick start

### Install the published packages

The Python core and both host adapters are published. The host CLIs remain separate
prerequisites, but you do not need to clone this repository or install its workspace
dependencies for normal use. The Python distribution is named
`context-guardian-core`; its installed CLI remains `context-guardian`.

For Pi, install the core and adapter:

```bash
python3 -m pip install context-guardian-core
pi install npm:@context-guardian/pi
```

Pi `0.82.1` and Node.js `22.19.0+` are required. If the core is installed in a
virtual environment, point the adapter at that interpreter before starting Pi:

```bash
export CONTEXT_GUARDIAN_PYTHON=/absolute/path/to/venv/bin/python
```

For DeepSeek Harness, install the core and adapter into the Web profile:

```bash
python3 -m pip install context-guardian-core
dsh plugin --profile web add context-guardian-deepseek-harness
```

DeepSeek Harness `0.1.5-rc.x` and Node.js `22.19.0+` are required. Harness Web
also needs a one-time preset change; see the adapter guide below.

Package publication is designed around npm Trusted Publishing with GitHub Actions
OIDC. The release workflow does not use a long-lived `NPM_TOKEN`; configure the
trusted publisher for each npm package as described in
[`docs/publishing.md`](docs/publishing.md).

### Use this repository today

```bash
git clone https://github.com/deulofeu1/context-guardian.git
cd context-guardian

python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
npm install
```

The workspace install does not install the host CLI itself. The Pi workflow expects
Pi `0.82.1` and Node.js `22.19.0+`; the DeepSeek Harness workflow expects the
DeepSeek Harness `0.1.5-rc.x` API family and the same Node.js runtime.

Now run the local Python CLI without an API key:

```bash
context-guardian inspect examples/conversation.json
context-guardian inspect examples/conversation.json --preview-file native-preview.txt --json
context-guardian review examples/conversation.json --preview-file native-preview.txt
context-guardian verify examples/conversation.json
```

`verify` is a deterministic release smoke test. It needs no model or API key and
checks native-preview audit corrections, noise removal, stable IDs, bounded questions,
and rendered guidance. It is a fast core check, not a replacement for the interactive
Pi/DSH fixture tests.

For the source Pi workflow, use the interactive fixture from a checkout:

```bash
npm run pi-fixture-smoke
```

It opens Pi with a pre-seeded long conversation and lets you manually choose
Keep/Drop. To load the source extension in an existing Pi session, see
[`adapters/pi/README.md`](adapters/pi/README.md).

For source development or release verification, install the local adapter into the
Web profile:

```bash
dsh plugin --profile web add "$PWD/adapters/deepseek-harness"
```

Inside Pi, the adapter first asks Pi for a native Preview, audits it with the current
host model, and retries native compaction only when correction is needed. No second API
key is required. The Python process never receives those credentials.
The published adapter is tested against Pi `0.82.1` and Node.js `22.19.0+`.

For DeepSeek Harness:

```bash
dsh plugin --profile web add /absolute/path/to/ContextGuardian/adapters/deepseek-harness
```

This adapter decorates DeepSeek Harness's native `dsh-compaction-basic` backend.
It lets Harness produce a Preview, audits it through the active `ctx.llm` route,
asks at most three topic questions, and performs one guided native retry only when
needed. Harness remains responsible for session persistence and the compaction
transaction. Web sessions use the selected agent preset, so the preset must contain
the Context Guardian compaction row.

## Modes

- Rules mode is local, deterministic, conservative, and the default for the CLI.
- Native adapters produce a host Preview first, then audit it; automatic corrections
  and confirmed topic decisions become incremental instructions for one native retry.
- The default review budget is three topic questions and can be lowered with
  `CONTEXT_GUARDIAN_MAX_REVIEW_QUESTIONS=0..3`. Zero disables questions and uses
  conservative no-UI resolution.
- OpenAI is an optional standalone CLI provider: `pip install 'context-guardian-core[openai]'` when needed.

If the bridge, model call, or review UI fails, the adapter fails open and lets native
Pi compaction continue normally.

## Disable or uninstall

Both adapters are opt-in and reversible. They do not lock a project or session into
Context Guardian.

For Pi, stop loading the extension if you used `pi -e`. For a package installation,
remove it from user settings:

```bash
pi remove npm:@context-guardian/pi
# For a project-local installation:
pi remove npm:@context-guardian/pi -l
```

`pi uninstall` is an alias for `pi remove`. Removing the package leaves your project
files and Pi session data untouched; future `/compact` calls use Pi's native path.

For DeepSeek Harness, first select the native `standard` preset in
`Settings → Agent Presets`, make it the default, and start a new session. To remove
the adapter from the Web profile completely:

```bash
dsh plugin --profile web remove context-guardian-deepseek-harness
```

You may then delete the custom `context-guardian` preset. Switching presets is enough
for a temporary disable; removing the plugin is the full uninstall. DSH's profile
bundle and preset layers are separate, so switching back to `standard` must happen
before removing the bundle. If an uninstall command fails, inspect the selected
profile with `dsh plugin --profile web list` before making manual changes.

Claude Code and Codex are not part of the `main` release. Their earlier experimental
adapters remain on the `exploration/claude-code-codex` branch. If you installed an
experimental Claude Code `PreCompact` hook locally, remove only that hook from your
Claude Code settings; otherwise no CC restoration is needed.

## Integrations

| Platform | Level | Auto trigger | Host model | Human review | Preservation |
| --- | --- | --- | --- | --- | --- |
| Pi | Native | Yes | Pi current model | Pi UI, max 3 topics | Preview audit + native `customInstructions` retry |
| DeepSeek Harness | Native | Yes | Harness current `ctx.llm` route | `userQuestions`, max 3 topics | Preview audit + native input retry |

The current release focuses on native compaction integrations. See
[`docs/adapter-contract.md`](docs/adapter-contract.md) and
[`adapters/capabilities.json`](adapters/capabilities.json) for the shared contract
and capability declaration.

## Python API

```python
from context_guardian import ContextGuardian

guardian = ContextGuardian()
plan = guardian.audit_preview(messages, preview="the host's native preview text")
revision = guardian.build_revision_guidance(review_plan=plan, answers=[])
print(plan.review_questions)
print(revision.text)

# Checkpoint generation remains available for assisted integrations through
# guardian.build_checkpoint(...).
```

## Project boundary

Context Guardian intentionally does not implement an agent loop, context window
management, conversation persistence, vector database, RAG, or a competing summarizer.
If the host agent already provides a capability, the adapter reuses it.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
ruff check .

npm install
npm run typecheck
npm run typecheck:dsh
npm run test:dsh
npm run pi-smoke
npm run pi-fixture-smoke
npm run dsh-fixture-smoke
```

The fast Pi smoke test loads the extension in RPC mode and exercises the Python JSONL
bridge without requiring a live model call. The important end-to-end check is the
interactive fixture smoke test:

```bash
npm run pi-fixture-smoke
```

It creates a temporary Pi session containing a pre-seeded, sufficiently large
conversation, opens the Pi UI, and lets you run `/compact` and manually choose
Keep/Drop for uncertain candidates. This means nobody needs to spend time creating a
long real conversation just to validate the adapter. The fixture uses the current Pi
model and authentication, so log in to Pi first if necessary. If the Python core is
outside the repository virtual environment, set `CONTEXT_GUARDIAN_PYTHON` explicitly.

The DeepSeek Harness adapter has the equivalent interactive fixture:

```bash
env PATH="/path/to/node-22.19/bin:$PATH" npm run dsh-fixture-smoke
```

It creates a temporary Harness profile and a pre-seeded long session, opens the Web UI,
and pauses on an uncertain SQLite decision so you can select Keep or Drop. It also
verifies that the goal, API constraint, PostgreSQL decision, `auth.py` TODO, and useful
failure context reach native compaction guidance while transient grep/npm output is
discarded. No real API key is needed because the fixture uses a replay model.

## License

MIT.
