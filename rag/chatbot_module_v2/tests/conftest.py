from __future__ import annotations

from pathlib import Path

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
from chatbot.integrations import ConceptStatusService, DevConceptStatusService
from chatbot.errors import install_learning_error_handlers
from chatbot.router import router
from chatbot.store import ChatStore, SqlChatStore

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
    "CONCEPT_STATUS_LABEL_NOT_STARTED",
    "CONCEPT_STATUS_LABEL_IN_PROGRESS",
    "CONCEPT_STATUS_LABEL_PASSED",
    "FREE_QUESTION_AUTO_START",
    "BAND_HIGH",
    "BAND_LOW",
    "DISPLAY_SOURCE_MIN_SCORE",
    "STAGES_JSON_PATH",
    "CHAT_DB_URL",
    "DEV_USE_LOCAL_STATUS",
    "DEV_SIMULATE_QUIZ_STATUS",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def make_settings(db_path: Path, *, simulate_quiz_status: bool) -> Settings:
    return Settings(
        _env_file=None,
        chat_db_url=f"sqlite:///{db_path.as_posix()}",
        stages_json_path=STAGES_PATH,
        dev_use_local_status=True,
        dev_simulate_quiz_status=simulate_quiz_status,
        llm_model="gpt-test",
    )


@pytest.fixture
def status_db(tmp_path: Path) -> Path:
    return tmp_path / "chat.db"


@pytest.fixture
def dev_status(status_db: Path) -> DevConceptStatusService:
    service = DevConceptStatusService(make_settings(status_db, simulate_quiz_status=False))
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
def client(dev_status: DevConceptStatusService, chat_store: SqlChatStore) -> TestClient:
    return make_client(dev_status, chat_store)
