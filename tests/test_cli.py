import json
from pathlib import Path

from context_guardian.cli import main


def test_cli_json_output(capsys):
    example = Path(__file__).parents[1] / "examples" / "conversation.json"
    assert main(["inspect", str(example), "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["candidates"]
    assert output["mode"] == "rules"


def test_cli_verify_output(capsys):
    example = Path(__file__).parents[1] / "examples" / "conversation.json"
    assert main(["verify", str(example), "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["passed"] is True


def test_cli_checkpoint_writes_reviewed_markdown(tmp_path, monkeypatch, capsys):
    example = Path(__file__).parents[1] / "examples" / "conversation.json"
    output = tmp_path / ".agents" / "context-guardian.md"
    monkeypatch.setattr("builtins.input", lambda _: "y")

    assert main(["checkpoint", str(example), "--output", str(output)]) == 0

    text = output.read_text(encoding="utf-8")
    assert text.startswith("# Context Guardian Checkpoint")
    assert "## Goal" in text
    assert "PostgreSQL" in text
    assert "auth.py" in text
    assert "grep" not in text
    assert "checkpoint written" in capsys.readouterr().out
