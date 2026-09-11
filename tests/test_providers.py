import io
import json

import pytest

from context_guardian.models import MemoryCandidate
from context_guardian.providers import HostModelProvider, OpenAIProvider, ProviderError


class ReplyStream:
    def __init__(self, output_stream):
        self.output_stream = output_stream

    def readline(self):
        request = json.loads(self.output_stream.getvalue().splitlines()[-1])
        return (
            json.dumps(
                {
                    "type": "provider_response",
                    "request_id": request["request_id"],
                    "ok": True,
                    "data": {
                        "id": "x",
                        "content": "durable fact",
                        "category": "important_fact",
                        "importance": 0.8,
                        "confidence": 0.8,
                        "suggested_action": "keep",
                    },
                }
            )
            + "\n"
        )


def test_host_provider_round_trip_validates_schema():
    output = io.StringIO()
    provider = HostModelProvider(input_stream=ReplyStream(output), output_stream=output)
    result = provider.generate_structured("extract", MemoryCandidate)
    assert result.content == "durable fact"


def test_host_provider_rejects_unmatched_response():
    provider = HostModelProvider(
        input_stream=io.StringIO(
            json.dumps({"type": "provider_response", "request_id": "wrong", "ok": True}) + "\n"
        ),
        output_stream=io.StringIO(),
    )
    try:
        provider.generate_structured("extract", MemoryCandidate)
    except ProviderError as exc:
        assert "did not match" in str(exc)
    else:
        raise AssertionError("expected ProviderError")


def test_openai_provider_requires_explicit_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        OpenAIProvider().generate_structured("extract", MemoryCandidate)
