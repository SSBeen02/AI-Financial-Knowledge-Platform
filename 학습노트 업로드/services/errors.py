class DiagnosticError(Exception):
    """사전테스트 처리 중 발생하는 도메인 오류."""


class AuthenticationRequiredError(DiagnosticError):
    pass


class IdempotencyConflictError(DiagnosticError):
    pass


class DiagnosticNotFoundError(DiagnosticError):
    pass


class DiagnosticAlreadySubmittedError(DiagnosticError):
    pass


class InvalidAnswersError(DiagnosticError):
    def __init__(self, detail: dict):
        self.detail = detail
        super().__init__(detail.get("message", "답안이 올바르지 않습니다."))


class ReportNotFoundError(DiagnosticError):
    def __init__(self, message: str = "리포트를 찾을 수 없습니다."):
        self.message = message
        super().__init__(message)


class LlmReportError(DiagnosticError):
    def __init__(self, message: str = "맞춤 리포트를 생성하지 못했습니다."):
        self.message = message
        super().__init__(message)


class DiagnosticStorageError(DiagnosticError):
    def __init__(
        self,
        message: str = (
            "진단 결과를 저장하지 못했습니다. "
            "Supabase URL, service role 키, diagnostic_attempts 테이블을 확인해 주세요."
        ),
    ):
        self.message = message
        super().__init__(message)
