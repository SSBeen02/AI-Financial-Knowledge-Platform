"""배포 통합시험 Stage 완료의 상태, 이벤트, 접근 제한."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from chatbot.config import Settings
from chatbot.integrations import SqlConceptStatusService
from integration_test_stage import CompleteStageRequest, complete_current_stage


USER = "a4376f94-23b7-46a0-b078-27167ef904a2"
TOKEN = "integration-test-secret-with-at-least-32-characters"


@pytest.fixture
def stage_service(tmp_path, monkeypatch):
    catalog = Path(__file__).resolve().parents[1] / "rag/chatbot_module/data/stages.json"
    settings = Settings(
        _env_file=None, llm_provider="fake", llm_model="test",
        chat_db_url=f"sqlite:///{(tmp_path / 'learning.db').as_posix()}",
        stages_json_path=catalog, db_auto_create=True,
    )
    service = SqlConceptStatusService(settings)
    service.set_current_stage(USER, "stage3")
    monkeypatch.setenv("INTEGRATION_TEST_USER_ID", USER)
    monkeypatch.setenv("INTEGRATION_TEST_STAGE_TOKEN", TOKEN)
    yield service
    service.close()


def test_completes_current_stage_with_ordered_game_events(stage_service):
    result = complete_current_stage(
        CompleteStageRequest(expected_stage_id="stage3"), USER, TOKEN, stage_service
    )
    assert result.completed_stage_id == "stage3"
    assert result.next_stage_id == "stage4"
    assert result.test_completed_count == result.total_count == 50
    assert result.event_count == 51
    assert stage_service.get_current_stage(USER) == "stage4"
    events = stage_service.get_unprocessed_events(user_id=USER)
    assert len(events) == 51
    assert [event.passed_count for event in events[:-1]] == list(range(1, 51))
    assert events[-1].event_type == "stage_completed"
    assert events[-1].next_stage_id == "stage4"
    with pytest.raises(HTTPException) as repeat:
        complete_current_stage(
            CompleteStageRequest(expected_stage_id="stage3"), USER, TOKEN, stage_service
        )
    assert repeat.value.status_code == 409
    assert len(stage_service.get_unprocessed_events(user_id=USER)) == 51


def test_secret_account_and_configuration_are_required(stage_service, monkeypatch):
    body = CompleteStageRequest(expected_stage_id="stage3")
    for user, token in [(USER, None), (USER, "wrong"), ("other-user", TOKEN)]:
        with pytest.raises(HTTPException) as denied:
            complete_current_stage(body, user, token, stage_service)
        assert denied.value.status_code == 403
    monkeypatch.delenv("INTEGRATION_TEST_STAGE_TOKEN")
    with pytest.raises(HTTPException) as disabled:
        complete_current_stage(body, USER, TOKEN, stage_service)
    assert disabled.value.status_code == 404
    assert stage_service.get_current_stage(USER) == "stage3"
    assert stage_service.get_unprocessed_events(user_id=USER) == []


def test_active_learning_blocks_completion(stage_service):
    concept_id = next(iter(stage_service.get_statuses(USER, "stage3")))
    stage_service.mark_in_progress(USER, concept_id, "stage3")
    with pytest.raises(HTTPException) as blocked:
        complete_current_stage(
            CompleteStageRequest(expected_stage_id="stage3"), USER, TOKEN, stage_service
        )
    assert blocked.value.status_code == 409
    assert stage_service.get_current_stage(USER) == "stage3"


def test_stage5_terminal_completion(stage_service):
    stage_service.set_current_stage(USER, "stage5")
    result = complete_current_stage(
        CompleteStageRequest(expected_stage_id="stage5"), USER, TOKEN, stage_service
    )
    assert result.completed_stage_id == "stage5"
    assert result.next_stage_id is None
    assert result.test_completed_count == result.total_count == 70
    assert stage_service.get_current_stage(USER) == "stage5"
    events = stage_service.get_unprocessed_events(user_id=USER)
    assert len(events) == 71
    assert events[-1].event_type == "stage_completed"
    assert events[-1].next_stage_id is None
    with pytest.raises(HTTPException) as repeat:
        complete_current_stage(
            CompleteStageRequest(expected_stage_id="stage5"), USER, TOKEN, stage_service
        )
    assert repeat.value.status_code == 409
