# Context Guardian for DeepSeek Harness

[English](README.md) · [简体中文](README.zh-CN.md)

This adapter adds a human review step before DeepSeek Harness's native context compaction:

```text
Harness history → Context Guardian inspection → Keep / Drop review → native Harness summary
```

It is a decorator over `dsh-compaction-basic`. DeepSeek Harness continues to own compaction range selection, token accounting, durable session events, summary framing, persistence, and the `/compact` command. If Python, the bridge, model extraction, or human review is unavailable, the adapter logs a warning and continues with native compaction.

## Install

DeepSeek Harness is currently a developer preview, so this adapter is pinned to the
`0.1.5-rc.x` API family. The adapter package is published; install it into the Web
profile with:

```bash
python3 -m pip install context-guardian-core
dsh plugin --profile web add context-guardian-deepseek-harness
```

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
when it loads and reports the number of inspection candidates and review candidates.

Start the web profile and use a sufficiently long session or `/compact`:

```bash
dsh --profile web
```

Review candidates appear through Harness's user-question UI. In headless compositions without an answerer, uncertain candidates are conservatively kept. For deterministic local testing, `CONTEXT_GUARDIAN_REVIEW_MODE=keep` or `drop` bypasses the question UI.

For a repeatable end-to-end UI test that does not require a long real conversation:

```bash
env PATH="/path/to/node-22.19/bin:$PATH" npm run dsh-fixture-smoke
```

The fixture creates an isolated Web profile, seeds a sufficiently large conversation,
opens the Harness UI, and pauses on a reviewable SQLite candidate. Select Keep or Drop,
then confirm the native `/compact` result. It uses a replay model, so no DeepSeek API
key is required. Exit the temporary Web process with Ctrl-C when finished.

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
