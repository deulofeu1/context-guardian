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
Exact Summary Edits + Reviewed Facts Appendix
  ↓
One Native Compaction Commit
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

The DeepSeek Harness adapter and Python core share a versioned bridge contract.
Keep them on the same `0.4.x` release line; do not upgrade the npm adapter while
leaving an older Python core installed. For a reproducible installation, pin the
core to the adapter's published version, for example:

```bash
python3 -m pip install "context-guardian-core==0.4.2"
dsh plugin --profile web add context-guardian-deepseek-harness@0.4.2
```

If a bridge operation is unsupported, the adapter now includes the underlying
error in its warning so a core/adapter mismatch is immediately diagnosable.

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
and the safe summary-edit / Reviewed Facts result. It is a fast core check, not a replacement for the interactive
Pi/DSH fixture tests.

For the source Pi workflow, use the interactive fixture from a checkout:

```bash
npm run pi-fixture-smoke
```

It opens Pi with a pre-seeded long conversation and lets you manually choose
explicit actions such as Apply correction / Keep current summary or Keep/Drop.
To load the source extension in an existing Pi session, see
[`adapters/pi/README.md`](adapters/pi/README.md).

For source development or release verification, install the local adapter into the
Web profile:

```bash
dsh plugin --profile web add "$PWD/adapters/deepseek-harness"
```

Inside Pi, the adapter asks Pi for one native Preview, audits it with the current host
model, applies only exact source-backed corrections, and adds deterministic Reviewed Facts after review. No second API key is
required. The Python process never receives those credentials.
The published adapter is tested against Pi `0.82.1` and Node.js `22.19.0+`.

For DeepSeek Harness:

```bash
dsh plugin --profile web add /absolute/path/to/ContextGuardian/adapters/deepseek-harness
```

This adapter decorates DeepSeek Harness's native `dsh-compaction-basic` backend.
It lets Harness produce one Preview, audits it through the active `ctx.llm` route,
asks at most three topic questions, applies only exact source-backed corrections, and adds one deterministic Reviewed Facts
block to the native result. Harness remains responsible for session persistence and the compaction
transaction. Web sessions use the selected agent preset, so the preset must contain
the Context Guardian compaction row.

The first real DeepSeek Harness Web run may ask you to configure a DeepSeek API key in
Harness. Enter it in Harness itself; Context Guardian never receives or forwards that
credential. A replay fixture is available for UI validation without a real key.

The audit model is untrusted and cannot promote a claim by itself. Provider findings
must cite an eligible message from the current compaction request, and each evidence
snippet is matched verbatim against that source before it can become a Review topic or
Reviewed Fact. A provider may use `display_summary` for readable or localized UI text,
but durable facts always use the validated source sentence. Host-internal planning
metadata, system/plugin messages, tool calls, paths, hashes, logs, and resolved
mechanical errors are excluded from the review surface.

## Modes

- Rules mode is local, deterministic, conservative, and the default for the CLI.
- Native adapters produce exactly one host Preview, then audit it; confirmed status corrections
  use exact unique replacements, while additions and retained topics become a deterministic
  Reviewed Facts block. No full conversation is copied into the summary.
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
| Pi | Native | Yes | Pi current model | Pi UI, max 3 topics | One Preview + Reviewed Facts appendix |
| DeepSeek Harness | Native | Yes | Harness current `ctx.llm` route | `userQuestions`, max 3 topics | One Preview + Reviewed Facts block |

The current release focuses on native compaction integrations. See
[`docs/adapter-contract.md`](docs/adapter-contract.md) and
[`adapters/capabilities.json`](adapters/capabilities.json) for the shared contract
and capability declaration.

## Python API

```python
from context_guardian import ContextGuardian

guardian = ContextGuardian()
messages = [{"role": "user", "content": "The project goal is ..."}]
plan = guardian.audit_preview(messages, preview="the host's native preview text")
finalization = guardian.finalize_preview(
    preview="the host's native preview text",
    review_plan=plan,
    answers=[],
    messages=messages,
)
print(plan.review_questions)
print(finalization.final_summary)

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
Apply correction / Keep current summary or Keep/Drop for uncertain topics. This means nobody needs to spend time creating a
long real conversation just to validate the adapter. The fixture uses the current Pi
model and authentication, so log in to Pi first if necessary. If the Python core is
outside the repository virtual environment, set `CONTEXT_GUARDIAN_PYTHON` explicitly.

The DeepSeek Harness adapter has the equivalent interactive fixture:

```bash
env PATH="/path/to/node-22.19/bin:$PATH" npm run dsh-fixture-smoke
```

It creates a temporary Harness profile and a pre-seeded long session, opens the Web UI,
and pauses on a single topic-level question about an npm fundamentals side discussion.
Select the session named `Context Guardian 预置长对话（请先选择）`, then enter
`/compact` and choose Keep or Drop. It also verifies that the goal, API constraint,
PostgreSQL decision, `auth.py` TODO, and SQLite rejection reason are appended to the
native Preview while transient grep/npm output is discarded. No real API key is needed
because the fixture uses a replay model.

For a real-model Web UI check, use the live fixture instead. It reuses the provider
and authentication already configured in DeepSeek Harness; the credential never
enters the Python process:

```bash
CONTEXT_GUARDIAN_DSH_LIVE=1 \
CONTEXT_GUARDIAN_FIXTURE_PACKAGE=context-guardian-deepseek-harness@0.4.2 \
npm run dsh-fixture-smoke
```

The live fixture seeds the same long session, adds one deliberately unresolved
future-relevant topic, and opens a real Harness Web session. Enter `/compact`, verify
that a bounded topic-level Review question appears, choose Keep or Drop, and confirm
that native compaction completes. The question can legitimately vary with the host
model; if the model already retains the topic in its Preview, no question is correct.
This is the important release check for the actual host path, while the replay fixture
is the deterministic check for CI.

Review text follows the dominant language of user-authored messages. Technical names
such as `OAuth`, `npm`, and `public API` remain unchanged, while host status text such
as `Compacting...` may still be supplied by Pi itself.

## License

MIT.
