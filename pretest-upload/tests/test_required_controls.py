"""최초 1회 응시, 재생성 제한, 투자 권유 출력 차단 회귀 검증."""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from unittest.mock import MagicMock

from database.repository import InMemoryDiagnosticRepository, SupabaseDiagnosticRepository
from schemas.diagnostic import SubmitRequest
from services.diagnostic_service import DiagnosticService, REPORT_RETRY_LIMIT
from services.errors import ReportRetryLimitError, LlmReportError
from services.llm_report import generate_local_report
from services.question_bank import load_questions
from services.report_safety import validate_report_safety
from services.report_language import validate_report_language


class RequiredControlsTest(unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryDiagnosticRepository()
        self.service = DiagnosticService(load_questions(), self.repo)

    def submit(self, user="owner"):
        attempt = self.service.start(user)
        questions = load_questions()
        payload = SubmitRequest(answers=[{"question_id": q["id"], "selected_answer": q["answer"]} for q in questions])
        self.service.submit(attempt.id, user, payload, "key")
        return attempt.id

    def test_parallel_starts_reuse_one_attempt_across_services(self):
        services = [DiagnosticService(load_questions(), self.repo) for _ in range(8)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            attempts = list(pool.map(lambda service: service.start("owner"), services))
        self.assertEqual(len({a.id for a in attempts}), 1)
        self.assertEqual(sum(not a.resumed for a in attempts), 1)
        self.assertNotEqual(self.service.start("other").id, attempts[0].id)

    def test_submitted_user_cannot_create_new_attempt(self):
        attempt_id = self.submit()
        current = self.service.start("owner")
        self.assertEqual(current.id, attempt_id)
        self.assertEqual(current.report_id, attempt_id)
        self.assertEqual(current.status, "processing")
        self.assertTrue(current.resumed)

    def test_legacy_duplicate_pending_cannot_bypass_submitted_attempt(self):
        pending = self.service.start("owner")
        legacy = self.repo.get_attempt(pending.id, "owner")
        legacy.update(id="legacy-submitted", status="completed")
        self.repo.create_attempt(legacy)
        resumed = self.service.start("owner")
        self.assertEqual(resumed.id, "legacy-submitted")
        self.assertEqual(resumed.status, "completed")

    def test_retry_limit_and_grade_preservation(self):
        attempt_id = self.submit()
        before = self.repo.get_attempt(attempt_id, "owner")
        for count in range(REPORT_RETRY_LIMIT):
            self.service._fail(attempt_id, "owner", "TEST", "failure")
            self.assertTrue(self.service.prepare_report_retry(attempt_id, "owner"))
            self.assertEqual(self.repo.get_attempt(attempt_id, "owner")["retry_count"], count + 1)
            self.assertFalse(self.service.prepare_report_retry(attempt_id, "owner"))
        self.service._fail(attempt_id, "owner", "TEST", "failure")
        with self.assertRaises(ReportRetryLimitError):
            self.service.prepare_report_retry(attempt_id, "owner")
        self.assertEqual(self.service.get_report(attempt_id, "owner").summary.model_dump(), before["summary"])

    def test_parallel_retries_register_one_job(self):
        attempt_id = self.submit()
        self.service._fail(attempt_id, "owner", "TEST", "failure")
        with ThreadPoolExecutor(max_workers=8) as pool:
            jobs = list(pool.map(lambda _: self.service.prepare_report_retry(attempt_id, "owner"), range(8)))
        self.assertEqual(sum(jobs), 1)
        self.assertEqual(self.repo.get_attempt(attempt_id, "owner")["retry_count"], 1)

    def test_retry_preserves_submission_time_and_rejects_old_generation_write(self):
        attempt_id = self.submit()
        original = self.repo.get_attempt(attempt_id, "owner")["submitted_at"]
        self.service._fail(attempt_id, "owner", "TEST", "failure")
        self.service.prepare_report_retry(attempt_id, "owner")
        self.assertIsNone(self.repo.update_attempt(attempt_id, "owner", "processing", {"status": "completed"}, 0))
        self.assertEqual(self.repo.get_attempt(attempt_id, "owner")["status"], "processing")
        self.assertEqual(self.repo.get_attempt(attempt_id, "owner")["submitted_at"], original)

    def test_unsafe_generation_fails_without_losing_grades(self):
        attempt_id = self.submit()
        row = self.repo.get_attempt(attempt_id, "owner")
        report = generate_local_report(row)
        report.level_diagnosis.summary = "이 주식을 매수하시오."
        with patch("services.diagnostic_service.generate_llm_report", return_value=report):
            self.service.generate_report(attempt_id, "owner")
        result = self.service.get_report(attempt_id, "owner")
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.summary.score, 100)
        self.assertIsNone(result.llm_report)
        self.assertEqual(result.disclaimer, "AI 작성, 투자 조언 아님")

    def test_education_and_prohibitions_are_not_investment_advice(self):
        attempt_id = self.submit()
        report = generate_local_report(self.repo.get_attempt(attempt_id, "owner"))
        for text in ["복리는 이자에 이자가 붙는 방식이오.", "투자를 권유하지 않소.", "수익을 보장하지 않소."]:
            report.level_diagnosis.summary = text
            validate_report_safety(report)
        for text in ["이 펀드에 가입하세요.", "이 주식을 매수하시오.", "수익을 보장하오.", "You should buy this stock."]:
            report.level_diagnosis.summary = text
            with self.subTest(text=text), self.assertRaises(LlmReportError):
                validate_report_safety(report)

    def test_supabase_start_uses_atomic_rpc_and_does_not_fallback_to_insert(self):
        client = MagicMock()
        row = {"id": "one", "user_id": "owner", "status": "pending"}
        client.rpc.return_value.execute.return_value.data = [row]
        with patch("database.repository.create_supabase_client", return_value=client):
            repo = SupabaseDiagnosticRepository("https://example.invalid", "fake-key")
            self.assertEqual(repo.start_once(row), row)
        client.rpc.assert_called_once_with("start_diagnostic_once", {"p_record": row})
        client.table.assert_not_called()

    def test_supabase_write_guards_owner_status_and_generation(self):
        client = MagicMock()
        query = client.table.return_value.update.return_value
        query.eq.return_value = query
        query.execute.return_value.data = []
        with patch("database.repository.create_supabase_client", return_value=client):
            repo = SupabaseDiagnosticRepository("https://example.invalid", "fake-key")
            self.assertIsNone(repo.update_attempt("id", "owner", "processing", {"status": "completed"}, 2))
        self.assertEqual([call.args for call in query.eq.call_args_list], [("id", "id"), ("user_id", "owner"), ("status", "processing"), ("retry_count", 2)])

    def test_start_and_retry_http_contract(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from dependencies import get_current_user_id
        from routers.diagnostics import router as diagnostics
        from routers.reports import router as reports
        from routers.errors import register_pretest_exception_handlers
        app = FastAPI()
        app.include_router(diagnostics)
        app.include_router(reports)
        register_pretest_exception_handlers(app)
        app.dependency_overrides[get_current_user_id] = lambda: "owner"
        with patch("routers.diagnostics.get_diagnostic_service", return_value=self.service), patch("routers.reports.get_diagnostic_service", return_value=self.service), TestClient(app) as client:
            first = client.post("/diagnostics")
            second = client.post("/diagnostics")
            self.assertEqual((first.status_code, second.status_code), (201, 200))
            self.assertEqual(first.json()["id"], second.json()["id"])
            attempt_id = self.submit()
            self.service._fail(attempt_id, "owner", "TEST", "failure")
            self.repo.update_attempt(attempt_id, "owner", "failed", {"retry_count": 3})
            response = client.post(f"/reports/{attempt_id}/retry")
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.json()["code"], "REPORT_RETRY_LIMIT_EXCEEDED")

    def test_local_fallback_uses_haoche_for_every_case(self):
        import re
        from services.grading import grade_attempt
        questions = load_questions()
        for case in ("perfect", "partial", "all_wrong"):
            answers = {q["id"]: q["answer"] if case == "perfect" or (case == "partial" and i % 2 == 0) else q["answer"] % 4 + 1 for i, q in enumerate(questions)}
            report = generate_local_report(grade_attempt(questions, answers))
            validate_report_language(report)
            narrative = [report.level_diagnosis.summary, report.wrong_answer_analysis.summary]
            narrative += [x.diagnosis for x in report.level_diagnosis.domain_comments]
            narrative += [x.vulnerability for x in report.wrong_answer_analysis.items]
            narrative += [x.guide for x in report.recommendations]
            for text in narrative:
                with self.subTest(case=case, text=text):
                    self.assertIsNone(re.search(r"습니다|합니다|하세요", text))

    def test_foreign_report_text_is_rejected_before_storage(self):
        attempt_id = self.submit()
        graded = self.repo.get_attempt(attempt_id, "owner")
        report = generate_local_report(graded)
        for text in ("경제를 복습하시오. Review the concept.", "경제를 복습하시오。経済を復習する。", "GDP를 확인하시오. 经济分析。", "경제를 복습하시오. Ｒｅｖｉｅｗ"):
            with self.subTest(text=text):
                report.recommendations[0].guide = text
                with self.assertRaises(LlmReportError):
                    validate_report_language(report)
        with patch("services.diagnostic_service.generate_llm_report", return_value=report):
            self.service.generate_report(attempt_id, "owner")
        response = self.service.get_report(attempt_id, "owner")
        self.assertEqual(response.status, "failed")
        self.assertIsNone(response.llm_report)
        self.assertEqual(response.summary.score, 100)


if __name__ == "__main__":
    unittest.main()
