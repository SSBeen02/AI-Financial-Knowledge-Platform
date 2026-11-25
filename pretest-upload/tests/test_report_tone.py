import copy
import unittest
from unittest.mock import patch

from pretest.database.repository import InMemoryDiagnosticRepository
from pretest.schemas.diagnostic import SubmitRequest
from pretest.services.diagnostic_service import DiagnosticService
from pretest.services.grading import grade_attempt
from pretest.services.llm_report import generate_local_report
from pretest.services.question_bank import load_questions
from pretest.services.report_tone import normalize_haoche_text, normalize_report_tone


class ReportToneTest(unittest.TestCase):
    def test_polite_endings_and_economic_terms(self):
        self.assertEqual(normalize_haoche_text("개념입니다. 복습하세요. 수요. 필요. GDP 33.3점, 지표요."),
                         "개념이오. 복습하시오. 수요. 필요. GDP 33.3점, 지표라오.")
        self.assertEqual(normalize_haoche_text("크게 커집니다. 영향을 미칩니다. 뜻을 가리킵니다. 틀렸습니다."),
                         "크게 커지오. 영향을 미치오. 뜻을 가리키오. 틀렸소.")

    def test_local_reports_are_haoche_and_questions_are_preserved(self):
        questions = load_questions()
        before = copy.deepcopy(questions)
        for case in ("perfect", "partial", "all_wrong"):
            answers = {q["id"]: q["answer"] if case == "perfect" or (case == "partial" and i % 2 == 0) else q["answer"] % 4 + 1 for i, q in enumerate(questions)}
            graded = grade_attempt(questions, answers)
            original = copy.deepcopy(graded)
            report = generate_local_report(graded)
            self.assertEqual(report, normalize_report_tone(report))
            self.assertEqual(graded, original)
        self.assertEqual(questions, before)

    def test_new_and_saved_report_paths_use_haoche(self):
        questions = load_questions()
        repository = InMemoryDiagnosticRepository()
        service = DiagnosticService(questions, repository)
        started = service.start("tone-user")
        payload = SubmitRequest(answers=[{"question_id": q["id"], "selected_answer": q["answer"]} for q in questions])
        submitted, _ = service.submit(started.id, "tone-user", payload, "tone-key")
        before = repository.get_attempt(started.id, "tone-user")
        report = generate_local_report(before)
        report.level_diagnosis.summary = "결과를 확인했습니다. 다음 개념을 복습하세요."
        report.wrong_answer_analysis.summary = "틀린 문항이 없습니다."
        with patch("pretest.services.diagnostic_service.generate_llm_report", return_value=report):
            service.generate_report(started.id, "tone-user")
        stored = repository.get_attempt(started.id, "tone-user")
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(stored["llm_report"]["level_diagnosis"]["summary"], "결과를 확인했소. 다음 개념을 복습하시오.")
        # 예전 일반 존댓말 기록도 조회 경로에서 보정한다.
        repository.update_attempt(started.id, "tone-user", "completed", {"llm_report": report.model_dump()})
        saved = repository.get_attempt(started.id, "tone-user")
        response = service.get_report(started.id, "tone-user")
        self.assertIn("결과를 확인했소. 다음 개념을 복습하시오.", response.llm_report.level_diagnosis.summary)
        self.assertEqual(response.summary.score, submitted.summary.score)
        self.assertEqual(repository.get_attempt(started.id, "tone-user"), saved)
        self.assertEqual([q.model_dump() for q in response.question_results], before["question_results"])


if __name__ == "__main__":
    unittest.main()
