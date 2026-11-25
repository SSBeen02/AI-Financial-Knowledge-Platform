"""통합 서버의 학습 서비스와 게임 저장소 연결. 운영 테이블은 자동 생성하지 않는다."""
import inspect as python_inspect
import os
from dataclasses import dataclass

from sqlalchemy import bindparam, create_engine, inspect, text
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
    if engine.dialect.name == "postgresql":
        validate_game_access(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    service = GameService(SqlUnitOfWork(factory), STORY_RULES, VISUALS, STAGE_TOTALS, TITLES, ACCESSORIES)
    return GameRuntime(service, source, engine)


def validate_game_access(engine: Engine) -> None:
    """RLS 누락이나 브라우저 직접 쓰기 허용 상태로 운영을 시작하지 않는다."""
    query = text("""
        select c.relname, c.relrowsecurity,
               has_table_privilege('anon', c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE') as anon_access,
               has_table_privilege('authenticated', c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE') as browser_write,
               has_table_privilege('authenticated', c.oid, 'SELECT') as user_read
        from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relname in :names
    """).bindparams(bindparam("names", expanding=True))
    with engine.connect() as connection:
        rows = connection.execute(query, {"names": list(Base.metadata.tables)}).mappings().all()
    if len(rows) != len(Base.metadata.tables):
        raise RuntimeError("public 게임 테이블 구성을 확인하세요.")
    for row in rows:
        if not row["relrowsecurity"] or row["anon_access"] or row["browser_write"] or not row["user_read"]:
            raise RuntimeError(f"게임 RLS·조회 전용 권한을 확인하세요: {row['relname']}")


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
    # Each module has its own engine; keep rollout overlap below the shared session limit.
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True,
                           pool_size=1, max_overflow=0, pool_timeout=15)
    try:
        return build_game_runtime(engine, learning_service)
    except Exception:
        engine.dispose()
        raise
