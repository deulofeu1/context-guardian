# Reviewed Facts appendix

Context Guardian 0.3.4 does not regenerate a host summary. Pi and DeepSeek Harness
call their native compactor once, keep the returned Preview uncommitted, and run the
audit and bounded human review against that Preview. The Core then produces a
versioned appendix using deterministic local code.

Only three sources can enter the appendix:

- source-backed `auto_corrections` from the audit plan;
- the key conclusion of a topic whose user answer is `Keep`;
- facts carried forward from an existing legal appendix.

Drop decisions, accepted omissions, UI explanations, evidence snippets, raw commands,
logs, paths, hashes, permissions, and full conversation history are not appended.
Facts are normalized, deduplicated, assigned stable IDs, and rendered between these
markers:

```text
<!-- context-guardian:reviewed-facts:v1 -->
## Context Guardian Reviewed Facts
The following reviewed facts should take priority for future work; this does not preserve the full original conversation.
- PostgreSQL is the selected database.
<!-- /context-guardian:reviewed-facts -->
```

The appendix is append-only. Native Preview text outside an existing legal appendix is
preserved byte-for-byte, and host result metadata is preserved by the adapters. A
legal existing appendix is merged and deduplicated; a malformed block is preserved and
a new legal block is appended. Applying the same appendix twice is idempotent.

The Python API is:

```python
from context_guardian import ContextGuardian

guardian = ContextGuardian()
plan = guardian.audit_preview(messages, preview=native_preview)
finalization = guardian.finalize_preview(
    preview=native_preview,
    review_plan=plan,
    answers=[{"question_id": "question-1", "action": "keep"}],
    messages=messages,
)
```

`finalization.original_preview` is the exact input, `finalization.final_summary` is
the append-only result, and `finalization.changed` indicates whether facts were added.
The deprecated `build_revision_guidance()` and bridge `revision_guidance` operation
remain only for compatibility with 0.2.x callers; maintained adapters do not invoke
them.
