"""게임 전용 영속 모델. 테이블 생성은 배포 마이그레이션에서 수행한다."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class CharacterRow(Base):
    __tablename__ = "game_characters"
    character_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    character_name: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CharacterStateRow(Base):
    __tablename__ = "game_character_states"
    __table_args__ = (
        CheckConstraint("current_stage BETWEEN 1 AND 5"),
        CheckConstraint("coin_balance >= 0"),
    )
    character_id: Mapped[str] = mapped_column(ForeignKey("game_characters.character_id"), primary_key=True)
    current_stage: Mapped[int] = mapped_column(Integer, default=1)
    current_rank: Mapped[str] = mapped_column(String(20), default="꽃거지")
    active_title: Mapped[str | None] = mapped_column(String(100))
    coin_balance: Mapped[int] = mapped_column(Integer, default=0)
    crown: Mapped[str | None] = mapped_column(String(20))
    all_stages_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completion_presentation: Mapped[dict | None] = mapped_column(JSON)
    pending_transition: Mapped[dict | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class StoryProgressRow(Base):
    __tablename__ = "game_story_progress"
    __table_args__ = (
        CheckConstraint("stage BETWEEN 1 AND 5"),
        CheckConstraint("total_concept_count > 0"),
        CheckConstraint("passed_concept_count BETWEEN 0 AND total_concept_count"),
        CheckConstraint("current_story_step BETWEEN 0 AND 5"),
    )
    character_id: Mapped[str] = mapped_column(ForeignKey("game_characters.character_id"), primary_key=True)
    stage: Mapped[int] = mapped_column(Integer, primary_key=True)
    passed_concept_count: Mapped[int] = mapped_column(Integer, default=0)
    total_concept_count: Mapped[int] = mapped_column(Integer)
    current_story_step: Mapped[int] = mapped_column(Integer, default=0)
    last_event_id: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class EventLogRow(Base):
    __tablename__ = "game_event_logs"
    __table_args__ = (CheckConstraint("status IN ('processing','processed','rejected','failed')"),)
    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20))
    result: Mapped[dict | None] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CoinTransactionRow(Base):
    __tablename__ = "game_coin_transactions"
    __table_args__ = (
        UniqueConstraint("character_id", "idempotency_key"),
        UniqueConstraint("character_id", "stage", "concept_id", "reason"),
        CheckConstraint("balance_after >= 0"),
    )
    tx_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    character_id: Mapped[str] = mapped_column(ForeignKey("game_characters.character_id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(100))
    stage: Mapped[int | None] = mapped_column(Integer)
    concept_id: Mapped[str | None] = mapped_column(String(100))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    source_event_id: Mapped[str | None] = mapped_column(String(100))
    balance_after: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StageCompletionRow(Base):
    __tablename__ = "game_stage_completions"
    character_id: Mapped[str] = mapped_column(ForeignKey("game_characters.character_id"), primary_key=True)
    stage: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_event_id: Mapped[str] = mapped_column(String(100))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StoryRewardRow(Base):
    __tablename__ = "game_story_rewards"
    character_id: Mapped[str] = mapped_column(ForeignKey("game_characters.character_id"), primary_key=True)
    stage: Mapped[int] = mapped_column(Integer, primary_key=True)
    story_reward_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    source_event_id: Mapped[str | None] = mapped_column(String(100))
    unlocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
