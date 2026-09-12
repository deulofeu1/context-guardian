"""Model provider contracts and optional provider implementations."""

from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ModelProvider(Protocol):
    def generate_structured(self, prompt: str, schema: type[T]) -> T:
        """Return a validated instance of ``schema`` for ``prompt``."""


class ProviderError(RuntimeError):
    """Raised when a provider cannot return a valid structured response."""


class HostModelProvider:
    """Provider backed by a TypeScript host over stdin/stdout JSONL."""

    def __init__(self, *, input_stream=None, output_stream=None, max_frame_bytes: int = 2_000_000):
        self.input_stream = input_stream or sys.stdin
        self.output_stream = output_stream or sys.stdout
        self.max_frame_bytes = max_frame_bytes

    def generate_structured(self, prompt: str, schema: type[T]) -> T:
        request_id = str(uuid.uuid4())
        self._write(
            {
                "protocol_version": 1,
                "type": "provider_request",
                "request_id": request_id,
                "operation": "generate_structured",
                "prompt": prompt,
                "schema": schema.model_json_schema(),
            }
        )
        while True:
            line = self.input_stream.readline()
            if not line:
                raise ProviderError("host provider closed the protocol before responding")
            if len(line.encode("utf-8")) > self.max_frame_bytes:
                raise ProviderError("host provider response exceeded the frame limit")
            try:
                frame = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProviderError("host provider returned invalid JSON") from exc
            if frame.get("type") != "provider_response" or frame.get("request_id") != request_id:
                raise ProviderError("host provider response did not match the request")
            if not frame.get("ok"):
                raise ProviderError(str(frame.get("error") or "host provider failed"))
            try:
                return schema.model_validate(frame.get("data"))
            except Exception as exc:
                raise ProviderError("host provider returned data that does not match the schema") from exc

    def _write(self, frame: dict[str, Any]) -> None:
        payload = json.dumps(frame, ensure_ascii=False, separators=(",", ":"))
        if len(payload.encode("utf-8")) > self.max_frame_bytes:
            raise ProviderError("host provider request exceeded the frame limit")
        self.output_stream.write(payload + "\n")
        self.output_stream.flush()


class OpenAIProvider:
    """Optional standalone provider using the OpenAI Responses API.

    It is intentionally imported lazily so the base package remains usable without
    an OpenAI installation or API key.
    """

    def __init__(self, *, model: str | None = None, api_key: str | None = None):
        self.model = model or os.getenv("CONTEXT_GUARDIAN_OPENAI_MODEL", "gpt-4o-mini")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")

    def generate_structured(self, prompt: str, schema: type[T]) -> T:
        if not self.api_key:
            raise ProviderError("OPENAI_API_KEY is not configured")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderError("install context-guardian-core[openai] to use OpenAIProvider") from exc

        client = OpenAI(api_key=self.api_key)
        try:
            response = client.responses.parse(
                model=self.model,
                input=prompt,
                text_format=schema,
            )
            parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                raise ProviderError("OpenAI returned no parsed structured output")
            return schema.model_validate(parsed)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"OpenAI structured generation failed: {exc}") from exc


def provider_from_name(name: str | None) -> ModelProvider | None:
    if name in (None, "rules"):
        return None
    if name == "openai":
        return OpenAIProvider()
    if name == "host":
        return HostModelProvider()
    raise ValueError(f"unknown provider: {name}")
