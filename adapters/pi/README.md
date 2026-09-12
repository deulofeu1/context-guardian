# `@context-guardian/pi`

[English](README.md) · [简体中文](README.zh-CN.md)

Pi adapter for Context Guardian.

## Installation

The package is published. Install the Python core and Pi adapter without cloning the
repository:

```bash
python3 -m pip install context-guardian-core
pi install npm:@context-guardian/pi
```

Pi `0.82.1` and Node.js `22.19.0+` are required. The adapter starts `python3` on
macOS/Linux and `python` on Windows for the core bridge. If the core is installed in a
virtual environment, set its absolute interpreter path:

```bash
export CONTEXT_GUARDIAN_PYTHON=/absolute/path/to/venv/bin/python
```

The bridge timeout defaults to 120 seconds and can be lowered with
`CONTEXT_GUARDIAN_TIMEOUT_MS` (values above 120 seconds are capped).

To try a checkout directly instead, use `pi -e` or the repository's interactive
fixture smoke. A `pi -e` load is temporary and does not need to be uninstalled.

The adapter reuses Pi's current model and credentials. It does not persist or forward
provider credentials to the Python process. If the bridge or review flow fails, Pi's
native compaction continues unchanged.

## Disable or uninstall

To temporarily disable a manually loaded extension, stop passing the `-e` option.
For a package installation, remove it from Pi settings:

```bash
pi remove npm:@context-guardian/pi
# For a project-local installation:
pi remove npm:@context-guardian/pi -l
```

`pi uninstall` is an alias. Removal does not delete project files or Pi sessions;
future `/compact` calls use Pi's native compaction.

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
