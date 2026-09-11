# Changelog

## Unreleased

- Added portable `build_checkpoint()` output for assisted integrations.
- Added Claude Code `PreCompact` adapter with persisted checkpoints and fail-open
  behavior.
- Added Codex manual checkpoint skill and pre-seeded interactive Keep/Drop fixture.
- Added a shared adapter contract, capability matrix, Claude marketplace entry, and
  Codex marketplace entry.
- Added a DeepSeek Harness adapter that decorates native compaction with Context
  Guardian inspection, human review, host-model reuse, and fail-open fallback.
- Added a pre-seeded interactive DeepSeek Harness fixture smoke for manual Keep/Drop
  validation without requiring a long real conversation.
- Hardened the JSONL guidance bridge to validate candidates received over the wire.

## 0.1.0 - 2026-09-11

- Added framework-neutral Python inspection core.
- Added deterministic rules mode and optional structured providers.
- Added JSONL bridge for host-model calls.
- Added Pi compaction adapter with fail-open behavior.
- Added deterministic verification CLI, Pi RPC smoke test, pre-seeded interactive Pi
  fixture smoke test, example conversation, tests, and release documentation.
