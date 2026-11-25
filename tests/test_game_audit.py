"""NFR-08: audit changes, immutability and transactional failure."""
import pytest
from sqlalchemy import event, select, update, delete
from sqlalchemy.exc import DBAPIError
from game.models import AuditLogRow
from test_game_store import factory, standard_service, learning_event
from test_game_plan import completion, fund, snapshot


def test_nfr08_records_before_after_for_coin_rank_and_accessory(factory):
    s=standard_service(factory); s.create_character('user-a','학당')
    fund(s)
    s.purchase_accessory('user-a','shoes','purchase-1')
    s.equip_accessory('user-a','shoes')
    s.process_event('user-a',completion(1))
    with factory() as db:
        rows=db.scalars(select(AuditLogRow)).all()
        def matching(kind,source):
            return next(r for r in rows if r.change_type==kind and r.source_id==source)
        for row in rows:
            assert row.user_id=='user-a' and row.character_id and row.created_at and row.source_type and row.source_id
        coin=matching('coin','fund-0')
        assert (coin.before_value,coin.after_value)==({'balance':0},{'balance':10})
        coin=matching('coin','purchase-1')
        assert (coin.before_value,coin.after_value)==({'balance':200},{'balance':0})
        item=matching('accessory_owned','purchase-1')
        assert not item.before_value['owned'] and item.after_value['owned']
        equip=next(r for r in rows if r.change_type=='accessory_equipped' and r.source_type=='user_action')
        assert equip.before_value['accessory_id'] is None and equip.after_value['accessory_id']=='shoes'
        rank=matching('rank','complete-1')
        assert (rank.before_value,rank.after_value)==({'rank':'꽃거지'},{'rank':'평민'})
        unequip=matching('accessory_equipped','complete-1')
        assert unequip.before_value['accessory_id']=='shoes' and unequip.after_value['accessory_id'] is None
        story=matching('story_reward','fund-11')
        assert story.before_value['owned'] is False and story.after_value['owned'] is True
    s.process_event('user-a',completion(2)); s.process_event('user-a',completion(3))
    with factory() as db:
        crown=db.scalar(select(AuditLogRow).where(AuditLogRow.change_type=='crown'))
        assert crown.before_value['crown'] is None and crown.after_value['crown']=='동왕관'


@pytest.mark.parametrize('operation',['update','delete'])
def test_nfr08_database_rejects_mutation(factory,operation):
    s=standard_service(factory); s.create_character('user-a','학당'); s.process_event('user-a',learning_event())
    with factory() as db:
        before={r.audit_id:r.change_type for r in db.scalars(select(AuditLogRow))}
    with pytest.raises(DBAPIError):
        with factory.begin() as db:
            statement=update(AuditLogRow).values(change_type='tampered') if operation=='update' else delete(AuditLogRow)
            db.execute(statement)
    with factory() as db:
        assert {r.audit_id:r.change_type for r in db.scalars(select(AuditLogRow))}==before


def test_nfr08_audit_write_failure_rolls_back_change(factory):
    s=standard_service(factory); s.create_character('user-a','학당')
    before=snapshot(factory,('game_event_logs',))
    def fail(session,*_):
        if any(isinstance(row,AuditLogRow) for row in session.new): raise RuntimeError('audit storage failure')
    event.listen(factory.class_,'before_flush',fail)
    try:
        with pytest.raises(RuntimeError): s.process_event('user-a',learning_event())
    finally: event.remove(factory.class_,'before_flush',fail)
    assert snapshot(factory,('game_event_logs',))==before
