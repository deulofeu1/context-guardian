# Context Guardian for DeepSeek Harness

This adapter adds a human review step before DeepSeek Harness's native context compaction:

```text
Harness history → Context Guardian inspection → Keep / Drop review → native Harness summary
```

It is a decorator over `dsh-compaction-basic`. DeepSeek Harness continues to own compaction range selection, token accounting, durable session events, summary framing, persistence, and the `/compact` command. If Python, the bridge, model extraction, or human review is unavailable, the adapter logs a warning and continues with native compaction.

## Install

DeepSeek Harness is currently a developer preview, so this adapter is pinned to the `0.1.5-rc.x` API family.

```bash
dsh plugin --profile web add /absolute/path/to/ContextGuardian/adapters/deepseek-harness
```

This checkout command installs the local adapter tarball into the profile. After npm
publishing, the argument can be replaced with `context-guardian-deepseek-harness`.

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
