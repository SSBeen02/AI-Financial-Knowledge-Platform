"""Opt-in game-only PostgreSQL tests in a disposable, private schema.

Set GAME_TEST_ENV_FILE to a private dotenv path. Credentials are never printed.
No learning/quiz modules or public tables are used.
"""
import os
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, select, text, func
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.schema import CreateSchema, DropSchema

from game.models import (Base, CharacterRow, CoinTransactionRow, EventLogRow,
                         StageCompletionRow, StoryRewardRow, RewardHistoryRow,
                         UserAccessoryRow, PurchaseRequestRow)
from test_game_store import standard_service, learning_event
from test_game_plan import (
    completion, fund,
    test_ut01_names_save_and_failure_preserves_database,
    test_ut02_boundaries_and_invalid_event_entire_state,
    test_ut03_jump_rewards_and_regression,
    test_ut03_ignored_reason_is_auditable,
    test_ut04_promotions_rejections_crown_boundaries_completion_unique,
    test_ut05_coin_dedup_false_ack_stage5_and_ledger,
    test_ut06_shop_boundaries_rejection_state,
    test_ut06_literal_no_storage_change_on_rejection,
    test_ut07_purchase_ten_replays_and_full_rollback,
    test_ut08_equip_replace_clear_and_promotion,
    test_ut09_1_invalid_id_no_log_no_state_no_ack,
    test_ut09_2_valid_id_invalid_fields_reject_log_and_ack,
    test_ut10_replay_only_ack,
    test_ut10_mixed_source_order,
    test_ut11_missing_character_failure_recovery_ack,
    test_ut12_all_fields_match_storage_and_catalog,
    test_extra_titles_catalog_dialogue_rewards_and_performance,
    test_extra_event_log_write_failure_rolls_back_game_state,
)


@pytest.fixture(scope='module')
def isolated_engine():
    path=os.environ.get('GAME_TEST_ENV_FILE')
    if not path:
        pytest.skip('GAME_TEST_ENV_FILE is required for isolated PostgreSQL tests')
    cfg=dotenv_values(path)
    raw=next((cfg.get(k) for k in ('GAME_TEST_DATABASE_URL','DATABASE_URL','GAME_DATABASE_URL','CHAT_DB_URL') if cfg.get(k)),None)
    if not raw:
        pytest.fail('Private environment file has no database URL',pytrace=False)
    try:
        url=make_url(raw).set(drivername='postgresql+psycopg')
    except Exception:
        pytest.fail('Invalid database URL',pytrace=False)
    if not url.password or 'YOUR-PASSWORD' in url.password:
        pytest.fail('Database password is missing',pytrace=False)
    admin=create_engine(url,hide_parameters=True,pool_size=5,max_overflow=0,
                        connect_args={'sslmode':'require','connect_timeout':8,
                                      'options':'-c statement_timeout=15000 -c lock_timeout=5000'})
    schema='game_ut_'+uuid4().hex
    created=False
    try:
        with admin.begin() as conn:
            conn.execute(CreateSchema(schema)); created=True
            conn.exec_driver_sql(f'REVOKE ALL ON SCHEMA "{schema}" FROM PUBLIC')
        engine=admin.execution_options(schema_translate_map={None:schema})
        Base.metadata.create_all(engine)
        print('POSTGRES_PRIVATE_SCHEMA_CREATED',schema)
        yield engine,schema
    finally:
        if created:
            with admin.begin() as conn:
                conn.execute(DropSchema(schema,cascade=True))
            print('POSTGRES_PRIVATE_SCHEMA_REMOVED',schema)
        admin.dispose()


@pytest.fixture
def factory(isolated_engine):
    engine,schema=isolated_engine
    # Only explicitly named tables in the UUID-owned test schema are reset.
    tables=', '.join(f'"{schema}"."{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.exec_driver_sql(f'TRUNCATE TABLE {tables}')
    return sessionmaker(engine,expire_on_commit=False)


def test_pg_same_event_five_concurrent_requests(factory):
    s=standard_service(factory); s.create_character('user-a','학당')
    barrier=Barrier(5)
    def run(_):
        barrier.wait(timeout=10)
        return s.process_event('user-a',learning_event()).model_dump()
    with ThreadPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(run,range(5)))
    assert all(r==results[0] and r['status']=='processed' for r in results)
    assert s.get_game_state('user-a').coin_balance==10
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(EventLogRow))==1
        assert db.scalar(select(func.count()).select_from(CoinTransactionRow))==1


@pytest.mark.parametrize('same_key',[True,False])
def test_pg_concurrent_purchase_single_debit_and_grant(factory,same_key):
    s=standard_service(factory); s.create_character('user-a','학당'); fund(s)
    barrier=Barrier(5)
    def run(i):
        barrier.wait(timeout=10)
        return s.purchase_accessory('user-a','shoes','same' if same_key else f'key-{i}')
    with ThreadPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(run,range(5)))
    if same_key:
        assert all(r==results[0] and r.status=='success' for r in results)
    else:
        assert sorted(r.status for r in results)==['already_owned']*4+['success']
    assert s.get_game_state('user-a').coin_balance==0
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(UserAccessoryRow))==1
        assert db.scalar(select(func.count()).select_from(CoinTransactionRow).where(CoinTransactionRow.reason=='purchase'))==1


def test_pg_row_lock_blocks_second_connection_then_releases(factory):
    s=standard_service(factory); c=s.create_character('user-a','학당')
    def attempt():
        with factory.begin() as db:
            db.execute(text("SET LOCAL lock_timeout='500ms'"))
            db.scalar(select(CharacterRow).where(CharacterRow.character_id==c.character_id).with_for_update())
    with factory.begin() as owner:
        owner.scalar(select(CharacterRow).where(CharacterRow.character_id==c.character_id).with_for_update())
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(attempt)
            with pytest.raises(OperationalError) as exc:
                future.result(timeout=10)
            assert exc.value.orig.sqlstate=='55P03'
    attempt()


def test_pg_actual_unique_constraints(factory):
    s=standard_service(factory); s.create_character('user-a','학당'); fund(s)
    s.purchase_accessory('user-a','shoes','buy'); s.process_event('user-a',completion(1))
    for model in [CharacterRow,EventLogRow,CoinTransactionRow,StageCompletionRow,
                  StoryRewardRow,RewardHistoryRow,UserAccessoryRow,PurchaseRequestRow]:
        with factory() as db:
            row=db.scalars(select(model)).first()
            values={col.name:getattr(row,col.name) for col in model.__table__.columns}
        if model is CharacterRow: values['character_id']=str(uuid4())
        if model is CoinTransactionRow: values['tx_id']=str(uuid4())
        with pytest.raises(IntegrityError) as exc:
            with factory.begin() as db: db.add(model(**values))
        assert exc.value.orig.sqlstate=='23505',model.__name__
