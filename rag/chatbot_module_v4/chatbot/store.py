"""대화 기록·학습 맥락 저장소.

서비스는 이 인터페이스만 사용한다. 로컬은 SQLite, 배포는 PostgreSQL로
`CHAT_DB_URL`만 바꿔 같은 코드가 동작한다.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import (
    JSON,
    DateTime,
    Index,
    String,
    UniqueConstraint,
    create_engine,
    delete,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from chatbot.config import Settings
from chatbot.learning_management import require_database_tables

StartType = Literal["keyword", "detected", "relearn", "quiz_retry"]
SessionStatus = Literal["active", "completed"]
QuizStatus = Literal["pending", "passed", "failed", "generation_failed"]
MessageRole = Literal["user", "assistant"]

_START_TYPES = {"keyword", "detected", "relearn", "quiz_retry"}
_SESSION_STATUSES = {"active", "completed"}
_QUIZ_STATUSES = {"pending", "passed", "failed", "generation_failed"}


class ChatStoreError(Exception):
    """저장소 규칙을 지킬 수 없을 때."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    user_id: str
    stage: str
    concept_id: str
    term: str
    attempt: int
    start_type: StartType
    status: SessionStatus
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class PendingQuiz:
    session_id: str
    user_id: str
    concept_id: str
    stage: str
    term: str


@dataclass(frozen=True)
class LatestQuiz:
    session_id: str
    user_id: str
    concept_id: str
    stage: str
    quiz_status: QuizStatus
    created_at: datetime


@dataclass(frozen=True)
class LearningContextRecord:
    session_id: str
    user_id: str
    concept_id: str
    quiz_status: QuizStatus
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class CompletionRequestRecord:
    user_id: str
    session_id: str
    idempotency_key: str
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class MessageRecord:
    message_id: str
    session_id: str | None
    user_id: str
    role: MessageRole
    content: str
    is_related: bool | None
    band: str | None
    top_score: float | None
    sources: list[dict[str, Any]] | None
    display_sources: list[dict[str, Any]] | None
    latency_ms: int | None
    created_at: datetime


@dataclass(frozen=True)
class StoredMessagePair:
    user: MessageRecord
    assistant: MessageRecord


@dataclass(frozen=True)
class ConversationTurn:
    question: str
    answer: str


class ChatStore(ABC):
    @abstractmethod
    def create_session(
        self,
        *,
        user_id: str,
        stage: str,
        concept_id: str,
        term: str,
        attempt: int,
        start_type: StartType,
        status: SessionStatus = "active",
        completed_at: datetime | None = None,
    ) -> SessionRecord: ...

    @abstractmethod
    def get_session(self, user_id: str, session_id: str) -> SessionRecord | None:
        """요청한 사용자의 세션만 반환한다. 없으면 None."""

    @abstractmethod
    def get_active_session(self, user_id: str) -> SessionRecord | None: ...

    @abstractmethod
    def get_next_attempt(self, user_id: str, concept_id: str, stage: str) -> int: ...

    @abstractmethod
    def complete_session(
        self,
        user_id: str,
        session_id: str,
        *,
        completed_at: datetime | None = None,
    ) -> SessionRecord: ...

    @abstractmethod
    def get_completion_request(
        self, user_id: str, idempotency_key: str
    ) -> CompletionRequestRecord | None: ...

    @abstractmethod
    def complete_session_with_context(
        self,
        *,
        user_id: str,
        session_id: str,
        concept_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
        completion_payload: dict[str, Any] | None = None,
        quiz_status: QuizStatus = "pending",
        completed_at: datetime,
    ) -> LearningContextRecord:
        """세션 완료, 학습 맥락, 멱등성 결과를 한 트랜잭션에 저장한다."""

    @abstractmethod
    def save_message_pair(
        self,
        *,
        user_id: str,
        session_id: str | None,
        question: str,
        answer: str,
        is_related: bool,
        band: str,
        top_score: float,
        sources: list[dict[str, Any]],
        latency_ms: int,
        display_sources: list[dict[str, Any]] | None = None,
    ) -> StoredMessagePair: ...

    @abstractmethod
    def get_recent_turns(
        self,
        user_id: str,
        session_id: str,
        *,
        limit: int,
    ) -> list[ConversationTurn]: ...

    @abstractmethod
    def get_session_messages(self, user_id: str, session_id: str) -> list[MessageRecord]: ...

    @abstractmethod
    def get_recent_messages(self, user_id: str, *, limit: int) -> list[MessageRecord]: ...

    @abstractmethod
    def get_previous_attempt_turns(
        self,
        user_id: str,
        concept_id: str,
        stage: str,
        *,
        before_attempt: int,
        limit: int,
    ) -> list[ConversationTurn]: ...

    @abstractmethod
    def save_learning_context(
        self,
        *,
        session_id: str,
        user_id: str,
        concept_id: str,
        payload: dict[str, Any],
        quiz_status: QuizStatus = "pending",
    ) -> LearningContextRecord: ...

    @abstractmethod
    def get_pending_quiz(self, user_id: str) -> PendingQuiz | None: ...

    @abstractmethod
    def get_learning_context(
        self, user_id: str, session_id: str
    ) -> LearningContextRecord | None: ...

    @abstractmethod
    def list_learning_contexts(self, user_id: str) -> list[LearningContextRecord]: ...

    @abstractmethod
    def get_latest_quiz(self, user_id: str, concept_id: str, stage: str) -> LatestQuiz | None:
        """그 (개념, 스테이지)의 학습 맥락 중 가장 최근 퀴즈 상태."""

    @abstractmethod
    def set_quiz_status(self, user_id: str, session_id: str, quiz_status: QuizStatus) -> None: ...

    @abstractmethod
    def reset_user(self, user_id: str) -> None:
        """개발 도구에서 한 사용자의 대화·세션·학습 맥락을 모두 지운다."""

    @abstractmethod
    def close(self) -> None: ...


class Base(DeclarativeBase):
    pass


class LearningSessionRow(Base):
    __tablename__ = "learning_sessions"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    concept_id: Mapped[str] = mapped_column(String, nullable=False)
    term: Mapped[str] = mapped_column(String, nullable=False)
    attempt: Mapped[int] = mapped_column(nullable=False)
    start_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "uq_learning_sessions_one_active",
            "user_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )


class LearningMessageRow(Base):
    """메시지 API는 이후 단계에서 쓴다. 테이블은 지금 만들어 둔다."""

    __tablename__ = "learning_messages"

    message_id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    is_related: Mapped[bool | None] = mapped_column(nullable=True)
    band: Mapped[str | None] = mapped_column(String, nullable=True)
    top_score: Mapped[float | None] = mapped_column(nullable=True)
    sources: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    display_sources: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LearningContextRow(Base):
    __tablename__ = "learning_contexts"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    concept_id: Mapped[str] = mapped_column(String, nullable=False)
    quiz_status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LearningCompletionRequestRow(Base):
    __tablename__ = "learning_completion_requests"

    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "idempotency_key", name="uq_learning_completion_user_key"
        ),
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _require_quiz_status(quiz_status: str) -> QuizStatus:
    if quiz_status not in _QUIZ_STATUSES:
        raise ChatStoreError(f"알 수 없는 퀴즈 상태입니다: {quiz_status}")
    return quiz_status  # type: ignore[return-value]


class SqlChatStore(ChatStore):
    def __init__(self, settings: Settings):
        connect_args = {}
        if settings.chat_db_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        self._engine = create_engine(settings.chat_db_url, connect_args=connect_args)
        if settings.db_auto_create:
            if settings.chat_db_url.startswith("sqlite"):
                self._migrate_sqlite_schema()
            Base.metadata.create_all(self._engine)
            if settings.chat_db_url.startswith("sqlite"):
                with self._engine.begin() as connection:
                    connection.exec_driver_sql(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_learning_sessions_one_active "
                        "ON learning_sessions (user_id) WHERE status = 'active'"
                    )
        else:
            require_database_tables(
                self._engine,
                {
                    "learning_sessions",
                    "learning_messages",
                    "learning_contexts",
                    "learning_completion_requests",
                },
            )

    def close(self) -> None:
        self._engine.dispose()

    def _migrate_sqlite_schema(self) -> None:
        """기존 chat_* 테이블과 doc_id 데이터를 손실 없이 새 이름으로 옮긴다."""
        inspector = inspect(self._engine)
        with self._engine.begin() as connection:
            tables = set(inspector.get_table_names())
            if "chat_sessions" in tables and "learning_sessions" not in tables:
                connection.exec_driver_sql(
                    "ALTER TABLE chat_sessions RENAME TO learning_sessions"
                )
            if "chat_messages" in tables and "learning_messages" not in tables:
                connection.exec_driver_sql(
                    "ALTER TABLE chat_messages RENAME TO learning_messages"
                )

        inspector = inspect(self._engine)
        tables = set(inspector.get_table_names())
        for table in ("learning_sessions", "learning_contexts"):
            if table not in tables:
                continue
            columns = {column["name"] for column in inspector.get_columns(table)}
            if "doc_id" in columns and "concept_id" not in columns:
                with self._engine.begin() as connection:
                    connection.exec_driver_sql(
                        f"ALTER TABLE {table} RENAME COLUMN doc_id TO concept_id"
                    )

        inspector = inspect(self._engine)
        if "learning_messages" in inspector.get_table_names():
            columns = {
                column["name"] for column in inspector.get_columns("learning_messages")
            }
            if "display_sources" not in columns:
                with self._engine.begin() as connection:
                    connection.exec_driver_sql(
                        "ALTER TABLE learning_messages ADD COLUMN display_sources JSON"
                    )
            with self._engine.begin() as connection:
                for column in ("sources", "display_sources"):
                    connection.exec_driver_sql(
                        f"UPDATE learning_messages SET {column} = "
                        f"replace({column}, '\"doc_id\"', '\"concept_id\"') "
                        f"WHERE {column} IS NOT NULL"
                    )
        if "learning_contexts" in inspector.get_table_names():
            with self._engine.begin() as connection:
                connection.exec_driver_sql(
                    "UPDATE learning_contexts SET payload = "
                    "replace(replace(replace(replace(payload, "
                    "'\"doc_id\"', '\"concept_id\"'), "
                    "'\"미학습\"', '\"not_started\"'), "
                    "'\"\ubbf8\ud1b5\uacfc\"', '\"in_progress\"'), "
                    "'\"통과\"', '\"passed\"')"
                )

    def create_session(
        self,
        *,
        user_id: str,
        stage: str,
        concept_id: str,
        term: str,
        attempt: int,
        start_type: StartType,
        status: SessionStatus = "active",
        completed_at: datetime | None = None,
    ) -> SessionRecord:
        if start_type not in _START_TYPES:
            raise ChatStoreError(f"알 수 없는 세션 시작 유형입니다: {start_type}")
        if status not in _SESSION_STATUSES:
            raise ChatStoreError(f"알 수 없는 세션 상태입니다: {status}")
        if attempt < 1:
            raise ChatStoreError("attempt는 1 이상이어야 합니다.")
        if status == "active" and self.get_active_session(user_id) is not None:
            raise ChatStoreError("진행 중인 세션은 하나만 있을 수 있습니다.")
        now = _utcnow()
        finished = None if status == "active" else _as_utc(completed_at or now)
        row = LearningSessionRow(
            session_id=str(uuid.uuid4()),
            user_id=user_id,
            stage=stage,
            concept_id=concept_id,
            term=term,
            attempt=attempt,
            start_type=start_type,
            status=status,
            created_at=now,
            completed_at=finished,
        )
        with Session(self._engine) as session:
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ChatStoreError(
                    "다른 요청에서 이미 학습 세션을 시작했습니다."
                ) from exc
            session.refresh(row)
            return _session_record(row)

    def get_session(self, user_id: str, session_id: str) -> SessionRecord | None:
        with Session(self._engine) as session:
            row = session.scalars(
                select(LearningSessionRow).where(
                    LearningSessionRow.session_id == session_id,
                    LearningSessionRow.user_id == user_id,
                )
            ).one_or_none()
            return _session_record(row) if row is not None else None

    def get_active_session(self, user_id: str) -> SessionRecord | None:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(LearningSessionRow).where(
                    LearningSessionRow.user_id == user_id,
                    LearningSessionRow.status == "active",
                )
            ).all()
            if not rows:
                return None
            if len(rows) > 1:
                raise ChatStoreError("진행 중인 세션은 하나만 있을 수 있습니다.")
            return _session_record(rows[0])

    def get_next_attempt(self, user_id: str, concept_id: str, stage: str) -> int:
        with Session(self._engine) as session:
            latest = session.scalar(
                select(func.max(LearningSessionRow.attempt)).where(
                    LearningSessionRow.user_id == user_id,
                    LearningSessionRow.concept_id == concept_id,
                    LearningSessionRow.stage == stage,
                )
            )
        return int(latest or 0) + 1

    def complete_session(
        self,
        user_id: str,
        session_id: str,
        *,
        completed_at: datetime | None = None,
    ) -> SessionRecord:
        with Session(self._engine) as session:
            row = session.get(LearningSessionRow, session_id)
            if row is None or row.user_id != user_id:
                raise ChatStoreError("세션을 찾을 수 없습니다.")
            if row.status != "active":
                raise ChatStoreError("이미 완료된 세션입니다.")
            row.status = "completed"
            row.completed_at = _as_utc(completed_at or _utcnow())
            session.commit()
            session.refresh(row)
            return _session_record(row)

    def get_completion_request(
        self, user_id: str, idempotency_key: str
    ) -> CompletionRequestRecord | None:
        with Session(self._engine) as session:
            row = session.scalars(
                select(LearningCompletionRequestRow).where(
                    LearningCompletionRequestRow.user_id == user_id,
                    LearningCompletionRequestRow.idempotency_key == idempotency_key,
                )
            ).one_or_none()
            return _completion_request_record(row) if row is not None else None

    def complete_session_with_context(
        self,
        *,
        user_id: str,
        session_id: str,
        concept_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
        completion_payload: dict[str, Any] | None = None,
        quiz_status: QuizStatus = "pending",
        completed_at: datetime,
    ) -> LearningContextRecord:
        completed_at = _as_utc(completed_at)
        quiz_status = _require_quiz_status(quiz_status)
        now = _utcnow()
        with Session(self._engine) as session:
            existing = session.scalars(
                select(LearningCompletionRequestRow).where(
                    LearningCompletionRequestRow.user_id == user_id,
                    LearningCompletionRequestRow.idempotency_key == idempotency_key,
                )
            ).one_or_none()
            if existing is not None:
                if existing.session_id != session_id:
                    raise ChatStoreError(
                        "같은 Idempotency-Key를 다른 학습 완료 요청에 사용할 수 없습니다."
                    )
                context = session.get(LearningContextRow, session_id)
                if context is None:
                    raise ChatStoreError("멱등성 완료 결과의 학습 맥락을 찾을 수 없습니다.")
                return _context_record(context)

            learning_session = session.get(LearningSessionRow, session_id)
            if learning_session is None or learning_session.user_id != user_id:
                raise ChatStoreError("세션을 찾을 수 없습니다.")
            if learning_session.status != "active":
                raise ChatStoreError("이미 완료된 세션입니다.")
            if learning_session.concept_id != concept_id:
                raise ChatStoreError("학습 맥락의 개념이 세션과 다릅니다.")

            learning_session.status = "completed"
            learning_session.completed_at = completed_at
            context = LearningContextRow(
                session_id=session_id,
                user_id=user_id,
                concept_id=concept_id,
                quiz_status=quiz_status,
                payload=payload,
                created_at=now,
            )
            completion_request = LearningCompletionRequestRow(
                request_id=str(uuid.uuid4()),
                user_id=user_id,
                session_id=session_id,
                idempotency_key=idempotency_key,
                payload=completion_payload or payload,
                created_at=now,
            )
            session.add_all([context, completion_request])
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                replay = self.get_completion_request(user_id, idempotency_key)
                if replay is not None and replay.session_id == session_id:
                    replay_context = self.get_learning_context(user_id, session_id)
                    if replay_context is not None:
                        return replay_context
                raise ChatStoreError("학습 완료 요청이 다른 요청과 충돌했습니다.") from exc
            session.refresh(context)
            return _context_record(context)

    def save_message_pair(
        self,
        *,
        user_id: str,
        session_id: str | None,
        question: str,
        answer: str,
        is_related: bool,
        band: str,
        top_score: float,
        sources: list[dict[str, Any]],
        latency_ms: int,
        display_sources: list[dict[str, Any]] | None = None,
    ) -> StoredMessagePair:
        if band not in {"high", "mid", "low"}:
            raise ChatStoreError(f"알 수 없는 band입니다: {band}")
        if latency_ms < 0:
            raise ChatStoreError("latency_ms는 0 이상이어야 합니다.")
        if session_id is not None and self.get_session(user_id, session_id) is None:
            raise ChatStoreError("세션을 찾을 수 없습니다.")
        now = _utcnow()
        user_row = LearningMessageRow(
            message_id=str(uuid.uuid4()),
            session_id=session_id,
            user_id=user_id,
            role="user",
            content=question,
            is_related=None,
            band=None,
            top_score=None,
            sources=None,
            display_sources=None,
            latency_ms=None,
            created_at=now,
        )
        assistant_row = LearningMessageRow(
            message_id=str(uuid.uuid4()),
            session_id=session_id,
            user_id=user_id,
            role="assistant",
            content=answer,
            is_related=is_related,
            band=band,
            top_score=top_score,
            sources=sources,
            display_sources=display_sources or [],
            latency_ms=latency_ms,
            created_at=now + timedelta(microseconds=1),
        )
        with Session(self._engine) as session:
            session.add_all([user_row, assistant_row])
            session.commit()
            session.refresh(user_row)
            session.refresh(assistant_row)
            return StoredMessagePair(
                user=_message_record(user_row),
                assistant=_message_record(assistant_row),
            )

    def get_recent_turns(
        self,
        user_id: str,
        session_id: str,
        *,
        limit: int,
    ) -> list[ConversationTurn]:
        if limit < 1:
            return []
        if self.get_session(user_id, session_id) is None:
            raise ChatStoreError("세션을 찾을 수 없습니다.")
        with Session(self._engine) as session:
            rows = session.scalars(
                select(LearningMessageRow)
                .where(
                    LearningMessageRow.user_id == user_id,
                    LearningMessageRow.session_id == session_id,
                )
                .order_by(LearningMessageRow.created_at.asc(), LearningMessageRow.message_id.asc())
            ).all()
        return _turns_from_rows(rows)[-limit:]

    def get_session_messages(self, user_id: str, session_id: str) -> list[MessageRecord]:
        if self.get_session(user_id, session_id) is None:
            raise ChatStoreError("세션을 찾을 수 없습니다.")
        with Session(self._engine) as session:
            rows = session.scalars(
                select(LearningMessageRow)
                .where(
                    LearningMessageRow.user_id == user_id,
                    LearningMessageRow.session_id == session_id,
                )
                .order_by(LearningMessageRow.created_at.asc(), LearningMessageRow.message_id.asc())
            ).all()
        return [_message_record(row) for row in rows]

    def get_recent_messages(self, user_id: str, *, limit: int) -> list[MessageRecord]:
        if limit < 1:
            return []
        with Session(self._engine) as session:
            rows = session.scalars(
                select(LearningMessageRow)
                .where(LearningMessageRow.user_id == user_id)
                .order_by(LearningMessageRow.created_at.desc(), LearningMessageRow.message_id.desc())
                .limit(limit)
            ).all()
        rows.reverse()
        return [_message_record(row) for row in rows]

    def get_previous_attempt_turns(
        self,
        user_id: str,
        concept_id: str,
        stage: str,
        *,
        before_attempt: int,
        limit: int,
    ) -> list[ConversationTurn]:
        if limit < 1 or before_attempt <= 1:
            return []
        with Session(self._engine) as session:
            rows = session.scalars(
                select(LearningMessageRow)
                .join(LearningSessionRow, LearningSessionRow.session_id == LearningMessageRow.session_id)
                .where(
                    LearningMessageRow.user_id == user_id,
                    LearningSessionRow.user_id == user_id,
                    LearningSessionRow.concept_id == concept_id,
                    LearningSessionRow.stage == stage,
                    LearningSessionRow.attempt < before_attempt,
                )
                .order_by(LearningMessageRow.created_at.asc(), LearningMessageRow.message_id.asc())
            ).all()
        return _turns_from_rows(rows)[-limit:]

    def save_learning_context(
        self,
        *,
        session_id: str,
        user_id: str,
        concept_id: str,
        payload: dict[str, Any],
        quiz_status: QuizStatus = "pending",
    ) -> LearningContextRecord:
        quiz_status = _require_quiz_status(quiz_status)
        owner = self.get_session(user_id, session_id)
        if owner is None:
            raise ChatStoreError("세션을 찾을 수 없습니다.")
        if owner.concept_id != concept_id:
            raise ChatStoreError("학습 맥락의 개념이 세션과 다릅니다.")
        if quiz_status == "pending" and self.get_pending_quiz(user_id) is not None:
            raise ChatStoreError("퀴즈 대기 중인 학습 맥락은 하나만 있을 수 있습니다.")
        row = LearningContextRow(
            session_id=session_id,
            user_id=user_id,
            concept_id=concept_id,
            quiz_status=quiz_status,
            payload=payload,
            created_at=_utcnow(),
        )
        with Session(self._engine) as session:
            session.add(row)
            session.commit()
            session.refresh(row)
            return _context_record(row)

    def get_pending_quiz(self, user_id: str) -> PendingQuiz | None:
        with Session(self._engine) as session:
            rows = session.execute(
                select(LearningContextRow, LearningSessionRow)
                .join(LearningSessionRow, LearningSessionRow.session_id == LearningContextRow.session_id)
                .where(
                    LearningContextRow.user_id == user_id,
                    LearningContextRow.quiz_status == "pending",
                    LearningSessionRow.user_id == user_id,
                )
            ).all()
            if not rows:
                return None
            if len(rows) > 1:
                raise ChatStoreError("퀴즈 대기 중인 학습 맥락은 하나만 있을 수 있습니다.")
            context, chat_session = rows[0]
            return PendingQuiz(
                session_id=context.session_id,
                user_id=context.user_id,
                concept_id=context.concept_id,
                stage=chat_session.stage,
                term=chat_session.term,
            )

    def get_learning_context(
        self, user_id: str, session_id: str
    ) -> LearningContextRecord | None:
        with Session(self._engine) as session:
            row = session.get(LearningContextRow, session_id)
            if row is None or row.user_id != user_id:
                return None
            return _context_record(row)

    def list_learning_contexts(self, user_id: str) -> list[LearningContextRecord]:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(LearningContextRow)
                .where(LearningContextRow.user_id == user_id)
                .order_by(LearningContextRow.created_at.desc(), LearningContextRow.session_id.desc())
            ).all()
        return [_context_record(row) for row in rows]

    def get_latest_quiz(self, user_id: str, concept_id: str, stage: str) -> LatestQuiz | None:
        with Session(self._engine) as session:
            row = session.execute(
                select(LearningContextRow, LearningSessionRow)
                .join(LearningSessionRow, LearningSessionRow.session_id == LearningContextRow.session_id)
                .where(
                    LearningContextRow.user_id == user_id,
                    LearningContextRow.concept_id == concept_id,
                    LearningSessionRow.user_id == user_id,
                    LearningSessionRow.stage == stage,
                )
                .order_by(LearningContextRow.created_at.desc(), LearningContextRow.session_id.desc())
            ).first()
            if row is None:
                return None
            context, chat_session = row
            return LatestQuiz(
                session_id=context.session_id,
                user_id=context.user_id,
                concept_id=context.concept_id,
                stage=chat_session.stage,
                quiz_status=_require_quiz_status(context.quiz_status),
                created_at=_as_utc(context.created_at),
            )

    def set_quiz_status(self, user_id: str, session_id: str, quiz_status: QuizStatus) -> None:
        quiz_status = _require_quiz_status(quiz_status)
        if quiz_status == "pending":
            pending = self.get_pending_quiz(user_id)
            if pending is not None and pending.session_id != session_id:
                raise ChatStoreError("퀴즈 대기 중인 학습 맥락은 하나만 있을 수 있습니다.")
        with Session(self._engine) as session:
            row = session.get(LearningContextRow, session_id)
            if row is None or row.user_id != user_id:
                raise ChatStoreError("학습 맥락을 찾을 수 없습니다.")
            row.quiz_status = quiz_status
            session.commit()

    def reset_user(self, user_id: str) -> None:
        """사용자 범위로만 삭제한다. 참조 관계 순서대로 자식 레코드부터 지운다."""
        with Session(self._engine) as session:
            session.execute(
                delete(LearningCompletionRequestRow).where(
                    LearningCompletionRequestRow.user_id == user_id
                )
            )
            session.execute(
                delete(LearningContextRow).where(LearningContextRow.user_id == user_id)
            )
            session.execute(delete(LearningMessageRow).where(LearningMessageRow.user_id == user_id))
            session.execute(delete(LearningSessionRow).where(LearningSessionRow.user_id == user_id))
            session.commit()


def _session_record(row: LearningSessionRow) -> SessionRecord:
    if row.start_type not in _START_TYPES or row.status not in _SESSION_STATUSES:
        raise ChatStoreError("세션 기록이 올바르지 않습니다.")
    return SessionRecord(
        session_id=row.session_id,
        user_id=row.user_id,
        stage=row.stage,
        concept_id=row.concept_id,
        term=row.term,
        attempt=row.attempt,
        start_type=row.start_type,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        created_at=_as_utc(row.created_at),
        completed_at=_as_utc(row.completed_at) if row.completed_at is not None else None,
    )


def _context_record(row: LearningContextRow) -> LearningContextRecord:
    quiz_status = _require_quiz_status(row.quiz_status)
    payload = row.payload if isinstance(row.payload, dict) else {}
    return LearningContextRecord(
        session_id=row.session_id,
        user_id=row.user_id,
        concept_id=row.concept_id,
        quiz_status=quiz_status,
        payload=payload,
        created_at=_as_utc(row.created_at),
    )


def _completion_request_record(
    row: LearningCompletionRequestRow,
) -> CompletionRequestRecord:
    payload = row.payload if isinstance(row.payload, dict) else {}
    return CompletionRequestRecord(
        user_id=row.user_id,
        session_id=row.session_id,
        idempotency_key=row.idempotency_key,
        payload=payload,
        created_at=_as_utc(row.created_at),
    )


def _message_record(row: LearningMessageRow) -> MessageRecord:
    if row.role not in {"user", "assistant"}:
        raise ChatStoreError("메시지 역할이 올바르지 않습니다.")
    sources = row.sources if isinstance(row.sources, list) else None
    display_sources = row.display_sources if isinstance(row.display_sources, list) else None
    return MessageRecord(
        message_id=row.message_id,
        session_id=row.session_id,
        user_id=row.user_id,
        role=row.role,  # type: ignore[arg-type]
        content=row.content,
        is_related=row.is_related,
        band=row.band,
        top_score=row.top_score,
        sources=sources,
        display_sources=display_sources,
        latency_ms=row.latency_ms,
        created_at=_as_utc(row.created_at),
    )


def _turns_from_rows(rows: list[LearningMessageRow]) -> list[ConversationTurn]:
    turns: list[ConversationTurn] = []
    pending_question: str | None = None
    for row in rows:
        if row.role == "user":
            pending_question = row.content
        elif row.role == "assistant" and pending_question is not None:
            turns.append(ConversationTurn(question=pending_question, answer=row.content))
            pending_question = None
    return turns
