# Context Guardian for Claude Code

[English](README.md) · [简体中文](README.zh-CN.md)

Claude Code adapter for Context Guardian. It uses Claude Code's official `PreCompact`
hook to inspect the transcript before `/compact`, review uncertain candidates, and
write a short preservation checkpoint.

## Current status

Claude Code's `PreCompact` hook can block compaction, but its hook contract does not
provide an `additionalContext` channel for injecting text into the same compaction
request. Therefore the adapter uses a safe two-step flow for manual compaction:

```text
/compact
  ↓
PreCompact hook
  ↓
Keep / Drop review
  ↓
write .claude/context-guardian.md
  ↓
block once
  ↓
/compact Read .claude/context-guardian.md and preserve every reviewed item
  ↓
Claude Code native compaction
```

Automatic compaction writes a checkpoint and fails open to native compaction. This
avoids blocking an already-full context when the user cannot immediately provide the
checkpoint as custom instructions.

## Install from this checkout

Install the Python core first, then load the plugin for a Claude Code session:

```bash
python3 -m pip install -e /absolute/path/to/ContextGuardian
claude --plugin-dir /absolute/path/to/ContextGuardian/adapters/claude-code
```

The hook uses the local rules inspector. Claude Code does not expose its current
model invocation to an external command hook, so no second API key is requested and
no credentials are passed to Python. The rules fallback is conservative and can be
used without a model.

The checkpoint path defaults to `.claude/context-guardian.md`. Override it with
`CONTEXT_GUARDIAN_CLAUDE_CHECKPOINT`; use `CONTEXT_GUARDIAN_REVIEW_MODE=keep` or
`drop` for deterministic automation.

After release, install the Python core and marketplace plugin without cloning this
repository:

```bash
python -m pip install context-guardian-core
claude plugin marketplace add deulofeu1/context-guardian
claude plugin install context-guardian-claude@context-guardian
```

## Interactive fixture

Run the repeatable hook fixture from the repository root:

```bash
npm run claude-fixture-smoke
```

It injects a pre-seeded Claude-style transcript into the real `PreCompact` hook,
opens Keep/Drop questions in the terminal, verifies that the first invocation blocks
and writes a checkpoint, then verifies that a second invocation with the checkpoint
instruction allows native compaction to continue. It does not require a long real
conversation or an API key. For final Claude Code UI acceptance, load the plugin and
run `/compact` in a real session.

## Compatibility and failure behavior

The adapter targets the current Claude Code `PreCompact` command-hook contract. If
the transcript, Python core, review terminal, or checkpoint write fails, it emits a
warning on stderr and returns an empty allow response so Claude Code's native
compaction can continue.
