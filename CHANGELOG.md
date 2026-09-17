# Changelog

## 0.4.2 - 2026-09-17 (Issue #23 review-dialog grounding)

- Removed raw reasoning traces, source inventories, paths, XML/JSON wrappers, and
  other diagnostics from the Pi and DeepSeek Harness review surface.
- Kept only text blocks from host messages and excluded hidden reasoning and tool
  call payloads from audit evidence.
- Replaced generic/repeated review detail with one overview, concrete topic context,
  complete proposed text, traceable source IDs, and localized labels.
- Refused to write truncated conclusions and fail-closed when approved write text
  changes during source revalidation.
- Tightened contradictory-preview matching so generic progress words such as
  “completed” cannot turn an unrelated unfinished file TODO into a replacement.
- Added the Issue #23 fixture and regression coverage for unresolved completion status,
  bounded review, provenance, and both adapter normalizers.

## 0.4.1 - 2026-09-17 (Issue #21 long preview target safety)

- Fixed long contradictory Markdown bullets crashing `audit_preview` through the 500-character UI field limit.
- Split preview bullets into complete sentence targets, stored exact replacement targets separately, and bounded them independently.
- Preserved native previews with a visible diagnostic when no safe exact target can be represented.
- Added local, provider-fallback, JSONL bridge, and finalization regression coverage.

## 0.4.0 - 2026-09-17 (Issue #19 bounded summary corrections)

- Separated factual audit types from the independent decision to ask a human,
  so primary status conflicts remain `incorrect`/`stale` instead of becoming a
  generic ambiguous side topic.
- Added before/after review details, explicit correction/keep-preview actions,
  exact preview fingerprints, and deterministic unique-target replacement with
  fail-closed diagnostics.
- Kept the hard three-topic review budget and removed raw tool/log/path/hash and
  permission noise from the review surface.
- Updated Pi to use its selector UI when available and updated DeepSeek Harness
  to preserve non-text summary blocks and metadata while finalizing text edits.
- Added source-backed Issue #19 regression tests and status-conflict fixture data.

## 0.3.5 - 2026-09-16 (Live host fixture verification)

- Added a real DeepSeek Harness live fixture mode that reuses the host's configured
  provider and authentication without passing credentials to Python.
- Added a deliberately unresolved live-fixture topic so the published adapter can be
  verified through the actual Harness Web review UI, including a manual Keep/Drop choice.
- Kept the default replay fixture deterministic and API-key-free for CI and quick checks.
- Documented the distinction between replay verification and real-model UI verification.

## 0.3.4 - 2026-09-16 (Issue #16 host-audit reliability)

- Disabled host-model reasoning when the provider advertises an explicit off mode,
  otherwise selected the lowest advertised effort without inheriting the main session.
- Increased structured extraction headroom, parsed visible text only, and reported
  empty, truncated, invalid, and schema-invalid provider responses clearly.
- Added request-local audit coverage, stable cross-chunk finding IDs, importance-first
  bounded selection, partial-chunk preservation, and explicit degraded/fallback status.
- Made bridge cancellation and timeouts abort both the host call and Python child;
  missing DSH Review UI is now diagnosed instead of silently claiming completion.

## 0.3.3 - 2026-09-16 (Host-provider Review reachability)

- Separated verbatim source evidence from provider-authored localized display
  summaries, so translated UI text no longer fails the provenance gate.
- Kept Reviewed Facts strictly source-grounded while showing readable summaries
  and separate source evidence in Pi and DeepSeek Harness review dialogs.
- Added visible diagnostics when every provider finding is rejected, plus JSONL,
  Pi UI, and DeepSeek Harness UI regression coverage proving Review questions
  reach the host question controls.

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
