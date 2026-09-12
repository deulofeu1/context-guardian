# Adapter contract

Every Context Guardian host integration follows the same behavioral lifecycle:

```text
collect → inspect → review → preserve
```

The host-specific adapter owns only the lifecycle seam, message conversion, review
surface, and final injection or persistence. Candidate classification, scoring,
policy, stable IDs, and rendering remain in the Python Core.

The language-neutral contract is represented by
`context_guardian.adapters.ContextGuardianAdapter`:

```python
class ContextGuardianAdapter:
    collect_context() -> Sequence[ConversationMessage]
    inspect(messages) -> InspectionResult
    review(candidates) -> Sequence[ReviewDecision]
    preserve(candidates, decisions) -> CompactionGuidance | ContextCheckpoint
```

TypeScript adapters do not need to inherit the Python Protocol. They must preserve
the same four behaviors and declare their actual capabilities in
[`adapters/capabilities.json`](../adapters/capabilities.json).

## Preservation modes

The maintained Pi and DeepSeek Harness integrations pass `CompactionGuidance`
directly into their native compaction path. The Core also exposes
`ContextCheckpoint` for future assisted integrations whose host does not provide a
reliable pre-compaction injection seam.

The capability matrix describes the integrations maintained in the current release.
