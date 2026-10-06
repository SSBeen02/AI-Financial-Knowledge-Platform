from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI

from chatbot.deps import get_quiz_service
from chatbot.quiz import QuizServiceError, QuizSetResult
from chatbot.schemas import (
    ErrorResponse,
    GameEventOut,
    LearningCompletionOut,
    LearningContextOut,
    MessageResponse,
    QuizResultReportIn,
    QuizRetryOut,
    StateResponse,
)


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict[str, object]:
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


def _shape(value):
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_shape(item) for item in value]
    return type(value).__name__


def test_learning_context_example_matches_public_schema() -> None:
    parsed = LearningContextOut.model_validate(_load("learning_context_example.json"))
    assert parsed.concept.concept_id == "sisa_1281"
    assert parsed.concept.stage_id == "stage1"
    assert parsed.reference_chunk_ids == ["sisa_1281"]


def test_report_quiz_result_example_matches_internal_contract_schema() -> None:
    parsed = QuizResultReportIn.model_validate(_load("report_quiz_result_example.json"))
    assert parsed.session_id == "session-example-1"
    assert parsed.correct_count == 2
    assert parsed.passed is True


@pytest.mark.parametrize(
    ("name", "schema"),
    [
        ("game_event_concept_passed.json", GameEventOut),
        ("game_event_stage_completed.json", GameEventOut),
        ("current_response.json", StateResponse),
        ("message_response.json", MessageResponse),
        ("complete_response.json", LearningCompletionOut),
        ("quiz_retry_response.json", QuizRetryOut),
        ("error_response.json", ErrorResponse),
    ],
)
def test_team_integration_json_examples_match_public_schemas(name: str, schema: type) -> None:
    payload = _load(name)
    parsed = schema.model_validate(payload)
    assert _shape(parsed.model_dump(mode="json")) == _shape(payload)


def test_legacy_learning_context_stage_is_read_but_serialized_as_stage_id() -> None:
    payload = _load("learning_context_example.json")
    concept = payload["concept"]
    assert isinstance(concept, dict)
    concept["stage"] = concept.pop("stage_id")
    dumped = LearningContextOut.model_validate(payload).model_dump(mode="json")
    assert dumped["concept"]["stage_id"] == "stage1"
    assert "stage" not in dumped["concept"]


def _load_quiz_service_example():
    path = ROOT / "examples" / "quiz_service_example.py"
    spec = importlib.util.spec_from_file_location("quiz_service_example", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quiz_service_example_is_idempotent_and_registers_override() -> None:
    module = _load_quiz_service_example()

    class Repository:
        def __init__(self) -> None:
            self.result = None

        def get_by_session_id(self, session_id: str):
            del session_id
            return self.result

        def create_quiz_set(self, **kwargs):
            del kwargs
            self.result = QuizSetResult(quiz_set_id="quiz-example", status="pending")
            return self.result

    repository = Repository()
    service = module.TeamQuizService(repository)
    kwargs = {
        "user_id": "user-1",
        "session_id": "session-1",
        "concept_id": "sisa_1281",
        "stage_id": "stage1",
        "learning_context": {},
        "reference_chunk_ids": ["sisa_1281"],
    }
    assert service.create_quiz_set(**kwargs) == service.create_quiz_set(**kwargs)
    app = FastAPI()
    module.register_quiz_service_override(app, lambda: service)
    assert app.dependency_overrides[get_quiz_service]() is service


def test_quiz_service_example_wraps_repository_failure() -> None:
    module = _load_quiz_service_example()

    class Repository:
        def get_by_session_id(self, session_id: str):
            del session_id
            return None

        def create_quiz_set(self, **kwargs):
            del kwargs
            raise TimeoutError

    service = module.TeamQuizService(Repository())
    with pytest.raises(QuizServiceError):
        service.create_quiz_set(
            user_id="user-1",
            session_id="session-1",
            concept_id="sisa_1281",
            stage_id="stage1",
            learning_context={},
            reference_chunk_ids=["sisa_1281"],
        )
