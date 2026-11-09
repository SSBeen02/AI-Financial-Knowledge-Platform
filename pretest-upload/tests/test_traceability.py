"""추적표의 문제은행·채점 경계·소유자 격리·이전 결과 표시 검증."""
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ["DEV_MODE"] = "true"
os.environ["DIAGNOSTIC_REPOSITORY"] = "memory"
os.environ["LLM_REPORT_MODE"] = "local"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from database.repository import InMemoryDiagnosticRepository
from dependencies import get_current_user_id
from schemas.diagnostic import SubmitRequest
from services.diagnostic_service import DiagnosticService
from services.domains import level_for
from services.errors import LlmReportError
from services.grading import grade_attempt
from services.question_bank import QuestionBankError, _read_questions, load_questions


class QuestionContractTest(unittest.TestCase):
    def read(self, questions):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "questions.json"
            path.write_text(json.dumps({"questions": questions}), encoding="utf-8")
            return _read_questions(path)

    def test_imported_bank_rejects_contract_violations(self):
        original = load_questions()
        cases = []
        cases.append(original[:-1])
        extra = copy.deepcopy(original)
        extra.append(dict(extra[0], id="additional-question", concept="additional-concept"))
        cases.append(extra)
        for field, value in (
            ("domain", "unknown_domain"),
            ("domain", original[6]["domain"]),
            ("options", ["a", "b", "c"]),
            ("options", ["a", "b", "c", "d", "e"]),
            ("options", ["a", "b", "c", "   "]),
            ("concept", original[1]["concept"]),
            ("answer", True),
            ("answer", 5),
            ("explanation", {"correct": "explanation", "options_detail": ["one"]}),
        ):
            changed = copy.deepcopy(original)
            changed[0][field] = value
            cases.append(changed)
        for index, questions in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(QuestionBankError):
                self.read(questions)

    def test_json_export_import_preserves_questions(self):
        questions = load_questions()
        self.assertEqual(self.read(questions), questions)


class TraceabilityServiceTest(unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryDiagnosticRepository()
        self.questions = copy.deepcopy(load_questions())
        self.service = DiagnosticService(self.questions, self.repo)

    def test_other_user_cannot_get_submit_or_retry(self):
        # 실제 사전테스트 라우터만 사용해 다른 모듈의 DB 초기화를 피한다.
        from routers.diagnostics import router as diagnostics_router
        from routers.reports import router as reports_router
        from routers.errors import register_pretest_exception_handlers
        app = FastAPI()
        app.include_router(diagnostics_router)
        app.include_router(reports_router)
        register_pretest_exception_handlers(app)
        started = self.service.start("owner")
        payload = {"answers": [{"question_id": q["id"], "selected_answer": q["answer"]} for q in self.questions]}
        before = self.repo.get_attempt(started.id, "owner")
        original_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user_id] = lambda: "other-user"
        try:
            with patch("routers.diagnostics.get_diagnostic_service", return_value=self.service), patch("routers.reports.get_diagnostic_service", return_value=self.service), TestClient(app) as client:
                responses = [
                    client.get(f"/reports/{started.id}"),
                    client.post(f"/diagnostics/{started.id}/submit", json=payload, headers={"Idempotency-Key": "other"}),
                    client.post(f"/reports/{started.id}/retry"),
                ]
            self.assertEqual([response.status_code for response in responses], [404, 404, 404])
            self.assertEqual(self.repo.get_attempt(started.id, "owner"), before)
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(original_overrides)

    def test_grade_level_and_vulnerability_boundaries(self):
        for score, expected in [(59.9, "보완필요"), (60, "보통"), (74.9, "보통"), (75, "양호"), (89.9, "양호"), (90, "우수")]:
            with self.subTest(score=score):
                self.assertEqual(level_for(score), expected)
        questions = [dict(copy.deepcopy(self.questions[0]), id=f"q-{i}") for i in range(100)]
        correct = questions[0]["answer"]
        wrong = correct % 4 + 1
        for count, vulnerable, severity in [(49, True, "high"), (50, True, "medium"), (69, True, "medium"), (70, False, None)]:
            with self.subTest(correct=count):
                result = grade_attempt(questions, {q["id"]: correct if i < count else wrong for i, q in enumerate(questions)})
                self.assertEqual(result["domain_scores"][0]["is_vulnerable"], vulnerable)
                self.assertEqual(result["vulnerabilities"][0]["severity"] if vulnerable else None, severity)

    def test_report_failure_preserves_all_grades(self):
        started = self.service.start("owner")
        payload = SubmitRequest(answers=[{"question_id": q["id"], "selected_answer": q["answer"] if i % 2 else q["answer"] % 4 + 1} for i, q in enumerate(self.questions)])
        self.service.submit(started.id, "owner", payload, "key")
        before = self.repo.get_attempt(started.id, "owner")
        with patch("services.diagnostic_service.generate_llm_report", side_effect=LlmReportError()):
            self.service.generate_report(started.id, "owner")
        after = self.repo.get_attempt(started.id, "owner")
        for field in ("answers", "questions_snapshot", "summary", "domain_scores", "question_results", "vulnerabilities"):
            self.assertEqual(after[field], before[field], field)
        report = self.service.get_report(started.id, "owner")
        self.assertEqual(report.status, "failed")
        self.assertIsNone(report.llm_report)

    def test_completion_at_deadline_is_failed(self):
        started = self.service.start("owner")
        payload = SubmitRequest(answers=[{"question_id": q["id"], "selected_answer": q["answer"]} for q in self.questions])
        self.service.submit(started.id, "owner", payload, "key")
        row = self.repo.get_attempt(started.id, "owner")
        began = datetime.fromisoformat(row["submitted_at"].replace("Z", "+00:00"))
        deadline = began + timedelta(seconds=30)
        with patch("services.diagnostic_service.datetime", wraps=datetime) as clock:
            clock.now.side_effect = [began, deadline, deadline]
            self.service.generate_report(started.id, "owner")
        report = self.service.get_report(started.id, "owner")
        self.assertEqual(report.status, "failed")
        self.assertEqual(report.error.code, "REPORT_GENERATION_TIMEOUT")
        self.assertEqual(report.summary.score, 100)
        self.assertIsNone(report.llm_report)


if __name__ == "__main__":
    unittest.main()
