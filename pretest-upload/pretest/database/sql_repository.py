"""통합 서버의 기존 PostgreSQL 연결로 담당자 저장소 계약을 구현한다."""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import DateTime, MetaData, Table, insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from pretest.services.errors import DiagnosticStorageError


class SqlDiagnosticRepository:
    backend_name = "postgresql"

    def __init__(self, engine):
        self.engine = engine
        self.table = Table("diagnostic_attempts", MetaData(), autoload_with=engine)
        required = {"id", "user_id", "status", "started_at", "submitted_at", "created_at", "updated_at",
                    "questions_snapshot", "submission_key", "answers", "summary", "domain_scores",
                    "question_results", "vulnerabilities", "llm_report", "report", "error"}
        if not required <= set(self.table.c.keys()):
            raise RuntimeError("사전테스트 diagnostic_attempts 스키마를 먼저 적용하세요.")

    def _values(self, values):
        result = dict(values)
        for key, value in result.items():
            if isinstance(self.table.c[key].type, DateTime) and isinstance(value, str):
                result[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result

    @staticmethod
    def _record(row):
        if row is None:
            return None
        result = dict(row)
        for key, value in result.items():
            if isinstance(value, UUID):
                result[key] = str(value)
            elif isinstance(value, datetime):
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                result[key] = value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return result

    def create_attempt(self, record):
        try:
            with self.engine.begin() as connection:
                row = connection.execute(insert(self.table).values(**self._values(record))
                                         .returning(self.table)).mappings().one()
                return self._record(row)
        except SQLAlchemyError as exc:
            raise DiagnosticStorageError("사전테스트 저장에 실패했습니다.") from exc

    def get_attempt(self, attempt_id, user_id):
        try:
            UUID(str(attempt_id))
        except (ValueError, TypeError, AttributeError):
            return None
        return self._get(select(self.table).where(self.table.c.id == attempt_id, self.table.c.user_id == user_id))

    def get_latest_attempt(self, user_id):
        return self._get(select(self.table).where(self.table.c.user_id == user_id)
                         .order_by(self.table.c.started_at.desc(), self.table.c.id.desc()).limit(1))

    def _get(self, query):
        try:
            with self.engine.connect() as connection:
                return self._record(connection.execute(query).mappings().first())
        except SQLAlchemyError as exc:
            raise DiagnosticStorageError("사전테스트 조회에 실패했습니다.") from exc

    def update_attempt(self, attempt_id, user_id, expected_status, changes):
        query = update(self.table).where(self.table.c.id == attempt_id,
            self.table.c.user_id == user_id, self.table.c.status == expected_status).values(**self._values(changes))
        try:
            with self.engine.begin() as connection:
                return self._record(connection.execute(query.returning(self.table)).mappings().first())
        except SQLAlchemyError as exc:
            raise DiagnosticStorageError("사전테스트 갱신에 실패했습니다.") from exc
