import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from game.models import Base, CharacterRow, CharacterStateRow, StoryProgressRow, StoryRewardRow
from game.store import SqlCharacterStore, SqlUnitOfWork
from game.rules import StoryDefinition, StoryRules
from game.schemas import EventStatus, Rank
from game.service import GameService, RankVisual


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


def service_for(factory):
    return GameService(SqlUnitOfWork(factory), StoryRules([
        StoryDefinition(1, 2, "can", "can"), StoryDefinition(1, 3, "umbrella", "umbrella")]),
        {rank: RankVisual("outfit", "background") for rank in Rank},
        {1: 30, 2: 40, 3: 50, 4: 60, 5: 70})


def learning_event(event_id="event-1", passed=18):
    return dict(event_id=event_id, user_id="user-a", event_type="concept_passed",
                stage_id="stage1", concept_id="concept-1", first_pass=True,
                passed_count=passed, total_count=30, stage_completed=False,
                next_stage_id=None, occurred_at="2026-10-23T00:00:00Z")


def test_event_replay_and_late_concept_do_not_regress_or_double_pay(factory):
    service = service_for(factory)
    service.create_character("user-a", "학당")
    payload = learning_event()
    assert service.process_event("user-a", payload).status == EventStatus.PROCESSED
    service.process_event("user-a", payload)
    service.process_event("user-a", learning_event("duplicate-concept"))
    late = learning_event("late", passed=6)
    late["concept_id"] = "concept-2"
    service.process_event("user-a", late)
    state = service.get_game_state("user-a")
    assert (state.coin_balance, state.current_story_step, state.stage_progress) == (20, 3, 60)
    assert {r.story_reward_id for r in state.story_rewards} == {"flower", "can", "umbrella"}


def test_stage_completion_nullable_fields_and_old_stage_coin(factory):
    service = service_for(factory)
    service.create_character("user-a", "학당")
    complete = learning_event("complete", passed=30)
    complete.update(event_type="stage_completed", concept_id=None, first_pass=None,
                    stage_completed=True, next_stage_id="stage2")
    assert service.process_event("user-a", complete).status == EventStatus.PROCESSED
    assert service.get_game_state("user-a").current_stage == 2
    service.process_event("user-a", learning_event("late"))
    state = service.get_game_state("user-a")
    assert (state.coin_balance, state.current_stage, state.current_story_step) == (10, 2, 0)
    complete["event_id"] = "duplicate-complete"
    assert service.process_event("user-a", complete).status == EventStatus.REJECTED


def test_sync_retries_ack_without_reapplying_reward_and_isolates_user(factory):
    service = service_for(factory)
    service.create_character("user-a", "학당")

    class Source:
        attempts = 0
        done = False

        def get_unprocessed_events(self, *, user_id, limit):
            assert user_id == "user-a" and limit == 100
            return [] if self.done else [learning_event()]

        def mark_event_processed(self, event_id):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("완료 표시 실패")
            self.done = True

    source = Source()
    assert service.sync_events("user-a", source).retry_pending
    result = service.sync_events("user-a", source)
    assert not result.retry_pending and result.game_state.coin_balance == 10
    with pytest.raises(ValueError):
        service.process_event("user-b", learning_event())
