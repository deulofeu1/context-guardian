# Changelog

## 0.1.2 - 2026-09-12 (DeepSeek Harness adapter)

- Made the DeepSeek Harness Python bridge safe on Windows by preserving the runtime
  variables required by Python and using the Windows `python` launcher by default.
- Added structured bridge error categories, a longer configurable timeout, and
  Windows CI coverage.
- Added package-specific release workflow inputs so adapter patch releases publish
  only the changed package.

## 0.1.1 - 2026-09-12

- Published the Python core, Pi adapter, and DeepSeek Harness adapter.
- Documented published-package installation, interactive verification, and safe
  disable/uninstall procedures for each host.
- Clarified that Claude Code and Codex remain exploratory integrations outside
  `main`.

## Unreleased

- Added portable `build_checkpoint()` output for assisted integrations.
- Added a shared adapter contract and capability matrix for host integrations.
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
