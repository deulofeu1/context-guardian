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

Native integrations pass `CompactionGuidance` into the host's native compactor.
Assisted integrations write `ContextCheckpoint` to a stable, human-readable file
because the host does not expose a reliable pre-compaction injection seam.

The capability matrix deliberately describes Claude Code's current limitation: its
`PreCompact` command hook can block a manual compaction, but guidance must be passed
on the next `/compact` invocation as custom instructions. Automatic compaction writes
the checkpoint and fails open.
