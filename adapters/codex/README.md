# Context Guardian for Codex

[English](README.md) · [简体中文](README.zh-CN.md)

Codex integration for Context Guardian at the assisted checkpoint level.

Codex does not currently expose a supported pre-compaction hook that this project can
use to intercept native compaction. This adapter therefore provides a manual
`context-guardian` skill and a portable checkpoint file rather than claiming automatic
compaction control.

## Flow

```text
Codex task
  ↓
manual Context Guardian skill
  ↓
collect current messages
  ↓
Keep / Drop review
  ↓
.agents/context-guardian.md
  ↓
Codex continues and reads the checkpoint
```

## Install from this checkout

Install the Python core, then add the local Codex marketplace/plugin as supported by
your Codex CLI. The repository includes the plugin manifest and skill under this
directory. For a local project checkout, the skill can also be copied into
`.agents/skills/context-guardian/`.

The command used by the skill is:

```bash
context-guardian checkpoint messages.json --output .agents/context-guardian.md
```

It uses the same Inspector, Policy and ReviewDecision models as the native Pi and
DeepSeek Harness adapters. Unresolved candidates are kept conservatively.

After release, install the Python core and Codex plugin without cloning this
repository:

```bash
python -m pip install context-guardian-core
codex plugin marketplace add deulofeu1/context-guardian
codex plugin add context-guardian-codex@context-guardian
```

## Interactive fixture

From the repository root:

```bash
npm run codex-fixture-smoke
```

The fixture injects the shared OAuth scenario, pauses for real Keep/Drop choices, and
verifies the generated checkpoint contains the goal, public API constraint, PostgreSQL
decision, SQLite failure reason and `auth.py` TODO while excluding command output.
It verifies the manual checkpoint integration, not a nonexistent Codex native hook.
