"""통합 서버의 학습 서비스와 게임 저장소 연결. 운영 테이블은 자동 생성하지 않는다."""
import inspect as python_inspect
import os
from dataclasses import dataclass

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

from game.catalog import ACCESSORIES, STAGE_TOTALS, STORY_RULES, TITLES, VISUALS
from game.models import Base
from game.service import GameService
from game.store import SqlUnitOfWork


class LearningEventSource:
    def __init__(self, learning_service):
        if "user_id" not in python_inspect.signature(learning_service.get_unprocessed_events).parameters:
            raise RuntimeError("학습 모듈의 사용자별 이벤트 조회(user_id)를 먼저 반영하세요.")
        self.learning_service = learning_service

    def get_unprocessed_events(self, *, user_id: str, limit: int = 100):
        if not user_id:
            raise ValueError("이벤트 조회에는 사용자 ID가 필요합니다.")
        return self.learning_service.get_unprocessed_events(user_id=user_id, limit=limit)

    def mark_event_processed(self, event_id: str):
        return self.learning_service.mark_event_processed(event_id)


@dataclass
class GameRuntime:
    service: GameService
    event_source: LearningEventSource
    engine: Engine

    def close(self):
        self.engine.dispose()


def build_game_runtime(engine: Engine, learning_service) -> GameRuntime:
    source = LearningEventSource(learning_service)
    schema = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not schema.has_table(table.name):
            raise RuntimeError(f"게임 migration을 먼저 적용하세요: {table.name}")
        actual = {c["name"] for c in schema.get_columns(table.name)}
        if not set(table.columns.keys()) <= actual:
            raise RuntimeError(f"게임 migration 컬럼을 확인하세요: {table.name}")
    factory = sessionmaker(engine, expire_on_commit=False)
    service = GameService(SqlUnitOfWork(factory), STORY_RULES, VISUALS, STAGE_TOTALS, TITLES, ACCESSORIES)
    return GameRuntime(service, source, engine)


def prepare_game_runtime(learning_service) -> GameRuntime | None:
    enabled = os.getenv("GAME_ENABLED", "false").strip().lower()
    if enabled not in {"true", "false"}:
        raise RuntimeError("GAME_ENABLED는 true 또는 false여야 합니다.")
    if enabled == "false":
        return None
    value = os.getenv("GAME_DATABASE_URL", "").strip() or os.getenv("CHAT_DB_URL", "").strip()
    try:
        url = make_url(value)
    except Exception:
        raise RuntimeError("게임 PostgreSQL 연결 설정을 확인하세요.") from None
    if url.drivername != "postgresql+psycopg":
        raise RuntimeError("게임 DB는 postgresql+psycopg 연결이 필요합니다.")
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
    try:
        return build_game_runtime(engine, learning_service)
    except Exception:
        engine.dispose()
        raise
