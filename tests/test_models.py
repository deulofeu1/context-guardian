import pytest
from pydantic import ValidationError

from context_guardian.models import MemoryCandidate, ReviewAction


def test_candidate_scores_are_bounded():
    with pytest.raises(ValidationError):
        MemoryCandidate(
            id="x",
            content="fact",
            category="important_fact",
            importance=1.1,
            confidence=0.5,
            suggested_action=ReviewAction.REVIEW,
        )


def test_message_content_blocks_are_normalized():
    from context_guardian.models import ConversationMessage

    message = ConversationMessage(
        role="assistant", content=[{"type": "text", "text": "one"}, {"type": "text", "text": "two"}]
    )
    assert message.content == "one\ntwo"
