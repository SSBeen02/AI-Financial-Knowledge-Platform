import json
import threading
import time
import unittest
from types import SimpleNamespace

from services.errors import LlmReportError
from services.grading import grade_attempt
from services.report_parallel import build_tasks, generate_parallel_report, ReportDeadlineError


def graded():
    rows = []
    for domain in ["finance_investment", "macroeconomy_monetary_fiscal_policy"]:
        rows.append({"id": domain + "_1", "domain": domain, "category": "sample", "difficulty": 1, "concept": domain + " concept", "question": "sample clue", "options": ["a", "b", "c", "d"], "answer": 1, "explanation": {"correct": "same evidence", "options_detail": ["same evidence", "selected evidence", "unused c", "unused d"]}})
    return grade_attempt(rows, {q["id"]: 2 for q in rows})


class FakeClient:
    def __init__(self, *, barrier=None, delay=0, bad_ids=False):
        self.barrier = barrier
        self.delay = delay
        self.bad_ids = bad_ids
        self.beta = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=self.parse)))

    def parse(self, **kwargs):
        if self.barrier:
            self.barrier.wait(timeout=1)
        time.sleep(self.delay)
        payload = json.loads(kwargs["messages"][1]["content"])
        schema = kwargs["response_format"]
        if "domains" in payload:
            result = schema(summary="확인한 결과이오.", wrong_summary="구분 기준을 살펴보시오.")
        else:
            result = schema(diagnosis="이번 문항의 기준이오.", wrong=[{"id": "bad" if self.bad_ids else q["id"], "text": "실제 선택과 정답의 차이이오."} for q in payload["wrong"]], focus="기준과 전략", guide="핵심이오. 비교해야 하오. 단서를 살펴보시오.")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=result, refusal=None))], usage=None)


class ParallelReportTest(unittest.TestCase):
    def test_tasks_run_concurrently_and_preserve_exact_facts(self):
        g = graded()
        report = generate_parallel_report(FakeClient(barrier=threading.Barrier(3)), g, "test", budget=2)
        self.assertEqual(report.level_diagnosis.overall_level, g["summary"]["level"])
        self.assertEqual([x.score for x in report.level_diagnosis.domain_comments], [x["score"] for x in g["domain_scores"]])
        self.assertEqual([x.question_id for x in report.wrong_answer_analysis.items], [x["question_id"] for x in g["question_results"]])
        self.assertEqual([x.domain for x in report.recommendations], [x["domain"] for x in g["domain_scores"]])

    def test_compact_input_drops_unused_choices_and_duplicate_evidence(self):
        task = build_tasks(graded())[1][1]
        question = task["wrong"][0]
        self.assertNotIn("options", question)
        self.assertEqual(question["selected"], "b")
        self.assertEqual(question["correct"], "a")
        self.assertEqual(question["evidence"], ["same evidence", "selected evidence"])

    def test_wrong_id_mismatch_fails_instead_of_fabricating_missing_analysis(self):
        with self.assertRaises(LlmReportError):
            generate_parallel_report(FakeClient(bad_ids=True), graded(), "test", budget=2)

    def test_deadline_does_not_wait_for_all_slow_workers(self):
        start = time.perf_counter()
        with self.assertRaises(ReportDeadlineError):
            generate_parallel_report(FakeClient(delay=0.25), graded(), "test", budget=0.03)
        self.assertLess(time.perf_counter() - start, 0.2)

    def test_perfect_case_never_requests_weaknesses(self):
        g = graded()
        for row in g["question_results"]:
            row["is_correct"] = True
        for row in g["domain_scores"]:
            row["is_vulnerable"] = False
            row["score"] = 100
        tasks = build_tasks(g)
        self.assertEqual(sum(t[1].get("recommend", False) for t in tasks), 1)
        self.assertTrue(all(t[1]["maintain"] and not t[1]["wrong"] for t in tasks[1:]))


class ServiceDeadlineTest(unittest.TestCase):
    def test_provider_timeout_preserves_grades_and_failure_status(self):
        from unittest.mock import patch
        from database.repository import InMemoryDiagnosticRepository
        from schemas.diagnostic import SubmitRequest
        from services.diagnostic_service import DiagnosticService
        from services.question_bank import load_questions
        qs = load_questions()
        repo = InMemoryDiagnosticRepository()
        service = DiagnosticService(qs, repo)
        started = service.start("user")
        service.submit(started.id, "user", SubmitRequest(answers=[{"question_id": q["id"], "selected_answer": q["answer"]} for q in qs]), "key")
        before = service.get_report(started.id, "user").model_dump()
        with patch("services.diagnostic_service.generate_llm_report", side_effect=ReportDeadlineError("timeout")):
            service.generate_report(started.id, "user")
        result = service.get_report(started.id, "user")
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error.code, "REPORT_GENERATION_TIMEOUT")
        self.assertEqual(result.model_dump()["question_results"], before["question_results"])
        self.assertEqual(result.model_dump()["summary"], before["summary"])
