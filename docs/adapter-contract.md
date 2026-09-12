# Adapter contract

Every Context Guardian host integration follows the same behavioral lifecycle:

```text
collect → native preview → audit → bounded review → native commit
```

The host-specific adapter owns only the lifecycle seam, message conversion, review
surface, and final injection or persistence. Candidate classification, scoring,
policy, stable IDs, and rendering remain in the Python Core.

The language-neutral contract is represented by
`context_guardian.adapters.ContextGuardianAdapter`:

```python
class ContextGuardianAdapter:
    collect_context() -> Sequence[ConversationMessage]
    inspect(messages) -> InspectionResult  # legacy/internal atomic API
    audit_preview(messages, preview) -> ReviewPlan
    preserve(review_plan, answers) -> CompactionGuidance | ContextCheckpoint
```

TypeScript adapters do not need to inherit the Python Protocol. They must preserve
the same lifecycle and declare their actual capabilities in
[`adapters/capabilities.json`](../adapters/capabilities.json).

## Preservation modes

The maintained Pi and DeepSeek Harness integrations first obtain a native Preview,
then pass only incremental `CompactionGuidance` into a native retry when audit or
user decisions require it. The Core also exposes
`ContextCheckpoint` for future assisted integrations whose host does not provide a
reliable pre-compaction injection seam. Review questions are topic-level and hard
limited to three by default (configurable from zero to three). A successful Preview
is preferred when audit or retry fails.

The capability matrix describes the integrations maintained in the current release.
