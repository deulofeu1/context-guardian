import json
from pathlib import Path

from context_guardian import AdapterCapabilities, IntegrationLevel


def test_capability_matrix_matches_public_adapter_contract():
    path = Path(__file__).parents[1] / "adapters" / "capabilities.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    integrations = payload["integrations"]
    assert {item["platform"] for item in integrations} == {"Pi", "Claude Code", "DeepSeek Harness", "Codex"}
    for item in integrations:
        capabilities = AdapterCapabilities(
            platform=item["platform"],
            level=IntegrationLevel(item["level"]),
            auto_trigger=item["auto_trigger"],
            host_model=item["host_model"],
            human_review=item["human_review"],
            native_compaction_injection=item["native_compaction_injection"],
        )
        assert capabilities.platform == item["platform"]


def test_codex_is_explicitly_assisted_and_claude_documents_persistence_boundary():
    path = Path(__file__).parents[1] / "adapters" / "capabilities.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_platform = {item["platform"]: item for item in payload["integrations"]}
    assert by_platform["Codex"]["level"] == "assisted"
    assert by_platform["Codex"]["auto_trigger"] is False
    assert "checkpoint" in by_platform["Claude Code"]["native_compaction_injection"]
