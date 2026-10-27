import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from game.models import Base, CharacterRow, CharacterStateRow, StoryProgressRow, StoryRewardRow
from game.store import SqlCharacterStore, SqlUnitOfWork
from game.rules import StoryDefinition, StoryRules
from game.schemas import EventStatus, Rank
from game.service import GameService, RankVisual


@pytest.fixture
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

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


def test_transaction_retries_database_conflict_once_but_not_business_errors(factory):
    from sqlalchemy.exc import OperationalError
    engine = factory.kw["bind"]
    attempts = []

    class SerializationFailure(Exception):
        sqlstate = "40001"

    def conflict(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO game_characters"):
            attempts.append(statement)
            if len(attempts) == 1:
                raise OperationalError(statement, parameters, SerializationFailure())

    event.listen(engine, "before_cursor_execute", conflict)
    try:
        result = SqlUnitOfWork(factory).run(lambda session: SqlCharacterStore(session).create("retry-user", "학당"))
    finally:
        event.remove(engine, "before_cursor_execute", conflict)
    assert len(attempts) == 2 and result.user_id == "retry-user"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(CharacterRow)) == 1

    calls = []
    def invalid(session):
        calls.append(1)
        raise ValueError("구매 조건 오류")
    with pytest.raises(ValueError):
        SqlUnitOfWork(factory).run(invalid)
    assert len(calls) == 1


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


def standard_service(factory):
    from game.catalog import ACCESSORIES, STAGE_TOTALS, STORY_RULES, TITLES, VISUALS
    return GameService(SqlUnitOfWork(factory), STORY_RULES, VISUALS, STAGE_TOTALS, TITLES, ACCESSORIES)


def test_purchase_replay_title_and_promotion_preserve_owned_accessory(factory):
    service = standard_service(factory)
    character = service.create_character("user-a", "학당")
    for i in range(20):
        payload = learning_event(f"pass-{i}", i + 1)
        payload["concept_id"] = f"concept-{i}"
        service.process_event("user-a", payload)
    purchase = service.purchase_accessory("user-a", "shoes", "buy-1")
    assert purchase.status == "success" and purchase.coin_balance == 0
    assert service.purchase_accessory("user-a", "shoes", "buy-1") == purchase
    assert service.purchase_accessory("user-a", "shoes", "buy-2").status == "already_owned"
    assert service.equip_accessory("user-a", "shoes").equipped_accessory.accessory_id == "shoes"
    assert service.set_title("user-a", "title_10").active_title == "title_10"
    complete = learning_event("complete", 30)
    complete.update(event_type="stage_completed", first_pass=None, concept_id=None,
                    stage_completed=True, next_stage_id="stage2")
    service.process_event("user-a", complete)
    state = service.get_game_state("user-a")
    assert state.equipped_accessory is None
    assert state.owned_accessories[0].accessory_id == "shoes"
    with pytest.raises(ValueError):
        service.equip_accessory("user-a", "shoes")


def test_stage5_selection_crowns_and_king_shop_use_stage4_progress(factory):
    from game.schemas import Crown
    service = standard_service(factory)
    service.create_character("user-a", "학당")
    for stage, total in [(1, 30), (2, 40), (3, 50), (4, 60)]:
        complete = learning_event(f"complete-{stage}", total)
        complete.update(stage_id=f"stage{stage}", total_count=total, event_type="stage_completed",
                        first_pass=None, concept_id=None, stage_completed=True, next_stage_id=f"stage{stage + 1}")
        assert service.process_event("user-a", complete).status == EventStatus.PROCESSED
    state = service.get_game_state("user-a")
    assert state.current_stage == 4 and state.all_stages_completed and state.crown == Crown.BRONZE
    optional = learning_event("optional", 28)
    optional.update(stage_id="stage5", total_count=70)
    service.process_event("user-a", optional)
    state = service.get_game_state("user-a")
    assert state.current_stage == 5 and state.crown == Crown.SILVER and state.all_stages_completed
    belt = next(i for i in service.list_shop_items("user-a") if i.accessory.accessory_id == "dragon_belt")
    assert belt.unlocked
    optional.update(event_id="optional-complete", event_type="stage_completed", passed_count=70,
                    concept_id=None, first_pass=None, stage_completed=True)
    service.process_event("user-a", optional)
    assert service.get_game_state("user-a").crown == Crown.GOLD


def test_game_api_auth_ownership_and_purchase_key_validation(factory):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from game.router import router
    from server_auth import get_verified_user_id

    app = FastAPI()
    app.include_router(router)
    app.state.game_service = standard_service(factory)
    with TestClient(app) as client:
        assert client.get("/game/state").status_code == 401
        app.dependency_overrides[get_verified_user_id] = lambda: "user-a"
        assert client.post("/game/character", json={"name": "학당", "user_id": "victim"}).status_code == 422
        assert client.post("/game/character", json={"name": "학당"}).status_code == 200
        assert client.post("/game/title", json={"title_id": "title_1"}).json()["active_title"] == "title_1"
        assert client.post("/game/accessories/purchase", json={"accessory_id": "shoes"}).status_code == 422
        assert client.post("/game/sync").status_code == 503
        app.dependency_overrides[get_verified_user_id] = lambda: "user-b"
        assert client.get("/game/state").json() is None


def test_purchase_failure_rolls_back_debit_and_request_result(factory):
    from game.models import CoinTransactionRow, PurchaseRequestRow, UserAccessoryRow
    service = standard_service(factory)
    character = service.create_character("user-a", "학당")
    # 각 개념 최초 통과를 만들어 정상적인 200엽전 잔액을 준비한다.
    for i in range(20):
        payload = learning_event(f"setup-{i}", i + 1)
        payload["concept_id"] = f"concept-{i}"
        service.process_event("user-a", payload)

    def fail_grant(session, *_):
        if any(isinstance(row, UserAccessoryRow) for row in session.new):
            raise RuntimeError("아이템 지급 저장 실패")

    event.listen(factory.class_, "before_flush", fail_grant)
    try:
        with pytest.raises(RuntimeError):
            service.purchase_accessory("user-a", "shoes", "retry-buy")
    finally:
        event.remove(factory.class_, "before_flush", fail_grant)
    assert service.get_game_state("user-a").coin_balance == 200
    with factory() as session:
        assert session.get(PurchaseRequestRow, (character.character_id, "retry-buy")) is None
        assert session.scalar(select(func.count()).select_from(CoinTransactionRow).where(
            CoinTransactionRow.reason == "purchase")) == 0
    assert service.purchase_accessory("user-a", "shoes", "retry-buy").status == "success"


def test_event_failure_rolls_back_reward_and_retries_without_freezing_failure(factory):
    from game.models import CoinTransactionRow, EventLogRow, RewardHistoryRow
    service = standard_service(factory)
    service.create_character("user-a", "학당")

    def fail_reward(session, *_):
        if any(isinstance(row, RewardHistoryRow) for row in session.new):
            raise RuntimeError("보상 이력 저장 실패")

    event.listen(factory.class_, "before_flush", fail_reward)
    try:
        with pytest.raises(RuntimeError):
            service.process_event("user-a", learning_event())
    finally:
        event.remove(factory.class_, "before_flush", fail_reward)
    assert service.get_game_state("user-a").coin_balance == 0
    with factory() as session:
        assert session.get(EventLogRow, "event-1").status == "failed"
        assert session.scalar(select(func.count()).select_from(CoinTransactionRow)) == 0
    service.process_event("user-a", learning_event())
    state = service.get_game_state("user-a")
    assert state.coin_balance == 10 and len(state.reward_history) == 3
