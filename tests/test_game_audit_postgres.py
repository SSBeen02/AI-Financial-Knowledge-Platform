"""Run only the NFR-08 checks with the disposable PostgreSQL fixture."""
from test_game_postgres import isolated_engine, factory
from test_game_audit import (
    test_nfr08_records_before_after_for_coin_rank_and_accessory,
    test_nfr08_database_rejects_mutation,
    test_nfr08_audit_write_failure_rolls_back_change,
)


def test_nfr08_postgres_rejects_truncate(factory, isolated_engine):
    import pytest
    from sqlalchemy.exc import DBAPIError
    from test_game_store import standard_service, learning_event
    s=standard_service(factory); s.create_character('user-a','학당'); s.process_event('user-a',learning_event())
    engine,schema=isolated_engine
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.exec_driver_sql(f'TRUNCATE TABLE "{schema}".game_audit_logs')
