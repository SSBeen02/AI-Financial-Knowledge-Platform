from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chatbot.concepts import load_stage_catalog
from chatbot.config import Settings
from chatbot.deps import (
    get_cached_settings,
    get_chat_store,
    get_concept_status_service,
    get_stage_catalog,
)
from chatbot.integrations import ConceptStatusService, SqlConceptStatusService
from chatbot.learning_management import UserConceptProgressRow
from sqlalchemy.orm import Session
from chatbot.errors import install_learning_error_handlers
from chatbot.router import router
from chatbot.store import ChatStore, SqlChatStore

# pytest가 테스트 모듈을 수집하는 동안 main_dev 같은 모듈이 Settings를 만들더라도
# 개발자의 .env나 OS LLM 설정을 읽지 않게 한다. 실제 연결 테스트는 _env_file을
# 명시해 별도로 실환경 설정을 불러온다.
Settings.model_config["env_file"] = None
os.environ["LLM_MODEL"] = "gpt-test"

ROOT = Path(__file__).resolve().parents[1]
STAGES_PATH = ROOT / "data" / "stages.json"

ENV_KEYS = (
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "QDRANT_COLLECTION",
    "DENSE_MODEL",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_RELEVANCE_MODEL",
    "LLM_REASONING_EFFORT",
    "LLM_MAX_OUTPUT_TOKENS",
    "LLM_TEMPERATURE",
    "CHAT_TONE",
    "ANSWER_KNOWLEDGE_MODE",
    "FREE_QUESTION_AUTO_START",
    "CORS_ALLOW_ORIGINS",
    "BAND_HIGH",
    "BAND_LOW",
    "DISPLAY_SOURCE_MIN_SCORE",
    "STAGES_JSON_PATH",
    "CHAT_DB_URL",
    "DB_AUTO_CREATE",
    "DEV_ENABLE_TOOLS",
    "DEV_SIMULATE_QUIZ_GENERATION_FAILURE",
    "DEV_USE_LOCAL_STATUS",
)


@pytest.fixture(autouse=True)
def isolate_unit_test_environment(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """단위 테스트를 실제 .env와 OS 환경변수로부터 완전히 격리한다.

    integration 표시가 있는 테스트만 실제 연결 설정을 읽는다.
    """
    if request.node.get_closest_marker("integration") is not None:
        monkeypatch.delenv("SSLKEYLOGFILE", raising=False)
        return
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture
def clean_env() -> None:
    """기존 테스트의 명시적 의존성을 유지하는 호환 fixture."""


def make_settings(db_path: Path, *, simulate_quiz_status: bool) -> Settings:
    return Settings(
        _env_file=None,
        chat_db_url=f"sqlite:///{db_path.as_posix()}",
        stages_json_path=STAGES_PATH,
        db_auto_create=True,
        dev_enable_tools=True,
        llm_model="gpt-test",
    )


@pytest.fixture
def status_db(tmp_path: Path) -> Path:
    return tmp_path / "chat.db"


@pytest.fixture
def dev_status(status_db: Path) -> SqlConceptStatusService:
    service = SqlConceptStatusService(make_settings(status_db, simulate_quiz_status=False))
    yield service
    service.close()


@pytest.fixture
def chat_store(status_db: Path) -> SqlChatStore:
    store = SqlChatStore(make_settings(status_db, simulate_quiz_status=False))
    yield store
    store.close()


def make_client(service: ConceptStatusService, store: ChatStore) -> TestClient:
    app = FastAPI()
    install_learning_error_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_concept_status_service] = lambda: service
    app.dependency_overrides[get_stage_catalog] = lambda: load_stage_catalog(STAGES_PATH)
    app.dependency_overrides[get_chat_store] = lambda: store
    app.dependency_overrides[get_cached_settings] = lambda: Settings(
        _env_file=None, llm_model="gpt-test"
    )
    return TestClient(app)


@pytest.fixture
def client(dev_status: SqlConceptStatusService, chat_store: SqlChatStore) -> TestClient:
    return make_client(dev_status, chat_store)


def force_concept_status(
    service: SqlConceptStatusService,
    user_id: str,
    concept_id: str,
    stage_id: str,
    status: str,
) -> None:
    """API 전제조건을 만드는 테스트 전용 DB 도우미."""
    now = datetime.now(timezone.utc)
    with Session(service._engine) as session:
        row = session.get(UserConceptProgressRow, (user_id, concept_id, stage_id))
        if row is None:
            row = UserConceptProgressRow(
                user_id=user_id,
                concept_id=concept_id,
                stage_id=stage_id,
                status=status,
                started_at=now,
                first_passed_at=now if status == "passed" else None,
                updated_at=now,
            )
            session.add(row)
        else:
            row.status = status
            row.first_passed_at = row.first_passed_at or (
                now if status == "passed" else None
            )
            row.updated_at = now
        session.commit()
