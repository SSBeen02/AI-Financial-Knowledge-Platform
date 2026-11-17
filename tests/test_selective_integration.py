"""선택 통합으로 추가된 사전테스트 계약을 로컬 저장소로 검증한다."""
import pytest

from pretest.database.repository import InMemoryDiagnosticRepository
from pretest.services.diagnostic_service import DiagnosticService
from pretest.services.errors import ReportRetryLimitError
from pretest.services.question_bank import load_questions
from pretest.services.domains import STAGE_DOMAINS, domain_label
from pretest.services.grading import grade_attempt
from pretest.schemas.diagnostic import SubmitRequest


def test_start_reuses_first_attempt_and_restores_question_snapshot():
    service = DiagnosticService(load_questions(), InMemoryDiagnosticRepository())
    first = service.start("local-user")
    resumed = service.start("local-user")
    assert first.id == resumed.id
    assert first.resumed is False and resumed.resumed is True
    assert [q.id for q in first.questions] == [q.id for q in resumed.questions]
    assert resumed.report_id is None
    expected = [domain for domain in STAGE_DOMAINS for _ in range(6)]
    assert [q.domain for q in first.questions] == expected
    assert [q.domain for q in resumed.questions] == expected
    assert [q.domain for q in service.current("local-user").questions] == expected


def test_diagnostic_api_order_and_official_result_report_labels():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pretest.dependencies import get_current_user_id
    from pretest.routers.diagnostics import router
    from pretest.services.diagnostic_service import get_diagnostic_service

    questions = load_questions()
    repository = InMemoryDiagnosticRepository()
    service = DiagnosticService(questions, repository)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_id] = lambda: "local-user"
    app.dependency_overrides[get_diagnostic_service] = lambda: service
    with TestClient(app) as client:
        first = client.post("/diagnostics")
        resumed = client.post("/diagnostics")
    assert first.status_code == 201 and resumed.status_code == 200
    assert first.json()["questions"] == resumed.json()["questions"]
    assert [q["domain"] for q in first.json()["questions"]] == [d for d in STAGE_DOMAINS for _ in range(6)]
    for question in first.json()["questions"]:
        assert question["domain_label"] == domain_label(question["domain"])

    answers = [{"question_id": q["id"], "selected_answer": q["answer"]} for q in questions]
    result, _ = service.submit(first.json()["id"], "local-user", SubmitRequest(answers=answers), "local-key")
    for row in result.domain_scores:
        assert row.domain_label == domain_label(row.domain)
    for row in result.question_results:
        assert row.domain_label == domain_label(row.domain)

    # Old stored grading data must also display the official names on retrieval.
    legacy = grade_attempt(questions, {q["id"]: q["answer"] for q in questions})
    for row in legacy["domain_scores"]:
        if row["domain"] == "finance_investment":
            row["domain_label"] = "금융·투자"
    repository.update_attempt(result.id, "local-user", "processing", dict(legacy, status="completed"))
    report = service.get_report(result.id, "local-user")
    for row in report.domain_scores:
        assert row.domain_label == domain_label(row.domain)


def test_report_retry_preserves_grading_and_limits_generations():
    repository = InMemoryDiagnosticRepository()
    service = DiagnosticService(load_questions(), repository)
    attempt = service.start("local-user")
    repository.update_attempt(attempt.id, "local-user", "pending", {
        "status": "failed", "summary": {"score": 50}, "submitted_at": attempt.started_at,
    })
    for count in range(1, 4):
        assert service.prepare_report_retry(attempt.id, "local-user") is True
        current = repository.get_attempt(attempt.id, "local-user")
        assert current["retry_count"] == count
        assert current["summary"]["score"] == 50
        repository.update_attempt(attempt.id, "local-user", "processing", {"status": "failed"})
    with pytest.raises(ReportRetryLimitError):
        service.prepare_report_retry(attempt.id, "local-user")
