"""퀴즈 세트와 제출 이력.

0929 문서 3.2에 따라 학습노트 전용 테이블과 오답노트 테이블은 만들지 않습니다.
학습노트는 quiz_sets와 quiz_submissions의 outer join으로 조회합니다.
stage_id는 학습노트 조회 쿼리를 위한 컬럼이고, idempotency_key는 중복 제출을 구분하는 컬럼입니다.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator

from app.db import Base
from app.timeutil import utc_now


class JSONBColumn(TypeDecorator):
    """Postgres에서는 JSONB, 그 외 엔진에서는 JSON으로 저장합니다."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class QuizSetStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class QuizSet(Base):
    __tablename__ = "quiz_sets"
    __table_args__ = (
        CheckConstraint(
            "status in ('pending', 'processing', 'completed', 'failed')",
            name="ck_quiz_sets_status",
        ),
        UniqueConstraint("user_id", "learning_session_id", name="uq_quiz_sets_user_session"),
        Index("ix_quiz_sets_user_concept", "user_id", "concept_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    concept_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    learning_session_id: Mapped[str] = mapped_column(String, nullable=False)
    stage_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    questions: Mapped[list] = mapped_column(JSONBColumn, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    submissions: Mapped[list[QuizSubmission]] = relationship(back_populates="quiz_set")


class QuizSubmission(Base):
    __tablename__ = "quiz_submissions"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_quiz_submissions_user_idempotency"),
        Index("ix_quiz_submissions_quiz_set_id", "quiz_set_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    quiz_set_id: Mapped[str] = mapped_column(ForeignKey("quiz_sets.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    submitted_answers: Mapped[list] = mapped_column(JSONBColumn, nullable=False)
    is_correct_list: Mapped[list] = mapped_column(JSONBColumn, nullable=False)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False)
    is_passed: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    quiz_set: Mapped[QuizSet] = relationship(back_populates="submissions")
