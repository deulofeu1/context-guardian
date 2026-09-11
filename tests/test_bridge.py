import io
import json

from context_guardian.bridge import run_protocol


def test_bridge_handles_rules_inspection():
    request = {
        "protocol_version": 1,
        "type": "request",
        "request_id": "request-1",
        "operation": "inspect",
        "provider": "rules",
        "messages": [{"role": "user", "content": "The goal is to keep the public API unchanged."}],
    }
    input_stream = io.StringIO(json.dumps(request) + "\n")
    output_stream = io.StringIO()
    assert run_protocol(input_stream, output_stream) == 0
    response = json.loads(output_stream.getvalue())
    assert response["ok"] is True
    assert response["request_id"] == "request-1"
    assert response["result"]["candidates"]


def test_bridge_rejects_unknown_operation():
    request = {"protocol_version": 1, "request_id": "request-2", "operation": "unknown"}
    input_stream = io.StringIO(json.dumps(request) + "\n")
    output_stream = io.StringIO()
    run_protocol(input_stream, output_stream)
    response = json.loads(output_stream.getvalue())
    assert response["ok"] is False
