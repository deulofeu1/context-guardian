"""JSONL command bridge used by the Pi adapter and testable independently."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from .inspector import ContextGuardian
from .models import MemoryCandidate
from .providers import HostModelProvider

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 2_000_000


def write_frame(stream: TextIO, frame: dict[str, Any]) -> None:
    payload = json.dumps(frame, ensure_ascii=False, separators=(",", ":"))
    if len(payload.encode("utf-8")) > MAX_FRAME_BYTES:
        raise ValueError("frame exceeds maximum size")
    stream.write(payload + "\n")
    stream.flush()


def read_frame(stream: TextIO) -> dict[str, Any]:
    line = stream.readline()
    if not line:
        raise EOFError("input closed")
    if len(line.encode("utf-8")) > MAX_FRAME_BYTES:
        raise ValueError("frame exceeds maximum size")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("frame must be a JSON object")
    return value


def handle_request(request: dict[str, Any], *, input_stream: TextIO, output_stream: TextIO) -> dict[str, Any]:
    if request.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("unsupported protocol version")
    operation = request.get("operation")
    if operation not in {"inspect", "guidance"}:
        raise ValueError("unsupported operation")

    provider_name = request.get("provider")
    provider = (
        HostModelProvider(input_stream=input_stream, output_stream=output_stream)
        if provider_name == "host"
        else None
    )
    guardian = ContextGuardian(provider=provider)

    if operation == "inspect":
        result = guardian.inspect_with_fallback(request.get("messages", []))
        return {"result": result.model_dump(mode="json")}

    candidates = [MemoryCandidate.model_validate(candidate) for candidate in request.get("candidates", [])]
    decisions = request.get("decisions", [])
    guidance = guardian.build_guidance(candidates, decisions)
    return {"result": guidance.model_dump(mode="json")}


def run_protocol(input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout) -> int:
    while True:
        try:
            request = read_frame(input_stream)
        except EOFError:
            return 0
        except Exception as exc:
            write_frame(
                output_stream, {"protocol_version": PROTOCOL_VERSION, "type": "error", "error": str(exc)}
            )
            continue

        request_id = request.get("request_id")
        try:
            response = handle_request(request, input_stream=input_stream, output_stream=output_stream)
            write_frame(
                output_stream,
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "type": "result",
                    "request_id": request_id,
                    "ok": True,
                    **response,
                },
            )
        except Exception as exc:
            print(f"context-guardian bridge error: {exc}", file=sys.stderr)
            write_frame(
                output_stream,
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "type": "result",
                    "request_id": request_id,
                    "ok": False,
                    "error": str(exc),
                },
            )
