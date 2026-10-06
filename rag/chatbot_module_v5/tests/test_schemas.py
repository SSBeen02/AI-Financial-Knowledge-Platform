from __future__ import annotations

import pytest
from pydantic import ValidationError

from chatbot.schemas import MessageIn, MessageResponse, QuizResultIn, SourceOut


def test_source_omits_images_when_absent() -> None:
    dumped = SourceOut(
        concept_id="sisa_1281",
        term="분업/특화",
        score=0.71,
        collection="sisa_terms",
        label="시사경제용어사전",
    ).model_dump()
    assert "images" not in dumped


def test_source_keeps_images_when_present() -> None:
    dumped = SourceOut(
        concept_id="sisa_1281",
        term="분업/특화",
        score=0.71,
        collection="sisa_terms",
        label="시사경제용어사전",
        images=["https://example.com/a.png"],
    ).model_dump()
    assert dumped["images"] == ["https://example.com/a.png"]


def test_nested_source_omits_absent_images() -> None:
    dumped = MessageResponse(
        answer="설명",
        session_id=None,
        session_started=False,
        concept=None,
        is_related=False,
        band="low",
        top_score=0.2,
        sources=[
            SourceOut(
                concept_id="sisa_1",
                term="용어",
                score=0.2,
                collection="sisa_terms",
                label="시사경제용어사전",
            )
        ],
        display_sources=[],
        message_id="m1",
    ).model_dump()
    assert "images" not in dumped["sources"][0]


def test_message_rejects_user_id_and_blank_text() -> None:
    with pytest.raises(ValidationError):
        MessageIn.model_validate({"message": "알려줘", "user_id": "u1"})
    with pytest.raises(ValidationError):
        MessageIn(message="   ")
    parsed = MessageIn(message="  알려줘  ", concept_id="  ")
    assert parsed.message == "알려줘"
    assert parsed.concept_id is None


def test_message_rejects_removed_stage_field() -> None:
    with pytest.raises(ValidationError):
        MessageIn.model_validate(
            {"message": "알려줘", "concept_id": "sisa_1", "stage": "stage5"}
        )


def test_quiz_result_uses_confirmed_quiz_contract() -> None:
    payload = {
        "submission_id": "submission-1",
        "concept_id": "sisa_1281",
        "stage_id": "stage1",
        "correct_count": 2,
        "passed": True,
    }
    assert QuizResultIn.model_validate(payload).passed is True
    with pytest.raises(ValidationError):
        QuizResultIn.model_validate({**payload, "session_id": "not-in-body"})
