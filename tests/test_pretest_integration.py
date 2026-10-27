from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import JSON, Column, DateTime, MetaData, String, Table, create_engine
from sqlalchemy.pool import StaticPool

import run_integration as integration
from pretest.database.sql_repository import SqlDiagnosticRepository
from pretest.services.diagnostic_service import DiagnosticService
from pretest.services.question_bank import load_questions
from server_auth import get_verified_user_id


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LLM_REPORT_MODE", "local")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    metadata = MetaData()
    Table("diagnostic_attempts", metadata,
          Column("id", String, primary_key=True), Column("user_id", String), Column("status", String),
          Column("submission_key", String),
          *(Column(name, DateTime(timezone=True)) for name in ("started_at", "submitted_at", "created_at", "updated_at")),
          *(Column(name, JSON) for name in ("answers", "questions_snapshot", "summary", "domain_scores",
                                         "question_results", "vulnerabilities", "llm_report", "report", "error")))
    metadata.create_all(engine)
    app = integration.create_app()
    app.state.pretest_service = DiagnosticService(load_questions(), SqlDiagnosticRepository(engine))
    app.dependency_overrides[integration.pretest_user_id] = lambda: "user-a"
    result = TestClient(app)
    result.app_under_test = app
    yield result
    result.close()
    engine.dispose()


def test_signup_pending_submit_report_and_relogin_with_real_repository(client):
    assert client.get("/diagnostics/current").json()["requires_test"]
    started = client.post("/diagnostics")
    assert started.status_code == 201
    body = started.json()
    assert body["total_questions"] == 24
    assert all("answer" not in q and "concept" not in q for q in body["questions"])
    current = client.get("/diagnostics/current").json()
    assert current["diagnostic_id"] == body["id"] and len(current["questions"]) == 24
    answers = [{"question_id": q["id"], "selected_answer": q["answer"]} for q in load_questions()]
    submitted = client.post(f"/diagnostics/{body['id']}/submit", json={"answers": answers},
                            headers={"Idempotency-Key": "test-submit"})
    assert submitted.status_code == 202
    report = client.get(f"/reports/{body['id']}").json()
    assert report["status"] == "completed" and report["summary"]["score"] == 100
    assert len(report["domain_scores"]) == 4 and report["llm_report"]
    current = client.get("/diagnostics/current").json()
    assert not current["requires_test"] and current["report_id"] == body["id"]
    assert current["questions"] == []
    replay = client.post(f"/diagnostics/{body['id']}/submit", json={"answers": answers},
                         headers={"Idempotency-Key": "test-submit"})
    assert replay.status_code == 200


def test_auth_ownership_and_shared_error_contract(client):
    app = client.app_under_test
    attempt = client.post("/diagnostics").json()["id"]
    invalid = client.post(f"/diagnostics/{attempt}/submit", json={"answers": []},
                          headers={"Idempotency-Key": "invalid"})
    assert invalid.status_code == 422
    assert set(invalid.json()) == {"code", "message", "request_id"}
    app.dependency_overrides[integration.pretest_user_id] = lambda: "user-b"
    assert client.get("/diagnostics/current").json()["diagnostic_id"] is None
    assert client.get(f"/reports/{attempt}").status_code == 404
    assert client.get("/reports/not-a-uuid").status_code == 404
    app.dependency_overrides[integration.pretest_user_id] = get_verified_user_id
    assert client.get("/diagnostics/current").status_code == 401


def test_disabled_pretest_does_not_fall_back_to_memory(client):
    client.app_under_test.state.pretest_service = None
    assert client.post("/diagnostics").status_code == 503
