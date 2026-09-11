# Context Guardian

> Never let your coding agent forget the wrong thing.

Context Guardian adds a human review layer before an AI agent compacts its context.
It does not replace the agent's memory system, summarizer, token manager, or native
compaction engine. It makes the hidden keep/drop decision inspectable.

```text
Context
  ↓
Inspect
  ↓
Auto Keep / Auto Drop
  ↓
Human Review
  ↓
Compaction Guidance
  ↓
Agent Native Compaction
```

## Why it exists

Agents often discard the reason a path was rejected. That can make them repeat the
same failed approach after compaction. Context Guardian surfaces durable decisions,
constraints, failed attempts, unfinished work, and transient noise before the host
agent summarizes the context.

## Quick start

From a checkout, install the Python core without an API key:

```bash
python -m pip install -e /absolute/path/to/ContextGuardian
context-guardian inspect examples/conversation.json
context-guardian inspect examples/conversation.json --json
context-guardian review examples/conversation.json
context-guardian verify examples/conversation.json
```

`verify` is a deterministic release smoke test. It needs no model or API key and
checks critical-memory retention, noise removal, stable candidate IDs, and rendered
guidance. It is a fast core check, not a replacement for the interactive Pi test.

For the Pi adapter:

```bash
python -m pip install -e /absolute/path/to/ContextGuardian
pi install npm:@context-guardian/pi
```

The npm command is for the published package; during local development use the
checkout's `adapters/pi` package as documented below.

Inside Pi, the adapter reuses the current host model and its existing credentials.
No second API key is required. The Python process never receives those credentials.
The published adapter is tested against Pi `0.82.1` and Node.js `22.19.0+`.

For DeepSeek Harness:

```bash
dsh plugin --profile web add /absolute/path/to/ContextGuardian/adapters/deepseek-harness
```

After the adapter is published, the path can be replaced with
`context-guardian-deepseek-harness`.

This adapter decorates DeepSeek Harness's native `dsh-compaction-basic` backend.
It reuses Harness's active model route for structured inspection, presents uncertain
candidates through Harness's user-question UI, and passes the resulting guidance back
into the native summary. Harness remains responsible for session persistence and the
compaction transaction. The adapter targets the DeepSeek Harness `0.1.5-rc.x` API
family and is installed as a separate package from the Pi adapter. Web sessions use
the selected agent preset, so the preset must contain the Context Guardian compaction
row; the adapter README documents the one-time preset setup.

## Modes

- Rules mode is local, deterministic, conservative, and the default for the CLI.
- Pi mode asks the host agent's current model for structured candidates, then uses
  Pi's native compaction helper with the resulting guidance.
- OpenAI is an optional standalone CLI provider: `pip install '.[openai]'` from the checkout.

If the bridge, model call, or review UI fails, the adapter fails open and lets native
Pi compaction continue normally.

## Python API

```python
from context_guardian import ContextGuardian

guardian = ContextGuardian()
result = guardian.inspect(messages)

decisions = [{"candidate_id": result.review[0].id, "action": "keep"}]
guidance = guardian.build_guidance(result.candidates, decisions)
print(guidance.text)
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
npm run smoke
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
