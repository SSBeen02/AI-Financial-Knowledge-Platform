"""게임 API와 저장소가 공유하는 계약."""
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


CharacterName = Annotated[str, StringConstraints(pattern=r"^[가-힣A-Za-z]{1,10}$", max_length=10)]


class Rank(str, Enum):
    BEGGAR = "꽃거지"
    COMMONER = "평민"
    SCHOLAR = "양반"
    KING = "왕"


class Crown(str, Enum):
    BRONZE = "동왕관"
    SILVER = "은왕관"
    GOLD = "금왕관"


class CharacterNameIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: CharacterName


class TitleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title_id: str = Field(min_length=1, max_length=100)


class AccessoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accessory_id: str = Field(min_length=1, max_length=100)


class Character(BaseModel):
    character_id: str
    user_id: str
    character_name: CharacterName
    created_at: datetime


class Title(BaseModel):
    title_id: str
    name: str


class Accessory(BaseModel):
    accessory_id: str
    name: str
    rank: Rank
    unlock_pass_count: int = Field(ge=0)
    price: int = Field(ge=0)
    on_sale: bool = True


class ShopItem(BaseModel):
    accessory: Accessory
    owned: bool
    unlocked: bool
    can_purchase: bool


class UserAccessory(BaseModel):
    accessory_id: str
    acquired_at: datetime


class EquippedAccessory(BaseModel):
    accessory_id: str
    equipped_at: datetime


class RewardHistory(BaseModel):
    reward_key: str
    reward_type: str
    reward_ref: str | None = None
    amount: int = 0
    source_event_id: str
    created_at: datetime


class StageCompletion(BaseModel):
    stage: int = Field(ge=1, le=5)
    source_event_id: str
    completed_at: datetime


class StoryReward(BaseModel):
    stage: int
    story_reward_id: str
    source_event_id: str | None = None
    unlocked_at: datetime


class CompletionPresentation(BaseModel):
    stage: int = Field(ge=1, le=5)
    event_id: str
    rank: Rank
    crown: Crown | None = None


class PendingTransition(BaseModel):
    screen: Literal["stage5_selection", "main"]
    next_stage_id: str | None = None


class GameStateOut(BaseModel):
    character_id: str
    character_name: CharacterName
    current_stage: int = Field(ge=1, le=5)
    current_rank: Rank
    current_story_step: int = Field(ge=0, le=5)
    passed_concept_count: int = Field(ge=0)
    total_concept_count: int = Field(gt=0)
    stage_progress: int = Field(ge=0, le=100)
    owned_accessories: list[UserAccessory] = Field(default_factory=list)
    equipped_accessory: EquippedAccessory | None = None
    available_titles: list[Title] = Field(default_factory=list)
    active_title: str | None = None
    active_background: str
    story_scene: str
    story_dialogue: str | None = None
    default_outfit: str
    crown: Crown | None = None
    coin_balance: int = Field(ge=0)
    reward_history: list[RewardHistory] = Field(default_factory=list)
    story_rewards: list[StoryReward] = Field(default_factory=list)
    stage_completion_history: list[StageCompletion] = Field(default_factory=list)
    completion_presentation: CompletionPresentation | None = None
    pending_transition: PendingTransition | None = None
    all_stages_completed: bool = False


class EventStatus(str, Enum):
    PROCESSING = "processing"
    PROCESSED = "processed"
    REJECTED = "rejected"
    FAILED = "failed"


class EventResult(BaseModel):
    event_id: str
    status: EventStatus
    message: str | None = None


class SyncOut(BaseModel):
    game_state: GameStateOut | None
    events: list[EventResult] = Field(default_factory=list)
    character_required: bool = False
    retry_pending: bool = False


class PurchaseResult(BaseModel):
    status: Literal["success", "already_owned", "insufficient_balance", "unavailable"]
    accessory_id: str
    coin_balance: int = Field(ge=0)


class LearningEventIn(BaseModel):
    """GameEventOut을 게임 경계에서 검증한다. 공급 모듈에는 의존하지 않는다."""
    event_id: str = Field(min_length=1, max_length=100)
    user_id: str = Field(min_length=1, max_length=36)
    event_type: Literal["concept_passed", "stage_completed"]
    stage_id: str = Field(pattern=r"^stage[1-5]$")
    concept_id: str | None = Field(default=None, max_length=100)
    first_pass: bool | None = Field(default=None, strict=True)
    passed_count: int = Field(strict=True)
    total_count: int = Field(strict=True)
    stage_completed: bool = Field(strict=True)
    next_stage_id: str | None = Field(default=None, pattern=r"^stage[1-5]$")
    occurred_at: datetime
