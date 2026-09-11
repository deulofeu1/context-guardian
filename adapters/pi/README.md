# `@context-guardian/pi`

Pi adapter for Context Guardian. Install the Python core first:

```bash
pip install context-guardian
pi install npm:@context-guardian/pi
```

The adapter reuses Pi's current model and credentials. It does not persist or forward
provider credentials to the Python process. If the bridge or review flow fails, Pi's
native compaction continues unchanged.

Compatibility: Pi `0.82.1` and Node.js `22.19.0+`.

From the repository root, run the fast no-key smoke test:

```bash
npm install
npm run pi-smoke
```

This checks the Python bridge and that Pi can load the extension in RPC mode. It does
not call a model and is suitable for CI.

For the full integration check, use the interactive fixture:

```bash
npm run pi-fixture-smoke
```

The script creates a temporary session with a pre-seeded long conversation, opens Pi,
and lets you run `/compact` and manually choose Keep/Drop. It exercises the actual
host-model, review UI, guidance, and native compaction flow without requiring a user to
first conduct a long conversation. Pi must be authenticated because the adapter reuses
the current host model. If the Python core is outside the repository virtual
environment, set `CONTEXT_GUARDIAN_PYTHON` explicitly.
