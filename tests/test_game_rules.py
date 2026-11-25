import pytest
from pydantic import ValidationError

from game.rules import RankPolicy, StoryDefinition, StoryRules, stage_number
from game.schemas import CharacterNameIn, Crown, Rank


def test_integer_thresholds_and_skipped_rewards():
    rules = StoryRules([
        StoryDefinition(1, 2, "can", "can"),
        StoryDefinition(1, 3, "umbrella", "umbrella"),
    ])
    assert rules.resolve_step(5, 30) == 0
    assert rules.resolve_step(6, 30) == 1
    assert rules.progress_percent(5, 30) == 16
    assert [d.story_reward_id for d in rules.pending_rewards(1, 1, 3)] == ["can", "umbrella"]
    assert rules.pending_rewards(1, 3, 1) == []
    with pytest.raises(ValueError):
        rules.resolve_step(31, 30)
    with pytest.raises(ValueError):
        rules.progress_percent(0, 0)


def test_rank_crown_and_stage_validation():
    assert stage_number("stage5") == 5
    with pytest.raises(ValueError):
        stage_number("stage05")
    assert RankPolicy.next_rank(3) == Rank.KING
    assert not RankPolicy.can_promote(2, 1, False)
    assert not RankPolicy.can_promote(2, 2, True)
    assert StoryRules.crown_for(5, 27) == Crown.BRONZE
    assert StoryRules.crown_for(5, 28) == Crown.SILVER
    assert StoryRules.crown_for(5, 70, True) == Crown.GOLD


def test_character_name_rejects_whitespace_digits_and_extra_fields():
    assert CharacterNameIn(name="학당ABC").name == "학당ABC"
    for name in ["", "가" * 11, "학당1", " 학당", "학당\n", "😀"]:
        with pytest.raises(ValidationError):
            CharacterNameIn(name=name)
    with pytest.raises(ValidationError):
        CharacterNameIn(name="학당", user_id="other")
