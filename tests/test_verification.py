import json
from pathlib import Path

from context_guardian.verification import verify_conversation, verify_file


def test_fixture_verification_passes():
    path = Path(__file__).parents[1] / "examples" / "conversation.json"
    result = verify_file(path)
    assert result["passed"] is True
    assert result["metrics"]["critical_memory_retention"] == 1.0
    assert result["metrics"]["noise_removal"] == 1.0
    assert result["metrics"]["checkpoint_memory_retention"] == 1.0
    assert result["checks"]["checkpoint_excludes_noise"] is True


def test_verification_accepts_message_arrays():
    path = Path(__file__).parents[1] / "examples" / "conversation.json"
    messages = json.loads(path.read_text(encoding="utf-8"))["messages"]
    assert verify_conversation(messages)["passed"] is True
