"""SQLAlchemy 기반 캐릭터 저장. 외부 모듈의 테이블은 조회하지 않는다."""
from collections.abc import Callable
from typing import TypeVar
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from game.models import CharacterRow, CharacterStateRow, StoryProgressRow, StoryRewardRow, utcnow
from game.schemas import Character, CharacterNameIn


T = TypeVar("T")


class SqlUnitOfWork:
    def __init__(self, factory: sessionmaker):
        self.factory = factory

    def run(self, work: Callable[[Session], T]) -> T:
        # work는 DB 작업만 수행한다. 원본 이벤트 완료 표시 등 외부 효과는 커밋 뒤 처리한다.
        for attempt in range(2):
            try:
                with self.factory.begin() as session:
                    return work(session)
            except DBAPIError as exc:
                sqlstate = getattr(exc.orig, "sqlstate", None)
                if attempt or sqlstate not in {"40001", "40P01"}:
                    raise
                # 실패한 세션은 롤백·종료됐으므로 새 트랜잭션에서 한 번만 재시도한다.


def character_out(row: CharacterRow) -> Character:
    return Character(character_id=row.character_id, user_id=row.user_id,
                     character_name=row.character_name, created_at=row.created_at)


class SqlCharacterStore:
    def __init__(self, session: Session):
        self.session = session

    def get_by_user(self, user_id: str) -> Character | None:
        row = self.session.scalar(select(CharacterRow).where(CharacterRow.user_id == user_id))
        return character_out(row) if row else None

    def create(self, user_id: str, name: str) -> Character:
        name = CharacterNameIn(name=name).name
        existing = self.get_by_user(user_id)
        if existing:
            return existing
        try:
            with self.session.begin_nested():
                row = CharacterRow(character_id=str(uuid4()), user_id=user_id,
                                   character_name=name, created_at=utcnow())
                self.session.add(row)
                self.session.flush()
                self.session.add_all([
                    CharacterStateRow(character_id=row.character_id),
                    StoryProgressRow(character_id=row.character_id, stage=1,
                                     total_concept_count=30),
                    StoryRewardRow(character_id=row.character_id, stage=1,
                                   story_reward_id="flower"),
                ])
                self.session.flush()
                return character_out(row)
        except IntegrityError:
            # 다른 요청이 먼저 생성한 경우에만 그 캐릭터를 재사용한다.
            existing = self.get_by_user(user_id)
            if existing is None:
                raise
            return existing

    def lock(self, character_id: str) -> CharacterRow:
        row = self.session.scalar(select(CharacterRow).where(
            CharacterRow.character_id == character_id).with_for_update())
        if row is None:
            raise LookupError("캐릭터가 없습니다.")
        return row

    def update_name(self, character_id: str, name: str) -> Character:
        name = CharacterNameIn(name=name).name
        row = self.lock(character_id)
        row.character_name = name
        self.session.flush()
        return character_out(row)
