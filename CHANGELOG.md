# Changelog

## 0.3.2 - 2026-09-15 (Host audit review and fact rendering)

- Preserved source-grounded Host Provider review requests so uncertain topics can
  reach the bounded interactive Review UI instead of being silently discarded.
- Expanded short provider evidence phrases to complete source sentences or
  bounded source context before writing Reviewed Facts.
- Added regression coverage for Host Provider Review reachability and complete
  Reviewed Facts rendering, including short noun-phrase evidence.

## 0.3.1 - 2026-09-14 (Source-grounded audit)

- Added explicit host-message provenance so system, plugin planning metadata,
  compaction bookkeeping, tool calls, and mechanical execution noise cannot become
  Review topics or Reviewed Facts.
- Revalidated every provider finding against request-local source IDs and exact
  evidence snippets, including a second validation before facts are written.
- Added the Issue #9 regression fixture for planning metadata such as
  `task_plan.md`, `findings.md`, and `progress.md`.
- Preserved bounded topic-level review and fail-open native compaction behavior.

## 0.3.0 - 2026-09-14 (Single native compaction)

- Replaced the optional second native compaction with one native Preview followed by
  deterministic, append-only Reviewed Facts finalization.
- Added versioned `ReviewedFact`, `ReviewedFactsAppendix`, and `PreviewFinalization`
  core APIs with stable IDs, deduplication, carried-forward facts, and Chinese/English
  rendering.
- Updated Pi and DeepSeek Harness adapters to preserve native result metadata and make
  exactly one host compaction call per operation.
- Added bridge support, adapter tests, fixture expectations, and release metadata for
  the 0.3.0 compatibility line.

## 0.2.1 - 2026-09-13 (Language detection fix)

- Count Chinese characters and Latin words separately when choosing the Review UI
  language, so technical identifiers and product names cannot outweigh Chinese prose.
- Added Pi, DeepSeek Harness, and Python regression coverage for mixed Chinese/English
  user messages.
- Made the Pi fixture long enough to cross Pi's native recent-token compaction boundary
  and localized its durable user-authored messages for a representative Chinese UI test.

## 0.2.0 - 2026-09-12 (Preview Audit)

- Added native-preview auditing with source-backed findings for missing, incorrect,
  stale, and ambiguous context.
- Replaced unbounded atomic adapter questions with topic-level `ReviewQuestion`
  prompts, hard-limited to three and configurable from zero to three.
- Added automatic correction, accepted-omission tracking, incremental revision
  guidance, bounded audit input construction, and language detection from user text.
- Updated Pi and DeepSeek Harness adapters to preview first and retry native
  compaction only when a correction or confirmed topic decision is needed.
- Kept successful native previews as the fail-open result when audit, UI, or retry
  fails; no host session transaction or final summarizer is replaced.
- Fixed semantic topics beginning with tool names (for example, `npm` fundamentals)
  being mistaken for raw command noise, and made the DSH fixture session easy to
  identify in the Web session list.

## 0.1.2 - 2026-09-12 (Pi adapter)

- Made the Pi Python bridge safe on Windows by preserving the runtime variables
  required by Python and using the Windows `python` launcher by default.
- Added structured bridge error categories, a longer configurable timeout, stricter
  JSONL protocol validation, and Windows CI coverage.

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
