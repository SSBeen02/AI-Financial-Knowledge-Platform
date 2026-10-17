import copy
import json
import logging
import threading
from typing import Protocol

from database.settings import load_settings
from database.supabase import create_supabase_client
from services.errors import DiagnosticStorageError

logger = logging.getLogger("diagnostics")

JSON_COLUMNS = (
    "answers",
    "questions_snapshot",
    "error",
    "summary",
    "domain_scores",
    "question_results",
    "vulnerabilities",
    "llm_report",
    "report",
)

_repository: "DiagnosticRepository | None" = None
_repository_lock = threading.Lock()


class DiagnosticRepository(Protocol):
    backend_name: str

    def create_attempt(self, record: dict) -> dict: ...

    def get_attempt(self, attempt_id: str, user_id: str) -> dict | None: ...

    def update_attempt(
        self, attempt_id: str, user_id: str, expected_status: str, changes: dict
    ) -> dict | None: ...


class InMemoryDiagnosticRepository:
    """프로세스가 살아있는 동안만 유지되는 저장소. Supabase 키 없이 로컬에서 실행할 때 사용합니다."""

    backend_name = "memory"

    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create_attempt(self, record: dict) -> dict:
        with self._lock:
            attempt_id = record["id"]
            if attempt_id in self._rows:
                raise DiagnosticStorageError("같은 진단 id가 이미 있습니다.")
            self._rows[attempt_id] = copy.deepcopy(record)
            return copy.deepcopy(self._rows[attempt_id])

    def get_attempt(self, attempt_id: str, user_id: str) -> dict | None:
        with self._lock:
            row = self._rows.get(attempt_id)
            if row is None or row["user_id"] != user_id:
                return None
            return copy.deepcopy(row)

    def update_attempt(
        self, attempt_id: str, user_id: str, expected_status: str, changes: dict
    ) -> dict | None:
        with self._lock:
            row = self._rows.get(attempt_id)
            if row is None or row["user_id"] != user_id or row["status"] != expected_status:
                return None
            row.update(copy.deepcopy(changes))
            return copy.deepcopy(row)


class SupabaseDiagnosticRepository:
    backend_name = "supabase"

    def __init__(self, url: str, key: str) -> None:
        self._client = create_supabase_client(url, key)

    def create_attempt(self, record: dict) -> dict:
        try:
            response = self._client.table("diagnostic_attempts").insert(record).execute()
        except Exception as exc:
            logger.exception("diagnostic_attempts insert 실패")
            raise DiagnosticStorageError() from exc
        rows = response.data or []
        if not rows:
            raise DiagnosticStorageError()
        return _coerce_row(rows[0])

    def get_attempt(self, attempt_id: str, user_id: str) -> dict | None:
        try:
            response = (
                self._client.table("diagnostic_attempts")
                .select("*")
                .eq("id", attempt_id)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            logger.exception("diagnostic_attempts 조회 실패")
            raise DiagnosticStorageError() from exc
        rows = response.data or []
        if not rows:
            return None
        return _coerce_row(rows[0])

    def update_attempt(
        self, attempt_id: str, user_id: str, expected_status: str, changes: dict
    ) -> dict | None:
        try:
            response = (
                self._client.table("diagnostic_attempts")
                .update(changes)
                .eq("id", attempt_id)
                .eq("user_id", user_id)
                .eq("status", expected_status)
                .execute()
            )
        except Exception as exc:
            logger.exception("diagnostic_attempts 갱신 실패")
            raise DiagnosticStorageError() from exc
        rows = response.data or []
        if not rows:
            return None
        return _coerce_row(rows[0])


def _coerce_row(row: dict) -> dict:
    coerced = dict(row)
    for key in JSON_COLUMNS:
        value = coerced.get(key)
        if isinstance(value, str):
            coerced[key] = json.loads(value)
    return coerced


def _build_repository() -> DiagnosticRepository:
    settings = load_settings()
    mode = settings.repository
    if mode not in {"auto", "memory", "supabase"}:
        raise RuntimeError("DIAGNOSTIC_REPOSITORY는 auto, memory, supabase 중 하나여야 합니다.")

    configured = bool(settings.supabase_url and settings.supabase_key)
    if mode == "supabase" and not configured:
        raise RuntimeError(
            "Supabase 저장소를 쓰려면 SUPABASE_URL과 SUPABASE_SERVICE_ROLE_KEY가 필요합니다."
        )

    use_supabase = mode == "supabase" or (mode == "auto" and configured)
    if use_supabase:
        if not settings.supabase_url or not settings.supabase_key:
            raise RuntimeError("Supabase 설정이 비어 있습니다.")
        logger.info("저장소: Supabase diagnostic_attempts")
        return SupabaseDiagnosticRepository(settings.supabase_url, settings.supabase_key)

    if mode == "auto":
        logger.warning(
            "저장소: 프로세스 메모리. SUPABASE_URL과 SUPABASE_SERVICE_ROLE_KEY를 설정하면 "
            "diagnostic_attempts 테이블에 저장합니다."
        )
    else:
        logger.info("저장소: 프로세스 메모리")
    return InMemoryDiagnosticRepository()


def get_repository() -> DiagnosticRepository:
    global _repository
    if _repository is not None:
        return _repository
    with _repository_lock:
        if _repository is None:
            _repository = _build_repository()
        return _repository
