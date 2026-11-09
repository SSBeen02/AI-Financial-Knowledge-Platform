"""GM-UT plan checks. Isolated SQLite only; no learning/quiz integration.

These executable assertions deliberately expose unmet plan conditions.
SQLite success does not establish PostgreSQL locking or concurrency.
"""
import time
import math
import pytest
from sqlalchemy import event, select, func

from test_game_store import factory, standard_service, learning_event
from game.models import (Base, CharacterRow, CharacterStateRow, StoryProgressRow,
                         StoryRewardRow, EventLogRow, CoinTransactionRow,
                         StageCompletionRow, RewardHistoryRow, UserAccessoryRow,
                         EquippedAccessoryRow, PurchaseRequestRow)
from game.schemas import EventStatus, Rank, Crown, Accessory, GameStateOut
from game.catalog import STAGE_TOTALS, VISUALS, TITLES, STORY_RULES


class Source:
    """Fake source records acknowledgements; never contacts another module."""
    def __init__(self, events):
        self.events, self.acks = events, []

    def get_unprocessed_events(self, *, user_id, limit):
        return [e for e in self.events if e.get('event_id') not in self.acks][:limit]

    def mark_event_processed(self, event_id):
        self.acks.append(event_id)


def snapshot(factory, exclude=()):
    with factory() as s:
        return {t.name: sorted([tuple(row) for row in s.execute(select(t))], key=repr)
                for t in Base.metadata.sorted_tables if t.name not in exclude}


def completion(stage, eid=None):
    p = learning_event(eid or f'complete-{stage}', STAGE_TOTALS[stage])
    p.update(stage_id=f'stage{stage}', total_count=STAGE_TOTALS[stage],
             event_type='stage_completed', concept_id=None, first_pass=None,
             stage_completed=True, next_stage_id=f'stage{stage+1}' if stage < 5 else None)
    return p


def fund(service, count=20):
    for i in range(count):
        p = learning_event(f'fund-{i}', i+1)
        p['concept_id'] = f'fund-{i}'
        service.process_event('user-a', p)


def test_ut01_names_save_and_failure_preserves_database(factory):
    s = standard_service(factory)
    for i, name in enumerate(['가', 'A', '가나다라마바사아자차', 'abcdefghij', '학당ABC']):
        c = s.create_character(f'name-{i}', name)
        assert c.character_name == name
        assert s.set_character_name(f'name-{i}', '변경Name').character_name == '변경Name'
    for name in ['', '가'*11, ' ', '학 당', '학당1', '!', '😀', '학당\n']:
        before = snapshot(factory)
        with pytest.raises(ValueError):
            s.create_character('invalid', name)
        with pytest.raises(ValueError):
            s.set_character_name('name-0', name)
        assert snapshot(factory) == before
    before = snapshot(factory)
    def fail(session, *_):
        if any(isinstance(r, CharacterRow) for r in session.dirty):
            raise RuntimeError('injected name save error')
    event.listen(factory.class_, 'before_flush', fail)
    try:
        with pytest.raises(RuntimeError):
            s.set_character_name('name-0', '실패')
    finally:
        event.remove(factory.class_, 'before_flush', fail)
    assert snapshot(factory) == before


def test_ut02_boundaries_and_invalid_event_entire_state(factory):
    for passed, total, step, percent in [(5,30,0,16),(6,30,1,20),(12,30,2,40),
            (29,30,4,96),(30,30,5,100),(8,40,1,20),(10,50,1,20),(12,60,1,20),(14,70,1,20)]:
        assert STORY_RULES.resolve_step(passed,total) == step
        assert STORY_RULES.progress_percent(passed,total) == percent
    s = standard_service(factory)
    s.create_character('user-a','학당')
    before = snapshot(factory, ('game_event_logs',))
    assert s.process_event('user-a',learning_event('overflow',31)).status == EventStatus.REJECTED
    assert snapshot(factory, ('game_event_logs',)) == before


def test_ut03_jump_rewards_and_regression(factory):
    s = standard_service(factory)
    c = s.create_character('user-a','학당')
    for eid, count in [('six',6),('eighteen',18),('twelve',12)]:
        s.process_event('user-a',learning_event(eid,count))
    state = s.get_game_state('user-a')
    assert (state.passed_concept_count,state.current_story_step,state.stage_progress) == (18,3,60)
    with factory() as db:
        rows = db.scalars(select(StoryRewardRow)).all()
        assert sorted(r.story_reward_id for r in rows) == ['can','flower','umbrella']
        assert len(db.scalars(select(RewardHistoryRow).where(RewardHistoryRow.reward_type=='story')).all()) == 2
        assert db.get(EventLogRow,'twelve').status == 'processed'


def test_ut03_ignored_reason_is_auditable(factory):
    s=standard_service(factory); s.create_character('user-a','학당')
    s.process_event('user-a',learning_event('high',18))
    s.process_event('user-a',learning_event('late',12))
    with factory() as db:
        log=db.get(EventLogRow,'late')
        assert (log.result or {}).get('message'), 'No ignored/regression reason in Event_Log'


def test_ut04_promotions_rejections_crown_boundaries_completion_unique(factory):
    s=standard_service(factory); s.create_character('user-a','학당')
    for payload in [completion(3,'early3'), dict(learning_event('early5',27),stage_id='stage5',total_count=70)]:
        before=snapshot(factory,('game_event_logs',))
        assert s.process_event('user-a',payload).status == EventStatus.REJECTED
        assert snapshot(factory,('game_event_logs',)) == before
    for stage,rank in [(1,Rank.COMMONER),(2,Rank.SCHOLAR),(3,Rank.KING),(4,Rank.KING)]:
        payload=completion(stage)
        first=s.process_event('user-a',payload)
        assert first.status == EventStatus.PROCESSED
        assert s.process_event('user-a',payload)==first
        for n in range(3):
            assert s.process_event('user-a',completion(stage,f'dup-{stage}-{n}')).status == EventStatus.REJECTED
        state=s.get_game_state('user-a')
        assert state.current_rank==rank
        assert (state.default_outfit,state.active_background)==(VISUALS[rank].outfit,VISUALS[rank].background)
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(StageCompletionRow).where(StageCompletionRow.stage==stage))==1
    assert state.current_stage==4 and state.all_stages_completed and state.pending_transition is not None
    for count,crown in [(27,Crown.BRONZE),(28,Crown.SILVER),(70,Crown.SILVER)]:
        p=dict(learning_event(f'optional-{count}',count),stage_id='stage5',total_count=70,concept_id=f'c-{count}')
        s.process_event('user-a',p)
        assert s.get_game_state('user-a').crown==crown
    s.process_event('user-a',completion(5))
    assert s.get_game_state('user-a').crown==Crown.GOLD


def test_ut05_coin_dedup_false_ack_stage5_and_ledger(factory):
    s=standard_service(factory); s.create_character('user-a','학당')
    for i in range(5): s.process_event('user-a',learning_event(f'dup-{i}',1))
    assert s.get_game_state('user-a').coin_balance==10
    s.process_event('user-a',dict(learning_event('new',2),concept_id='new'))
    assert s.get_game_state('user-a').coin_balance==20
    before=snapshot(factory,('game_event_logs',))
    source=Source([dict(learning_event('not-first',30),first_pass=False)])
    s.sync_events('user-a',source)
    assert source.acks==['not-first']
    assert snapshot(factory,('game_event_logs',))==before
    for stage in range(1,5): s.process_event('user-a',completion(stage))
    initial=s.get_game_state('user-a').coin_balance
    for i in range(1,71):
        s.process_event('user-a',dict(learning_event(f's5-{i}',i),concept_id=f's5-{i}',stage_id='stage5',total_count=70))
    assert s.get_game_state('user-a').coin_balance-initial==700
    s.process_event('user-a',completion(5))
    balance=s.get_game_state('user-a').coin_balance
    with factory() as db:
        assert db.scalar(select(func.sum(CoinTransactionRow.amount)))==balance
        assert db.scalar(select(func.count()).select_from(CoinTransactionRow).where(CoinTransactionRow.source_event_id.like('complete-%')))==0


def test_ut06_shop_boundaries_rejection_state(factory):
    s=standard_service(factory); s.create_character('user-a','학당'); fund(s,19)
    assert not next(i for i in s.list_shop_items('user-a') if i.accessory.accessory_id=='shoes').unlocked
    p=dict(learning_event('twenty',20),concept_id='twenty'); s.process_event('user-a',p)
    item=next(i for i in s.list_shop_items('user-a') if i.accessory.accessory_id=='shoes')
    assert item.unlocked and item.can_purchase and item.accessory.price==200
    before=snapshot(factory,('game_purchase_requests',))
    assert s.purchase_accessory('user-a','rice_paddle','wrong-rank').status=='unavailable'
    assert snapshot(factory,('game_purchase_requests',))==before
    # Independent low-balance state: one genuine first pass carrying aggregate 20.
    s.create_character('poor','학당')
    s.process_event('poor',dict(learning_event('poor-progress',20),user_id='poor'))
    before=snapshot(factory,('game_purchase_requests',))
    assert s.purchase_accessory('poor','shoes','poor-buy').status=='insufficient_balance'
    assert snapshot(factory,('game_purchase_requests',))==before


def test_ut06_literal_no_storage_change_on_rejection(factory):
    s=standard_service(factory); s.create_character('user-a','학당')
    before=snapshot(factory,('game_purchase_requests',))
    assert s.purchase_accessory('user-a','rice_paddle','rejected-key').status=='unavailable'
    assert snapshot(factory,('game_purchase_requests',))==before
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchaseRequestRow))==1


def test_rejected_purchase_key_replays_first_result_after_conditions_change(factory):
    s=standard_service(factory); s.create_character('user-a','학당')
    first=s.purchase_accessory('user-a','shoes','retry')
    assert first.status=='unavailable'
    fund(s)
    before=snapshot(factory)
    assert s.purchase_accessory('user-a','shoes','retry')==first
    assert snapshot(factory)==before
    assert s.purchase_accessory('user-a','shoes','new-key').status=='success'


def test_ut07_purchase_ten_replays_and_full_rollback(factory):
    s=standard_service(factory); s.create_character('user-a','학당'); fund(s)
    before=snapshot(factory)
    def fail(session,*_):
        if any(isinstance(r,UserAccessoryRow) for r in session.new): raise RuntimeError('grant error')
    event.listen(factory.class_,'before_flush',fail)
    try:
        with pytest.raises(RuntimeError): s.purchase_accessory('user-a','shoes','buy')
    finally: event.remove(factory.class_,'before_flush',fail)
    assert snapshot(factory)==before
    results=[s.purchase_accessory('user-a','shoes','buy') for _ in range(10)]
    assert all(r==results[0] and r.status=='success' for r in results)
    with factory() as db:
        for model in [UserAccessoryRow,PurchaseRequestRow]:
            assert db.scalar(select(func.count()).select_from(model))==1
        assert db.scalar(select(func.count()).select_from(CoinTransactionRow).where(CoinTransactionRow.reason=='purchase'))==1


def test_ut08_equip_replace_clear_and_promotion(factory):
    s=standard_service(factory); c=s.create_character('user-a','학당')
    for item in ['shoes','rice_paddle']:
        before=snapshot(factory)
        with pytest.raises(ValueError): s.equip_accessory('user-a',item)
        assert snapshot(factory)==before
    fund(s); s.purchase_accessory('user-a','shoes','buy')
    # Catalog has one accessory per rank. Synthetic second same-rank item exercises replacement.
    s.accessories['test-shoes']=Accessory(accessory_id='test-shoes',name='시험',rank=Rank.BEGGAR,unlock_pass_count=0,price=0)
    s.purchase_accessory('user-a','test-shoes','test-buy')
    for item in ['shoes','test-shoes',None,'shoes']:
        state=s.equip_accessory('user-a',item)
        assert (state.equipped_accessory.accessory_id if state.equipped_accessory else None)==item
        with factory() as db: assert db.scalar(select(func.count()).select_from(EquippedAccessoryRow))<=1
    s.process_event('user-a',completion(1))
    state=s.get_game_state('user-a')
    assert state.equipped_accessory is None and len(state.owned_accessories)==2
    with pytest.raises(ValueError): s.equip_accessory('user-a','shoes')


@pytest.mark.parametrize('invalid',['MISSING','',None,123,[],{},'x'*101,'   ',' bad '])
def test_ut09_1_invalid_id_no_log_no_state_no_ack(factory,invalid):
    s=standard_service(factory); s.create_character('user-a','학당')
    p=learning_event(); p['event_id']=invalid
    if invalid=='MISSING': p.pop('event_id')
    before=snapshot(factory)
    with pytest.raises(ValueError): s.process_event('user-a',p)
    assert snapshot(factory)==before
    source=Source([p])
    result=s.sync_events('user-a',source)
    assert result.retry_pending
    assert not source.acks
    assert snapshot(factory)==before


@pytest.mark.parametrize('field,value',[('stage_id',None),('passed_count',None),('event_type','unknown'),('stage_id','stage6'),('passed_count',-1),('total_count',0),('occurred_at','invalid')])
def test_ut09_2_valid_id_invalid_fields_reject_log_and_ack(factory,field,value):
    s=standard_service(factory); s.create_character('user-a','학당')
    p=learning_event(); p[field]=value
    if value is None: p.pop(field)
    before=snapshot(factory,('game_event_logs',))
    source=Source([p]); result=s.sync_events('user-a',source)
    assert source.acks==['event-1'] and result.events[0].status==EventStatus.REJECTED
    assert snapshot(factory,('game_event_logs',))==before
    with factory() as db: assert db.get(EventLogRow,'event-1').status=='rejected'


def test_ut10_replay_only_ack(factory):
    s=standard_service(factory); s.create_character('user-a','학당')
    p=learning_event(); s.process_event('user-a',p)
    before=snapshot(factory); source=Source([p])
    s.sync_events('user-a',source)
    assert source.acks==['event-1'] and snapshot(factory)==before


def test_ut10_mixed_source_order(factory):
    s=standard_service(factory); s.create_character('user-a','학당')
    source=Source([completion(1,'done'),learning_event('z'),learning_event('a'),
                   dict(learning_event('earlier'),occurred_at='2026-10-22T00:00:00Z')])
    s.sync_events('user-a',source)
    assert source.acks==['earlier','a','z','done']


def test_sync_sorts_timezone_offsets_and_rejects_bad_time(factory):
    s=standard_service(factory); s.create_character('user-a','학당')
    source=Source([dict(learning_event('invalid'),occurred_at='invalid'),
                   dict(learning_event('later'),occurred_at='2026-10-23T09:01:00+09:00'),
                   dict(learning_event('earlier'),occurred_at='2026-10-23T00:00:00Z')])
    result=s.sync_events('user-a',source)
    assert source.acks==['earlier','later','invalid']
    assert result.events[-1].status==EventStatus.REJECTED


def test_ut11_missing_character_failure_recovery_ack(factory):
    s=standard_service(factory); source=Source([learning_event()])
    assert s.sync_events('user-a',source).character_required and source.acks==[]
    assert all(not rows for rows in snapshot(factory).values())
    s.create_character('user-a','학당'); before=snapshot(factory,('game_event_logs',))
    def fail(session,*_):
        if any(isinstance(r,RewardHistoryRow) for r in session.new): raise RuntimeError('reward failure')
    event.listen(factory.class_,'before_flush',fail)
    try:
        assert s.sync_events('user-a',source).retry_pending and source.acks==[]
    finally: event.remove(factory.class_,'before_flush',fail)
    assert snapshot(factory,('game_event_logs',))==before
    with factory() as db: assert db.get(EventLogRow,'event-1').status=='failed'
    assert not s.sync_events('user-a',source).retry_pending
    assert source.acks==['event-1']
    with factory() as db:
        assert db.get(EventLogRow,'event-1').status=='processed'
        assert db.scalar(select(func.count()).select_from(CoinTransactionRow))==1
    assert s.get_game_state('user-a').coin_balance==10


def test_ut12_all_fields_match_storage_and_catalog(factory):
    s=standard_service(factory); c=s.create_character('user-a','학당'); fund(s)
    s.purchase_accessory('user-a','shoes','buy'); s.equip_accessory('user-a','shoes'); s.set_title('user-a','title_2')
    for promote in [False,True]:
        if promote: s.process_event('user-a',completion(1))
        out=s.get_game_state('user-a').model_dump(mode='json')
        with factory() as db:
            cr=db.get(CharacterRow,c.character_id); st=db.get(CharacterStateRow,c.character_id)
            pr=db.get(StoryProgressRow,(c.character_id,st.current_stage))
            expected={'character_id':cr.character_id,'character_name':cr.character_name}
            for key in ['current_stage','current_rank','active_title','coin_balance','crown','all_stages_completed','completion_presentation','pending_transition']:
                expected[key]=getattr(st,key)
            for key in ['passed_concept_count','total_concept_count','current_story_step']: expected[key]=getattr(pr,key)
            expected['stage_progress']=pr.passed_concept_count*100//pr.total_concept_count
            visual=VISUALS[Rank(st.current_rank)]; definition=STORY_RULES.definition(st.current_stage,pr.current_story_step)
            expected.update(default_outfit=visual.outfit,active_background=visual.background,
                            story_scene=definition.scene if definition else visual.background,
                            story_dialogue=definition.dialogue if definition else None,
                            available_titles=[t.model_dump(mode='json') for t in TITLES])
            mappings=[('owned_accessories',UserAccessoryRow,['accessory_id','acquired_at']),
                      ('story_rewards',StoryRewardRow,['stage','story_reward_id','source_event_id','unlocked_at']),
                      ('reward_history',RewardHistoryRow,['reward_key','reward_type','reward_ref','amount','source_event_id','created_at']),
                      ('stage_completion_history',StageCompletionRow,['stage','source_event_id','completed_at'])]
            for key,model,fields in mappings:
                expected[key]=[{f:getattr(r,f) for f in fields} for r in db.scalars(select(model).where(model.character_id==c.character_id))]
            eq=db.get(EquippedAccessoryRow,c.character_id)
            expected['equipped_accessory']={'accessory_id':eq.accessory_id,'equipped_at':eq.equipped_at} if eq else None
            assert set(expected)==set(GameStateOut.model_fields)==set(out)
            normalized=GameStateOut.model_validate(expected).model_dump(mode='json')
            for key in out:
                if isinstance(out[key],list): assert sorted(out[key],key=repr)==sorted(normalized[key],key=repr),key
                else: assert out[key]==normalized[key],key


def test_extra_titles_catalog_dialogue_rewards_and_performance(factory):
    s=standard_service(factory); s.create_character('user-a','학당')
    assert len(s.get_game_state('user-a').available_titles)==10
    before=s.get_game_state('user-a')
    for title in TITLES: assert s.set_title('user-a',title.title_id).active_title==title.title_id
    with pytest.raises(ValueError): s.set_title('user-a','not-in-catalog')
    after=s.get_game_state('user-a')
    assert after.coin_balance==before.coin_balance and after.reward_history==before.reward_history
    assert {i.accessory.accessory_id for i in s.list_shop_items('user-a')}==set(s.accessories)
    for stage in range(1,5):
        if stage>1: s.process_event('user-a',completion(stage-1))
        for step in range(5):
            count=step*STAGE_TOTALS[stage]//5
            if count: s.process_event('user-a',dict(learning_event(f'dialogue-{stage}-{step}',count),stage_id=f'stage{stage}',total_count=STAGE_TOTALS[stage],concept_id=f'd-{step}'))
            out=s.get_game_state('user-a'); definition=STORY_RULES.definition(stage,step)
            assert out.story_dialogue==definition.dialogue and out.story_scene==definition.scene
    s.process_event('user-a',completion(4))
    s.process_event('user-a',dict(learning_event('s5',1),stage_id='stage5',total_count=70))
    assert s.get_game_state('user-a').story_dialogue is None
    with factory() as db:
        assert {p.stage for p in db.scalars(select(StoryProgressRow))}=={1,2,3,4,5}
        for r in db.scalars(select(RewardHistoryRow)):
            assert r.source_event_id and r.created_at and db.get(EventLogRow,r.source_event_id)
        for r in db.scalars(select(CoinTransactionRow)):
            assert r.reason and r.created_at and r.source_event_id
    timings=[]
    for _ in range(100):
        start=time.perf_counter(); s.get_game_state('user-a'); timings.append((time.perf_counter()-start)*1000)
    print(f'{factory.kw["bind"].dialect.name} state n=100 mean={sum(timings)/100:.3f}ms p95={sorted(timings)[94]:.3f}ms')
    timings=[]
    for i in range(2,32):
        source=Source([dict(learning_event(f'perf-{i}',i),stage_id='stage5',total_count=70,concept_id=f'perf-{i}')])
        start=time.perf_counter(); s.sync_events('user-a',source); timings.append((time.perf_counter()-start)*1000)
    print(f'{factory.kw["bind"].dialect.name} fake-source sync n=30 mean={sum(timings)/30:.3f}ms p95={sorted(timings)[math.ceil(30*.95)-1]:.3f}ms')


def test_extra_event_log_write_failure_rolls_back_game_state(factory):
    s=standard_service(factory); s.create_character('user-a','학당')
    before=snapshot(factory,('game_event_logs',))
    def fail(session,*_):
        if any(isinstance(r,EventLogRow) and r.status=='processed' for r in session.dirty):
            raise RuntimeError('terminal audit write failure')
    event.listen(factory.class_,'before_flush',fail)
    source=Source([learning_event()])
    try:
        assert s.sync_events('user-a',source).retry_pending
    finally: event.remove(factory.class_,'before_flush',fail)
    assert source.acks==[] and snapshot(factory,('game_event_logs',))==before
    with factory() as db: assert db.get(EventLogRow,'event-1').status=='failed'


def test_extra_state_query_error_returns_503(factory):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import SQLAlchemyError
    from game.router import router
    from server_auth import get_verified_user_id
    class BrokenService:
        def get_game_state(self,user_id): raise SQLAlchemyError('injected database error')
    app=FastAPI(); app.include_router(router); app.state.game_service=BrokenService()
    app.dependency_overrides[get_verified_user_id]=lambda:'user-a'
    with TestClient(app) as client:
        response=client.get('/game/state')
        assert response.status_code==503 and 'injected' not in response.text


def test_awning_reward_boundary_and_replay(factory):
    s=standard_service(factory); s.create_character('user-a','학당')
    for count in (23,24,25):
        s.process_event('user-a',dict(learning_event(f'awning-{count}',count),concept_id=f'a-{count}'))
        rewards=[r.story_reward_id for r in s.get_game_state('user-a').story_rewards]
        assert rewards.count('awning') == (0 if count==23 else 1)
    s.process_event('user-a',dict(learning_event('awning-24',24),concept_id='a-24'))
    with factory() as db:
        row=db.scalar(select(StoryRewardRow).where(StoryRewardRow.story_reward_id=='awning'))
        assert row.source_event_id=='awning-24'
        assert db.scalar(select(func.count()).select_from(StoryRewardRow).where(StoryRewardRow.story_reward_id=='awning'))==1


def test_nonlearning_operations_do_not_promote(factory):
    s=standard_service(factory); s.create_character('user-a','학당'); fund(s)
    for action in (lambda:s.get_game_state('user-a'), lambda:s.list_shop_items('user-a'),
                   lambda:s.set_title('user-a','title_1'), lambda:s.purchase_accessory('user-a','shoes','buy'),
                   lambda:s.equip_accessory('user-a','shoes'),lambda:s.equip_accessory('user-a',None)):
        action(); assert s.get_game_state('user-a').current_rank==Rank.BEGGAR


def test_state_and_progress_timestamps_and_failure_rollback(factory):
    s=standard_service(factory); c=s.create_character('user-a','학당')
    def times():
        with factory() as db:
            return (db.get(CharacterStateRow,c.character_id).updated_at,
                    db.get(StoryProgressRow,(c.character_id,1)).updated_at)
    original=times(); s.process_event('user-a',learning_event('advance',6)); advanced=times()
    assert advanced[0]>original[0] and advanced[1]>original[1]
    s.set_title('user-a','title_1'); assert times()[0]>advanced[0]
    before=snapshot(factory,('game_event_logs',))
    def fail(session,*_):
        if any(isinstance(r,RewardHistoryRow) for r in session.new): raise RuntimeError('injected failure')
    event.listen(factory.class_,'before_flush',fail)
    try:
        with pytest.raises(RuntimeError): s.process_event('user-a',dict(learning_event('fail',18),concept_id='new'))
    finally: event.remove(factory.class_,'before_flush',fail)
    assert snapshot(factory,('game_event_logs',))==before
