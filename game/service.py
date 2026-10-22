"""사용자별 이벤트 반영과 게임 상태 조회. 모든 변경은 캐릭터 잠금 안에서 수행한다."""
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from game.models import (CharacterStateRow, CoinTransactionRow, EventLogRow,
                         StageCompletionRow, StoryProgressRow, StoryRewardRow, utcnow)
from game.rules import RankPolicy, StoryRules, stage_number, validate_counts
from game.schemas import (EventResult, EventStatus, GameStateOut, LearningEventIn,
                          Rank, StageCompletion, StoryReward, SyncOut, Title)
from game.store import SqlCharacterStore, SqlUnitOfWork


class EventSource(Protocol):
    def get_unprocessed_events(self, *, user_id: str, limit: int = 100) -> list: ...
    def mark_event_processed(self, event_id: str): ...


@dataclass(frozen=True)
class RankVisual:
    outfit: str
    background: str


class GameService:
    def __init__(self, uow: SqlUnitOfWork, rules: StoryRules,
                 visuals: Mapping[Rank, RankVisual], totals: Mapping[int, int],
                 titles: tuple[Title, ...] = ()):
        if set(totals) != set(range(1, 6)) or any(v <= 0 for v in totals.values()):
            raise ValueError("스테이지별 전체 개념 수가 필요합니다.")
        if set(visuals) != set(Rank):
            raise ValueError("모든 신분의 기본 외형이 필요합니다.")
        self.uow, self.rules = uow, rules
        self.visuals, self.totals, self.titles = dict(visuals), dict(totals), titles

    def create_character(self, user_id: str, name: str):
        return self.uow.run(lambda s: SqlCharacterStore(s).create(user_id, name))

    def get_game_state(self, user_id: str) -> GameStateOut | None:
        return self.uow.run(lambda s: self._state(s, user_id))

    def _state(self, session: Session, user_id: str) -> GameStateOut | None:
        character = SqlCharacterStore(session).get_by_user(user_id)
        if character is None:
            return None
        state = session.get(CharacterStateRow, character.character_id)
        progress = session.get(StoryProgressRow, (character.character_id, state.current_stage))
        definition = self.rules.definition(state.current_stage, progress.current_story_step)
        visual = self.visuals[Rank(state.current_rank)]
        completions = session.scalars(select(StageCompletionRow).where(
            StageCompletionRow.character_id == character.character_id).order_by(StageCompletionRow.stage)).all()
        rewards = session.scalars(select(StoryRewardRow).where(
            StoryRewardRow.character_id == character.character_id)).all()
        return GameStateOut(
            character_id=character.character_id, character_name=character.character_name,
            current_stage=state.current_stage, current_rank=state.current_rank,
            current_story_step=progress.current_story_step,
            passed_concept_count=progress.passed_concept_count,
            total_concept_count=progress.total_concept_count,
            stage_progress=self.rules.progress_percent(progress.passed_concept_count, progress.total_concept_count),
            active_title=state.active_title, available_titles=list(self.titles),
            active_background=visual.background,
            story_scene=definition.scene if definition else visual.background,
            story_dialogue=definition.dialogue if definition else None,
            default_outfit=visual.outfit, crown=state.crown, coin_balance=state.coin_balance,
            story_rewards=[StoryReward(stage=r.stage, story_reward_id=r.story_reward_id,
                                      source_event_id=r.source_event_id, unlocked_at=r.unlocked_at)
                           for r in rewards],
            stage_completion_history=[StageCompletion(stage=c.stage, source_event_id=c.source_event_id,
                                                      completed_at=c.completed_at) for c in completions],
            completion_presentation=state.completion_presentation,
            pending_transition=state.pending_transition, all_stages_completed=state.all_stages_completed)

    def process_event(self, user_id: str, payload: dict) -> EventResult:
        # 사용자 격리 오류는 원본 이벤트 완료 표시의 근거로 사용하지 않는다.
        if payload.get("user_id") != user_id:
            raise ValueError("다른 사용자의 이벤트입니다.")
        event_id = payload.get("event_id")
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 100:
            raise ValueError("이벤트 ID가 필요합니다.")

        def work(session):
            store = SqlCharacterStore(session)
            character = store.get_by_user(user_id)
            if character is None:
                return EventResult(event_id=event_id, status=EventStatus.FAILED, message="캐릭터 생성 필요")
            store.lock(character.character_id)
            log = session.get(EventLogRow, event_id)
            if log is not None:
                if log.user_id != user_id:
                    raise ValueError("이벤트 소유자가 일치하지 않습니다.")
                if log.status in ("processed", "rejected", "processing"):
                    return EventResult(event_id=event_id, status=log.status,
                                       message=(log.result or {}).get("message"))
            else:
                log = EventLogRow(event_id=event_id, user_id=user_id, payload=payload, status="processing")
                session.add(log)
            log.status = "processing"
            session.flush()
            try:
                event = LearningEventIn.model_validate(payload)
                self._validate_event(event)
                state = session.get(CharacterStateRow, character.character_id)
                stage = stage_number(event.stage_id)
                if event.event_type == "concept_passed" and not event.first_pass:
                    pass
                elif stage > state.current_stage:
                    if stage == 5 and state.current_stage == 4 and state.all_stages_completed:
                        state.current_stage = 5
                        state.pending_transition = None
                        session.add(StoryProgressRow(character_id=character.character_id,
                                                     stage=5, total_concept_count=self.totals[5]))
                        session.flush()
                    else:
                        raise ValueError("현재 스테이지보다 앞선 이벤트입니다.")
                if event.event_type == "stage_completed":
                    self._complete(session, character.character_id, state, event, stage)
                elif event.first_pass:
                    self._pass(session, character.character_id, state, event, stage)
                result = EventResult(event_id=event_id, status=EventStatus.PROCESSED)
            except (ValueError, ValidationError) as exc:
                # 바깥 트랜잭션을 롤백한 후 거부 이력만 별도 저장한다.
                raise RejectedEvent(str(exc)) from exc
            log.status, log.result, log.processed_at = result.status.value, result.model_dump(mode="json"), utcnow()
            return result

        try:
            return self.uow.run(work)
        except RejectedEvent as exc:
            return self._record_terminal(user_id, event_id, payload, EventStatus.REJECTED, str(exc))
        except Exception:
            self._record_terminal(user_id, event_id, payload, EventStatus.FAILED, "이벤트 처리 실패")
            raise

    def _record_terminal(self, user_id, event_id, payload, status, message):
        def record(session):
            character = SqlCharacterStore(session).get_by_user(user_id)
            if character:
                SqlCharacterStore(session).lock(character.character_id)
            log = session.get(EventLogRow, event_id)
            if log and (log.user_id != user_id or log.status in ("processed", "rejected", "processing")):
                if log.user_id != user_id:
                    raise ValueError("이벤트 소유자가 일치하지 않습니다.")
                return EventResult(event_id=event_id, status=log.status, message=(log.result or {}).get("message"))
            result = EventResult(event_id=event_id, status=status, message=message)
            if log is None:
                log = EventLogRow(event_id=event_id, user_id=user_id, payload=payload)
                session.add(log)
            log.status, log.result = status.value, result.model_dump(mode="json")
            log.processed_at = utcnow() if status == EventStatus.REJECTED else None
            return result
        return self.uow.run(record)

    def _validate_event(self, event):
        stage = stage_number(event.stage_id)
        validate_counts(event.passed_count, event.total_count)
        if event.total_count != self.totals[stage]:
            raise ValueError("전체 개념 수가 카탈로그와 다릅니다.")
        if event.event_type == "concept_passed":
            if not event.concept_id or event.first_pass is None:
                raise ValueError("개념 통과 필드가 없습니다.")
        else:
            expected_next = f"stage{stage + 1}" if stage < 5 else None
            if (event.passed_count != event.total_count or not event.stage_completed
                    or event.next_stage_id != expected_next):
                raise ValueError("스테이지 완료 필드가 일치하지 않습니다.")

    def _pass(self, session, cid, state, event, stage, award_coin=True):
        transaction = session.scalar(select(CoinTransactionRow).where(
            CoinTransactionRow.character_id == cid, CoinTransactionRow.stage == stage,
            CoinTransactionRow.concept_id == event.concept_id, CoinTransactionRow.reason == "first_pass"))
        if transaction is None and award_coin:
            state.coin_balance += 10
            session.add(CoinTransactionRow(tx_id=str(uuid4()), character_id=cid, amount=10,
                reason="first_pass", stage=stage, concept_id=event.concept_id,
                idempotency_key=f"first_pass:{stage}:{event.concept_id}", source_event_id=event.event_id,
                balance_after=state.coin_balance))
        if stage != state.current_stage:
            return
        progress = session.get(StoryProgressRow, (cid, stage))
        if event.passed_count <= progress.passed_concept_count:
            return
        step = self.rules.resolve_step(event.passed_count, event.total_count)
        for reward in self.rules.pending_rewards(stage, progress.current_story_step, step):
            if session.get(StoryRewardRow, (cid, stage, reward.story_reward_id)) is None:
                session.add(StoryRewardRow(character_id=cid, stage=stage,
                    story_reward_id=reward.story_reward_id, source_event_id=event.event_id))
        progress.passed_concept_count, progress.current_story_step = event.passed_count, step
        progress.last_event_id = event.event_id
        state.crown = self.rules.crown_for(stage, event.passed_count)
        state.updated_at = utcnow()

    def _complete(self, session, cid, state, event, stage):
        completed = session.get(StageCompletionRow, (cid, stage))
        if not RankPolicy.can_promote(state.current_stage, stage, completed is not None):
            raise ValueError("스테이지 완료 순서가 일치하지 않습니다.")
        progress = session.get(StoryProgressRow, (cid, stage))
        self._pass(session, cid, state, event, stage, award_coin=False)
        session.add(StageCompletionRow(character_id=cid, stage=stage, source_event_id=event.event_id))
        state.current_rank = RankPolicy.next_rank(stage).value
        if stage < 4:
            state.current_stage = stage + 1
            session.add(StoryProgressRow(character_id=cid, stage=stage + 1,
                                         total_concept_count=self.totals[stage + 1]))
            state.crown = self.rules.crown_for(stage + 1, 0)
        elif stage == 4:
            state.all_stages_completed = True
            state.pending_transition = {"screen": "stage5_selection", "next_stage_id": "stage5"}
        else:
            state.crown = self.rules.crown_for(5, event.passed_count, completed=True)
        state.completion_presentation = {"stage": stage, "event_id": event.event_id,
                                         "rank": state.current_rank, "crown": state.crown}
        state.updated_at = utcnow()

    def sync_events(self, user_id: str, source: EventSource) -> SyncOut:
        if self.get_game_state(user_id) is None:
            return SyncOut(game_state=None, character_required=True)
        results = []
        retry = False
        seen = set()
        while True:
            batch = source.get_unprocessed_events(user_id=user_id, limit=100)
            if not batch:
                break
            advanced = False
            for item in batch:
                payload = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
                event_id = payload.get("event_id")
                if event_id in seen:
                    retry = True
                    continue
                seen.add(event_id)
                try:
                    result = self.process_event(user_id, payload)
                    results.append(result)
                    if result.status in (EventStatus.PROCESSED, EventStatus.REJECTED):
                        source.mark_event_processed(result.event_id)
                        advanced = True
                    else:
                        retry = True
                except Exception:
                    retry = True
                    break
            if retry:
                break
            if not advanced:
                break
        return SyncOut(game_state=self.get_game_state(user_id), events=results, retry_pending=retry)


class RejectedEvent(Exception):
    pass
