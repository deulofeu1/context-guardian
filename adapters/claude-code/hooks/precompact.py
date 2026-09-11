#!/usr/bin/env python3
"""Claude Code PreCompact hook for Context Guardian.

Claude Code gives PreCompact hooks the transcript path and allows them to block a
manual compaction, but does not expose an additionalContext channel for this event.
The hook therefore reviews and writes a checkpoint, then asks the user to rerun
manual /compact with that checkpoint as custom instructions.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from context_guardian import ContextGuardian, ConversationMessage, ReviewDecision


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def warn(message: str) -> None:
    print(f"context-guardian: {message}", file=sys.stderr)


def content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (content_text(item) for item in value))).strip()
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if "content" in value:
            return content_text(value["content"])
        if value.get("type") in {"tool_use", "tool-call"}:
            name = str(value.get("name") or "")
            arguments = value.get("input", value.get("arguments", ""))
            return f"Tool call {name}: {arguments}".strip()
    return ""


def normalize_record(record: dict[str, Any], index: int) -> ConversationMessage | None:
    message = record.get("message") if isinstance(record.get("message"), dict) else record
    record_type = str(record.get("type") or message.get("role") or "")
    role = str(message.get("role") or record_type)
    if record_type in {"tool_result", "tool-use", "tool_result_message"}:
        role = "tool"
    if role not in {"user", "assistant", "tool", "toolResult", "tool_result"}:
        return None
    content = content_text(message.get("content", record.get("content", ""))).strip()
    if not content:
        return None
    tool_name = message.get("name") or record.get("name")
    is_error = bool(
        message.get("is_error")
        or message.get("isError")
        or record.get("is_error")
        or record.get("isError")
    )
    identifier = str(
        record.get("uuid")
        or record.get("id")
        or message.get("uuid")
        or message.get("id")
        or f"claude_message_{index + 1:04d}"
    )
    return ConversationMessage(
        role="tool" if role in {"toolResult", "tool_result"} else role,
        content=content,
        id=identifier,
        tool_name=str(tool_name) if tool_name else None,
        is_error=is_error,
        metadata={"source": "claude-transcript", "record_type": record_type},
    )


def load_transcript(path: Path) -> list[ConversationMessage]:
    messages: list[ConversationMessage] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            message = normalize_record(value, index)
            if message is not None:
                messages.append(message)
    return messages


def checkpoint_path(cwd: Path) -> Path:
    configured = os.getenv("CONTEXT_GUARDIAN_CLAUDE_CHECKPOINT")
    path = Path(configured) if configured else Path(".claude/context-guardian.md")
    return path if path.is_absolute() else cwd / path


def state_path(cwd: Path) -> Path:
    configured = os.getenv("CONTEXT_GUARDIAN_CLAUDE_STATE")
    path = Path(configured) if configured else Path(".claude/context-guardian-state.json")
    return path if path.is_absolute() else cwd / path


def review_candidates(result) -> list[ReviewDecision]:
    mode = os.getenv("CONTEXT_GUARDIAN_REVIEW_MODE")
    if mode in {"keep", "drop"}:
        return [ReviewDecision(candidate_id=item.id, action=mode) for item in result.review]

    fixture_choices = os.getenv("CONTEXT_GUARDIAN_REVIEW_CHOICES")
    if fixture_choices is not None:
        choices = [item.strip().lower() for item in fixture_choices.split(",")]
        if len(choices) != len(result.review) or any(item not in {"keep", "drop"} for item in choices):
            raise ValueError("CONTEXT_GUARDIAN_REVIEW_CHOICES does not match review candidates")
        return [
            ReviewDecision(candidate_id=item.id, action=choices[index])
            for index, item in enumerate(result.review)
        ]

    try:
        tty = open("/dev/tty", "r+", encoding="utf-8", buffering=1)
    except OSError:
        warn("no interactive terminal; unresolved candidates will be kept")
        return [ReviewDecision(candidate_id=item.id, action="keep") for item in result.review]

    decisions: list[ReviewDecision] = []
    with tty:
        tty.write(
            f"\nContext Guardian: {len(result.auto_keep)} auto-keep, "
            f"{len(result.auto_drop)} auto-drop, {len(result.review)} for review.\n"
        )
        for item in result.review:
            tty.write(
                f"\n[{item.category.value}] importance={item.importance:.2f} "
                f"confidence={item.confidence:.2f}\n{item.content}\n"
                "Keep this memory? [Y/n] "
            )
            answer = tty.readline().strip().lower()
            action = "drop" if answer in {"n", "no", "d", "drop"} else "keep"
            decisions.append(ReviewDecision(candidate_id=item.id, action=action))
    return decisions


def ready_for_native_compaction(event: dict[str, Any], path: Path) -> bool:
    if os.getenv("CONTEXT_GUARDIAN_CLAUDE_ALLOW_NATIVE") == "1":
        return True
    if not path.is_file():
        return False
    instructions = str(event.get("custom_instructions") or "").casefold()
    return path.name.casefold() in instructions or str(path).casefold() in instructions


def main() -> int:
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict) or event.get("hook_event_name") != "PreCompact":
            emit({})
            return 0
        transcript = Path(str(event.get("transcript_path") or ""))
        cwd = Path(str(event.get("cwd") or Path.cwd()))
        output = checkpoint_path(cwd)
        if event.get("trigger") == "manual" and ready_for_native_compaction(event, output):
            emit({})
            return 0
        if not transcript.is_file():
            raise RuntimeError("Claude Code transcript path is unavailable")

        messages = load_transcript(transcript)
        if not messages:
            raise RuntimeError("Claude Code transcript contained no inspectable messages")
        guardian = ContextGuardian()
        inspection = guardian.inspect_with_fallback(messages)
        decisions = review_candidates(inspection)
        checkpoint = guardian.build_checkpoint(inspection.candidates, decisions)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(checkpoint.text + "\n", encoding="utf-8")
        state = {
            "session_id": event.get("session_id"),
            "transcript_digest": hashlib.sha256(transcript.read_bytes()).hexdigest(),
            "checkpoint": str(output),
        }
        state_file = state_path(cwd)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        if event.get("trigger") != "manual":
            warn(f"checkpoint written for automatic compaction: {output}")
            emit({})
            return 0
        emit(
            {
                "decision": "block",
                "reason": (
                    f"Context Guardian reviewed this session and wrote {output}. "
                    f"Re-run /compact with: Read {output} and preserve every reviewed item."
                ),
            }
        )
        return 0
    except KeyboardInterrupt:
        warn("review cancelled; continuing native compaction")
        emit({})
        return 0
    except Exception as exc:
        warn(f"unavailable; continuing native compaction ({exc})")
        emit({})
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
