# Context Guardian for DeepSeek Harness

[English](README.md) · [简体中文](README.zh-CN.md)

This adapter audits a native Preview before DeepSeek Harness commits context compaction:

```text
Harness native Preview → Context Guardian Audit → auto correction / max 3 topic questions
→ exact status correction or deterministic Reviewed Facts block → native Harness compaction commit
```

It is a decorator over `dsh-compaction-basic`. DeepSeek Harness continues to own compaction range selection, token accounting, durable session events, summary framing, persistence, and the `/compact` command. The adapter makes one native `summarize()` call, applies only exact source-backed edits to text blocks, and adds one deterministic Reviewed Facts content block when needed. Non-text summary blocks and metadata are preserved. If Python, the bridge, audit, review UI, or finalization is unavailable, the adapter logs a warning and accepts the successful Preview. This is experimental and does not guarantee better summaries or agent performance.

The hard review budget is controlled by `CONTEXT_GUARDIAN_MAX_REVIEW_QUESTIONS=0..3`;
zero disables questions and resolves uncertain topics conservatively.

## Install

DeepSeek Harness is currently a developer preview, so this adapter is pinned to the
`0.1.5-rc.x` API family. The adapter package is published; install it into the Web
profile with:

```bash
python3 -m pip install context-guardian-core
dsh plugin --profile web add context-guardian-deepseek-harness
```

The adapter and Python core share a versioned bridge contract and must stay on
the same `0.4.x` release line. Pin both sides when reproducing a published setup;
for example, the `0.4.0` pair is:

```bash
python3 -m pip install "context-guardian-core==0.4.0"
dsh plugin --profile web add context-guardian-deepseek-harness@0.4.0
```

If an older core does not recognize an operation used by the adapter, the
adapter's fail-open warning includes the underlying bridge error instead of
silently hiding the compatibility problem.

For a source checkout, replace the package name with
`/absolute/path/to/ContextGuardian/adapters/deepseek-harness`.

Because DeepSeek Harness Web composes compaction inside the selected agent preset,
installing the package alone does not replace the `standard` preset's nested native
backend. Create a user preset based on `standard`, replace its `compaction-basic` row
with `context-guardian-deepseek-harness`, and select that preset (or make it the
default). The preset must contain this compaction group:

```yaml
- id: compaction
  name: cordis:group
  group: true
  isolate:
    compaction: true
    toolResultPruner: true
  config:
    - id: context-guardian-compaction
      name: context-guardian-deepseek-harness
    - id: command-compact
      name: '@deepseek-ai/dsh-command-compact'
    - id: tool-result-pruner
      name: '@deepseek-ai/dsh-compaction-tool-result-pruner'
```

Keep the rest of the copied `standard` preset unchanged. This is required because
DeepSeek Harness mounts the preset in a per-session scope; a profile-level plugin row
cannot override the preset's own `compaction-basic` row.

Install the Python core in the same environment used by `dsh`, or point the adapter at an interpreter explicitly:

```bash
python3 -m pip install -e /absolute/path/to/ContextGuardian
export CONTEXT_GUARDIAN_PYTHON=/absolute/path/to/python
```

The adapter does not receive or forward `DEEPSEEK_API_KEY`. Structured inspection calls go back through DeepSeek Harness's active `ctx.llm` route, so Harness remains the only process that resolves provider credentials.

Provider audit output is untrusted. Findings must cite a message from the current
request and evidence snippets must match that message verbatim before they can become
Review topics or Reviewed Facts. Readable or translated provider text is display-only;
the UI shows original source evidence separately and persists only the validated source
sentence. Host planning metadata, system/plugin messages, tool calls, paths, hashes,
logs, and resolved mechanical errors cannot enter the review UI. This is the same
provenance rule used by the Pi adapter.

If the core is installed in a virtual environment, set
`CONTEXT_GUARDIAN_PYTHON=/absolute/path/to/venv/bin/python` before starting Harness.

On Windows, the bridge preserves the runtime variables required by Python's networking
stack while still passing only an explicit minimal environment to the child process. If
the `python3` command resolves to the Microsoft Store placeholder, set the interpreter
explicitly in the same PowerShell session used to start Harness:

```powershell
$env:CONTEXT_GUARDIAN_PYTHON = (Get-Command python).Source
$env:CONTEXT_GUARDIAN_DEBUG = "1"
$env:CONTEXT_GUARDIAN_TIMEOUT_MS = "120000"
dsh --profile web
```

The bridge timeout defaults to 120 seconds and can be lowered with
`CONTEXT_GUARDIAN_TIMEOUT_MS` (up to 120 seconds). With debug enabled, the adapter logs
when it loads and reports only audit finding and topic-question counts (never raw prompt contents).

Start the web profile and use a sufficiently long session or `/compact`:

```bash
dsh --profile web
```

Review topics appear through Harness's user-question UI. In headless compositions
without an answerer, the adapter reports that Review UI is unavailable and accepts the
successful native Preview. For an explicitly configured no-UI run, set
`CONTEXT_GUARDIAN_NO_UI=1`; unresolved topics then use their conservative recommendations.

For a repeatable end-to-end UI test that does not require a long real conversation:

```bash
env PATH="/path/to/node-22.19/bin:$PATH" npm run dsh-fixture-smoke
```

The fixture creates an isolated Web profile, seeds a sufficiently large conversation,
deliberately omits selected facts from the replayed native Preview, and opens the
Harness UI. Select the session named `Context Guardian 预置长对话（请先选择）`
(or the `context-guardian-fixture-long` workspace), then enter `/compact`. The UI
should show at most three topic questions, including a source-backed status correction;
select Apply correction or Keep current summary and confirm the native
Preview with its deterministic Reviewed Facts block. It uses a replay model, so no
DeepSeek API key is required.
Exit the temporary Web process with Ctrl-C when finished.

For release verification against the real Harness host and its configured model,
run the same fixture in live mode:

```bash
CONTEXT_GUARDIAN_DSH_LIVE=1 \
CONTEXT_GUARDIAN_FIXTURE_PACKAGE=context-guardian-deepseek-harness@0.4.0 \
npm run dsh-fixture-smoke
```

Live mode uses the existing DSH home and provider route, so the configured Harness
credential stays inside Harness and is never passed to Python. It seeds a long session
with one deliberately unresolved future-relevant topic. In the Web UI, enter
`/compact`, confirm that a bounded topic-level Review question appears, manually choose
Keep or Drop, and confirm that native compaction finishes. The exact question is model-
dependent: if the native Preview already keeps the topic, zero questions is a valid
result. Use replay mode for deterministic CI and live mode for the actual host/UI check.

## Disable or uninstall

To temporarily disable Context Guardian, open `Settings → Agent Presets`, select the
native `standard` preset, make it the default, and start a new session. The custom
preset can remain available for later use.

For a full uninstall, switch away from the custom preset first, then remove the
profile plugin and optionally delete the custom preset:

```bash
dsh plugin --profile web remove context-guardian-deepseek-harness
```

The native `standard` preset restores Harness's original compaction path. If the
remove command fails, inspect the selected profile with
`dsh plugin --profile web list` before making manual changes.

## Local development

```bash
npm install
npm --workspace adapters/deepseek-harness run typecheck
```

To test a checkout before publishing, install the adapter into a Harness profile from the repository directory:

```bash
dsh plugin --profile web add /absolute/path/to/ContextGuardian/adapters/deepseek-harness
```

The profile bundle disables the stock `compaction-basic` row and inserts the decorated backend. The adapter is intentionally separate from the Python distribution and from the Pi adapter, so each host can evolve against its own lifecycle and UI contract.
