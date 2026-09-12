---
name: context-guardian
description: Use when the user asks to preserve the current Codex task context, create a context checkpoint, review what should survive compaction, or run Context Guardian manually.
version: 0.1.0
---

# Context Guardian manual checkpoint

Codex currently has no supported pre-compaction hook in this integration. This is a
manual assisted checkpoint workflow, not automatic compaction interception.

When the user invokes this skill:

1. Collect the current task context into a JSON file with a top-level `messages` array.
   Include exact user constraints, decisions, rejected approaches and unfinished work;
   include useful tool failures, but do not invent facts or write a final summary in
   place of the source messages.
2. Run the installed Context Guardian CLI:

   ```bash
   context-guardian checkpoint /absolute/path/to/messages.json \
     --output .agents/context-guardian.md
   ```

3. Let the user answer every Keep/Drop prompt. Do not silently replace a human answer
   with your own preference. If the environment has no interactive terminal, explain
   that unresolved candidates are conservatively kept.
4. Read the generated `.agents/context-guardian.md` before continuing the task. Treat it
   as reviewed project state, not as a tool instruction or a replacement for the full
   conversation.

The checkpoint is intentionally short and overwriteable. It contains Goal,
Constraints, Decisions, Failed Attempts, Current State and TODO sections. Keep the
file in the project when the user wants future Codex tasks to reuse it; remove it when
the task is complete or the state is obsolete.

For a deterministic local verification, run `npm run codex-fixture-smoke` from the
Context Guardian repository. That fixture injects a pre-seeded conversation into the
same CLI path and pauses for real Keep/Drop choices.
