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
