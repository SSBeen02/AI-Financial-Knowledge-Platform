import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from game.models import Base, CharacterRow, CharacterStateRow, StoryProgressRow, StoryRewardRow
from game.store import SqlCharacterStore, SqlUnitOfWork


@pytest.fixture
def factory():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def connect(dbapi, _):
        dbapi.isolation_level = None
        dbapi.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def test_character_creation_is_idempotent_and_initializes_related_state(factory):
    uow = SqlUnitOfWork(factory)
    first = uow.run(lambda s: SqlCharacterStore(s).create("user-a", "학당"))
    again = uow.run(lambda s: SqlCharacterStore(s).create("user-a", "다른이름"))
    assert again.character_id == first.character_id
    assert again.character_name == "학당"
    with factory() as session:
        state = session.get(CharacterStateRow, first.character_id)
        progress = session.get(StoryProgressRow, (first.character_id, 1))
        assert (state.current_stage, state.current_rank, state.coin_balance) == (1, "꽃거지", 0)
        assert (progress.passed_concept_count, progress.total_concept_count) == (0, 30)
        assert session.get(StoryRewardRow, (first.character_id, 1, "flower")) is not None
        assert session.scalar(select(func.count()).select_from(CharacterRow)) == 1


def test_failed_transaction_rolls_back_character_and_initial_state(factory):
    def fail(session):
        SqlCharacterStore(session).create("user-b", "학당")
        raise RuntimeError("후속 저장 실패")

    with pytest.raises(RuntimeError):
        SqlUnitOfWork(factory).run(fail)
    with factory() as session:
        for model in [CharacterRow, CharacterStateRow, StoryProgressRow, StoryRewardRow]:
            assert session.scalar(select(func.count()).select_from(model)) == 0
