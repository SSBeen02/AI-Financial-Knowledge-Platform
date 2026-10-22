"""외부 연결 없이 검증 가능한 이야기·승급 규칙."""
import re
from dataclasses import dataclass

from game.schemas import Crown, Rank


def stage_number(stage_id: str) -> int:
    if not re.fullmatch(r"stage[1-5]", stage_id):
        raise ValueError("정의되지 않은 스테이지입니다.")
    return int(stage_id[-1])


def validate_counts(passed_count: int, total_count: int) -> None:
    if total_count <= 0 or not 0 <= passed_count <= total_count:
        raise ValueError("통과 개수가 허용 범위를 벗어났습니다.")


@dataclass(frozen=True)
class StoryDefinition:
    stage: int
    step: int
    scene: str
    story_reward_id: str | None = None
    dialogue: str | None = None


class StoryRules:
    def __init__(self, definitions: list[StoryDefinition]):
        self._definitions = {(d.stage, d.step): d for d in definitions}
        if len(self._definitions) != len(definitions):
            raise ValueError("이야기 정의의 스테이지·단계가 중복됩니다.")

    @staticmethod
    def resolve_step(passed_count: int, total_count: int) -> int:
        validate_counts(passed_count, total_count)
        return passed_count * 5 // total_count

    @staticmethod
    def progress_percent(passed_count: int, total_count: int) -> int:
        validate_counts(passed_count, total_count)
        return passed_count * 100 // total_count

    def definition(self, stage: int, step: int) -> StoryDefinition | None:
        return self._definitions.get((stage, step))

    def pending_rewards(self, stage: int, old_step: int, new_step: int) -> list[StoryDefinition]:
        if not 0 <= old_step <= 5 or not 0 <= new_step <= 5:
            raise ValueError("이야기 단계는 0~5여야 합니다.")
        return [d for step in range(old_step + 1, new_step + 1)
                if (d := self.definition(stage, step)) and d.story_reward_id]

    @staticmethod
    def crown_for(stage: int, passed_count: int, completed: bool = False) -> Crown | None:
        if stage not in range(1, 6) or passed_count < 0:
            raise ValueError("왕관 판정 값이 잘못되었습니다.")
        if stage == 5:
            return Crown.GOLD if completed else Crown.SILVER if passed_count >= 28 else Crown.BRONZE
        return Crown.BRONZE if stage == 4 else None


class RankPolicy:
    @staticmethod
    def next_rank(completed_stage: int) -> Rank:
        if completed_stage not in range(1, 6):
            raise ValueError("정의되지 않은 스테이지입니다.")
        return {1: Rank.COMMONER, 2: Rank.SCHOLAR}.get(completed_stage, Rank.KING)

    @staticmethod
    def can_promote(current_stage: int, event_stage: int, already_completed: bool) -> bool:
        return current_stage == event_stage and not already_completed and event_stage in range(1, 6)
