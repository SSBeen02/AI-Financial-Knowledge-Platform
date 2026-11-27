"""PT-IR-03/PT-QR-01: provider routing and failure recovery without live services."""
import copy
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ["DEV_MODE"] = "true"
os.environ["DIAGNOSTIC_REPOSITORY"] = "memory"
os.environ["LLM_REPORT_MODE"] = "local"

from fastapi.testclient import TestClient
from pretest.database.repository import InMemoryDiagnosticRepository
from pretest.main import app
from pretest.services.diagnostic_service import DiagnosticService, get_diagnostic_service
from pretest.services.errors import LlmReportError
from pretest.services.grading import grade_attempt
from pretest.services.llm_report import generate_llm_report, generate_local_report
from pretest.services.question_bank import load_questions
from pretest.services.report_parallel import ReportDeadlineError
from pretest.services.report_summary import REPORT_STAGE_ORDER


def provider_settings(mode):
    return SimpleNamespace(llm_report_mode=mode, openai_api_key="fixture-openai",
                           openai_model="fixture-openai-model")


def local_generation(graded, **kwargs):
    return generate_local_report(graded)


class ProviderFollowupTests(unittest.TestCase):
    def setUp(self):
        questions = load_questions()
        self.graded = grade_attempt(questions, {q["id"]: q["answer"] for q in questions})

    def test_openai_modes_honor_remaining_budget_without_sdk_retry(self):
        expected = generate_local_report(self.graded)
        for mode in ("auto", "openai"):
            for budget in (2.5, 28.0, 60.0):
                with self.subTest(provider=mode, budget=budget):
                    with patch("pretest.services.llm_report.load_settings", return_value=provider_settings(mode)), \
                         patch("openai.OpenAI") as sdk, \
                         patch("pretest.services.llm_report.generate_openai_report", return_value=expected) as single, \
                         patch("pretest.services.report_parallel.generate_parallel_report", return_value=expected) as parallel:
                        self.assertEqual(generate_llm_report(self.graded, budget=budget), expected)
                    self.assertEqual(sdk.call_args.kwargs["timeout"], min(budget, 28.0))
                    self.assertEqual(sdk.call_args.kwargs["max_retries"], 0)
                    parallel.assert_called_once()
                    single.assert_not_called()

    def test_missing_provider_credentials_fail_without_network(self):
        settings = provider_settings("openai")
        settings.openai_api_key = None
        with patch("pretest.services.llm_report.load_settings", return_value=settings), \
             patch("openai.OpenAI") as sdk:
            with self.assertRaises(LlmReportError):
                generate_llm_report(self.graded)
            sdk.assert_not_called()

    def test_openai_failure_reaches_service_error_boundary(self):
        for mode in ("auto", "openai"):
            with self.subTest(provider=mode), \
                 patch("pretest.services.llm_report.load_settings", return_value=provider_settings(mode)), \
                 patch("openai.OpenAI", return_value=MagicMock()), \
                 patch("pretest.services.llm_report.generate_openai_report", side_effect=LlmReportError("fixture")), \
                 patch("pretest.services.report_parallel.generate_parallel_report", side_effect=LlmReportError("fixture")):
                with self.assertRaises(LlmReportError):
                    generate_llm_report(self.graded)

    def test_obsolete_provider_key_cannot_select_removed_provider(self):
        from pretest.database.settings import load_settings
        from pretest.services.llm_report import _resolved_mode
        with patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "true", "LLM_REPORT_MODE": "auto",
                                     "OPENAI_API_KEY": "", "GEMINI_API_KEY": "obsolete-fixture"}):
            self.assertEqual(_resolved_mode(load_settings()), "local")

    def test_integrated_runtime_rejects_non_openai_modes_before_db_connection(self):
        from pretest.integration import prepare_pretest_runtime
        for mode in ("gemini", "local", "auto"):
            with self.subTest(mode=mode), patch.dict(os.environ, {
                "PRETEST_ENABLED": "true", "LLM_REPORT_MODE": mode,
                "CHAT_DB_URL": "postgresql+psycopg://fixture:fixture@localhost/fixture",
                "OPENAI_API_KEY": "fixture-only",
            }), patch("pretest.integration.create_engine") as engine:
                with self.assertRaisesRegex(RuntimeError, "openai"):
                    prepare_pretest_runtime()
                engine.assert_not_called()


class ReportRecoveryFollowupTests(unittest.TestCase):
    def setUp(self):
        self.questions = copy.deepcopy(load_questions())
        self.repo = InMemoryDiagnosticRepository()
        self.service = DiagnosticService(self.questions, self.repo)
        override = patch.dict(app.dependency_overrides, {get_diagnostic_service: lambda: self.service})
        override.start()
        self.addCleanup(override.stop)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.answers = [{"question_id": q["id"], "selected_answer": q["answer"]} for q in self.questions]

    def test_provider_errors_and_timeout_recover_via_same_report_retry_api(self):
        for failure in (LlmReportError("fixture"), ReportDeadlineError("fixture"), RuntimeError("fixture")):
            with self.subTest(failure=type(failure).__name__):
                # Fresh local data models a new account without changing deployed records.
                self.repo = InMemoryDiagnosticRepository()
                self.service = DiagnosticService(self.questions, self.repo)
                report_id = self.client.post("/diagnostics").json()["id"]
                with patch("pretest.services.diagnostic_service.generate_llm_report", side_effect=failure):
                    submitted = self.client.post(f"/diagnostics/{report_id}/submit",
                        json={"answers": self.answers}, headers={"Idempotency-Key": "fixture-submit"})
                self.assertEqual(submitted.status_code, 202)
                failed = self.client.get(f"/reports/{report_id}").json()
                self.assertEqual(failed["status"], "failed")
                expected_code = "REPORT_GENERATION_TIMEOUT" if isinstance(failure, ReportDeadlineError) else "REPORT_GENERATION_FAILED"
                self.assertEqual(failed["error"]["code"], expected_code)
                with patch("pretest.services.diagnostic_service.generate_llm_report", side_effect=local_generation):
                    retry = self.client.post(f"/reports/{report_id}/retry")
                self.assertEqual(retry.status_code, 202)
                recovered = self.client.get(f"/reports/{report_id}").json()
                self.assertEqual((recovered["id"], recovered["status"], recovered["retry_count"]),
                                 (report_id, "completed", 1))
                self.assertIn("llm_report", recovered)
                self.assertNotIn("error", recovered)
                for field in ("summary", "question_results", "domain_scores"):
                    self.assertEqual(recovered[field], failed[field])
                self.assertEqual(len(self.repo._rows), 1)

    def test_elapsed_job_is_failed_by_lookup_and_retry_recovers(self):
        from pretest.schemas.diagnostic import SubmitRequest
        started = self.service.start("fixture-user")
        self.service.submit(started.id, "fixture-user", SubmitRequest(answers=self.answers), "fixture-key")
        expired = (datetime.now(timezone.utc) - timedelta(seconds=31)).isoformat()
        self.repo.update_attempt(started.id, "fixture-user", "processing", {"report_started_at": expired})
        failed = self.service.get_report(started.id, "fixture-user")
        self.assertEqual((failed.status, failed.error.code), ("failed", "REPORT_GENERATION_TIMEOUT"))
        self.assertTrue(self.service.prepare_report_retry(started.id, "fixture-user"))
        with patch("pretest.services.diagnostic_service.generate_llm_report", side_effect=local_generation):
            self.service.generate_report(started.id, "fixture-user")
        recovered = self.service.get_report(started.id, "fixture-user")
        self.assertEqual(recovered.status, "completed")
        self.assertEqual(recovered.summary, failed.summary)

    def test_wrong_answer_domains_match_grading_and_resolve_to_stages_1_to_4(self):
        report_id = self.client.post("/diagnostics").json()["id"]
        wrong = [{"question_id": q["id"], "selected_answer": q["answer"] % 4 + 1} for q in self.questions]
        with patch("pretest.services.diagnostic_service.generate_llm_report", side_effect=local_generation):
            self.client.post(f"/diagnostics/{report_id}/submit", json={"answers": wrong},
                             headers={"Idempotency-Key": "fixture-all-wrong"})
        result = self.client.get(f"/reports/{report_id}").json()
        self.assertEqual(result["status"], "completed")
        originals = {q["question_id"]: q for q in result["question_results"]}
        observed = set()
        for item in result["llm_report"]["wrong_answer_analysis"]["items"]:
            self.assertEqual(item["domain"], originals[item["question_id"]]["domain"])
            observed.add(REPORT_STAGE_ORDER[item["domain"]])
        self.assertEqual(observed, {1, 2, 3, 4})
