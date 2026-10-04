import copy
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

os.environ["DEV_MODE"] = "true"
os.environ["DIAGNOSTIC_REPOSITORY"] = "memory"
os.environ["LLM_REPORT_MODE"] = "local"

from fastapi.testclient import TestClient
from main import app
from dependencies import get_current_user_id
from database.repository import InMemoryDiagnosticRepository
from schemas.diagnostic import SubmitRequest
from services.diagnostic_service import DiagnosticService
from services.errors import IdempotencyConflictError, ReportNotFoundError, DiagnosticStorageError
from services.question_bank import load_questions


class SubmissionFlowTest(unittest.TestCase):
    def setUp(self):
        self.questions = copy.deepcopy(load_questions())
        self.repo = InMemoryDiagnosticRepository()
        self.service = DiagnosticService(self.questions, self.repo)
        self.started = self.service.start("user-a")
        self.payload = SubmitRequest(answers=[
            {"question_id": q["id"], "selected_answer": q["answer"]} for q in self.questions
        ])

    def submit(self, key="key-a", payload=None):
        return self.service.submit(self.started.id, "user-a", payload or self.payload, key)

    def test_acceptance_saves_answers_before_generation(self):
        with patch("services.diagnostic_service.generate_llm_report") as generate:
            response, created = self.submit()
        self.assertTrue(created)
        self.assertEqual(response.status, "processing")
        generate.assert_not_called()
        row = self.repo.get_attempt(self.started.id, "user-a")
        self.assertEqual(len(row["answers"]), 24)
        self.assertEqual(row["summary"]["score"], 100)
        self.assertNotIn("questions_snapshot", self.service.get_report(self.started.id, "user-a").model_dump())

    def test_concurrent_same_submission_creates_one_job(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: self.submit(), range(4)))
        self.assertEqual(sum(created for _, created in results), 1)
        self.assertTrue(all(result.status == "processing" for result, _ in results))

    def test_key_and_answer_conflicts(self):
        self.submit()
        with self.assertRaises(IdempotencyConflictError):
            self.submit(key="other-key")
        changed = self.payload.model_copy(deep=True)
        changed.answers[0].selected_answer = 1
        with self.assertRaises(IdempotencyConflictError):
            self.submit(payload=changed)
        reordered = SubmitRequest(answers=list(reversed(self.payload.answers)))
        self.assertFalse(self.submit(payload=reordered)[1])

    def test_user_isolation(self):
        with self.assertRaises(ReportNotFoundError):
            self.service.get_report(self.started.id, "user-b")

    def test_original_question_version_is_used(self):
        self.service._questions[0]["answer"] = 1
        response, _ = self.submit()
        self.assertEqual(response.summary.score, 100)

    def test_unexpected_sdk_error_is_failed_and_grades_survive(self):
        self.submit()
        with patch("services.diagnostic_service.generate_llm_report", side_effect=RuntimeError("SDK setup failure")):
            self.service.generate_report(self.started.id, "user-a")
        report = self.service.get_report(self.started.id, "user-a")
        self.assertEqual(report.status, "failed")
        self.assertEqual(report.summary.score, 100)
        self.assertEqual(report.error.code, "REPORT_GENERATION_FAILED")
        self.assertFalse(self.submit()[1])

    def test_expired_job_is_failed_and_late_completion_cannot_overwrite(self):
        self.submit()
        old = (datetime.now(timezone.utc) - timedelta(seconds=301)).isoformat()
        self.repo.update_attempt(self.started.id, "user-a", "processing", {"submitted_at": old})
        report = self.service.get_report(self.started.id, "user-a")
        self.assertEqual(report.status, "failed")
        self.assertEqual(report.error.code, "REPORT_GENERATION_TIMEOUT")
        with patch("services.diagnostic_service.generate_llm_report") as generate:
            self.service.generate_report(self.started.id, "user-a")
        generate.assert_not_called()

    def test_completion_storage_failure_keeps_grades(self):
        self.submit()
        original = self.repo.update_attempt
        def update(*args):
            if args[3].get("status") == "completed":
                raise DiagnosticStorageError()
            return original(*args)
        with patch.object(self.repo, "update_attempt", side_effect=update):
            self.service.generate_report(self.started.id, "user-a")
        self.assertEqual(self.service.get_report(self.started.id, "user-a").status, "failed")


class AuthContractTest(unittest.TestCase):
    def test_dev_disabled_requires_login(self):
        with patch.dict(os.environ, {"DEV_MODE": "false"}), TestClient(app) as client:
            result = client.post("/diagnostics")
        self.assertEqual(result.status_code, 401)
        self.assertEqual(result.json()["code"], "AUTHENTICATION_REQUIRED")

    def test_common_auth_dependency_overrides_dummy(self):
        app.dependency_overrides[get_current_user_id] = lambda: "b209ca89-3d10-4d79-b16b-0b427c9c132d"
        try:
            with patch.dict(os.environ, {"DEV_MODE": "false"}), TestClient(app) as client:
                result = client.post("/diagnostics")
            self.assertEqual(result.status_code, 201)
            self.assertEqual(result.json()["user_id"], "b209ca89-3d10-4d79-b16b-0b427c9c132d")
        finally:
            app.dependency_overrides.pop(get_current_user_id, None)

    def test_submission_key_required(self):
        with TestClient(app) as client:
            started = client.post("/diagnostics").json()
            result = client.post(f"/diagnostics/{started['id']}/submit", json={"answers": [{"question_id": "a", "selected_answer": 1}]})
        self.assertEqual(result.status_code, 422)
        self.assertEqual(result.json()["code"], "VALIDATION_ERROR")
