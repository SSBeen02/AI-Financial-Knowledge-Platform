import os
import re
import unittest

os.environ["DEV_MODE"] = "true"
os.environ["DIAGNOSTIC_REPOSITORY"] = "memory"
os.environ["LLM_REPORT_MODE"] = "local"

from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from services.errors import LlmReportError
from services.grading import grade_attempt
from services.question_bank import count_by_domain, load_questions

ISO_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
HIDDEN_KEYS = {"answer", "explanation", "concept"}


def _sample_question(question_id: str, domain: str, answer: int = 1) -> dict:
    return {
        "id": question_id,
        "domain": domain,
        "category": "sample",
        "difficulty": 1,
        "concept": f"개념-{question_id}",
        "question": "질문",
        "options": ["1) a", "2) b", "3) c", "4) d"],
        "answer": answer,
        "explanation": {"correct": "해설", "options_detail": ["d1", "d2", "d3", "d4"]},
    }


def _assert_no_keys(value, banned: set[str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in banned:
                raise AssertionError(key)
            _assert_no_keys(nested, banned)
    elif isinstance(value, list):
        for item in value:
            _assert_no_keys(item, banned)


class GradingTest(unittest.TestCase):
    def test_domain_severity_and_threshold(self):
        questions = [
            _sample_question("a1", "finance_investment", 1),
            _sample_question("a2", "finance_investment", 1),
            _sample_question("b1", "macroeconomy_monetary_fiscal_policy", 2),
            _sample_question("b2", "macroeconomy_monetary_fiscal_policy", 2),
        ]
        graded = grade_attempt(
            questions,
            {"a1": 2, "a2": 2, "b1": 2, "b2": 1},
        )

        self.assertEqual(graded["summary"]["score"], 25.0)
        self.assertEqual(graded["summary"]["level"], "보완필요")
        self.assertEqual(graded["summary"]["weakest_domain"], "finance_investment")
        self.assertEqual(graded["vulnerabilities"][0]["domain"], "finance_investment")
        self.assertEqual(graded["vulnerabilities"][0]["severity"], "high")
        self.assertEqual(graded["vulnerabilities"][0]["score"], 0.0)
        self.assertEqual(graded["vulnerabilities"][1]["severity"], "medium")
        self.assertEqual(graded["vulnerabilities"][1]["score"], 50.0)
        self.assertIn("금융·투자 0점", graded["summary"]["analysis"])

    def test_clear_result_has_no_vulnerability(self):
        questions = [
            _sample_question("a1", "finance_investment", 1),
            _sample_question("a2", "finance_investment", 1),
        ]
        graded = grade_attempt(questions, {"a1": 1, "a2": 1})
        self.assertEqual(graded["summary"]["score"], 100.0)
        self.assertEqual(graded["summary"]["level"], "우수")
        self.assertEqual(graded["vulnerabilities"], [])
        self.assertFalse(graded["domain_scores"][0]["is_vulnerable"])


class DiagnosticApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        original_post = self.client.post
        def post(url, **kwargs):
            if url.endswith("/submit"):
                kwargs.setdefault("headers", {"Idempotency-Key": "test-key"})
            return original_post(url, **kwargs)
        self.client.post = post
        self.questions = load_questions()

    def _answers(self, overrides: dict[str, int] | None = None) -> list[dict]:
        overrides = overrides or {}
        return [
            {
                "question_id": question["id"],
                "selected_answer": overrides.get(question["id"], question["answer"]),
            }
            for question in self.questions
        ]

    def test_question_bank_shape(self):
        counts = count_by_domain(self.questions)
        self.assertEqual(len(self.questions), 24)
        self.assertEqual(len(counts), 4)
        self.assertTrue(all(count == 6 for count in counts.values()))

    def test_start_hides_answer_key_and_records_dummy_user(self):
        response = self.client.post("/diagnostics")
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["user_id"], "test-user-123")
        self.assertEqual(body["status"], "pending")
        self.assertEqual(body["total_questions"], 24)
        self.assertRegex(body["started_at"], ISO_UTC)
        self.assertEqual(len(body["questions"]), 24)
        self.assertEqual(body["questions"][0]["options"][1], "2) 복리")
        _assert_no_keys(body, HIDDEN_KEYS)

        spec = self.client.get("/openapi.json").json()
        self.assertEqual(
            set(spec["paths"]),
            {
                "/diagnostics",
                "/diagnostics/{id}/submit",
                "/reports/{id}",
            },
        )
        start_parameters = spec["paths"]["/diagnostics"]["post"].get("parameters", [])
        self.assertFalse(any(item.get("name") == "user_id" for item in start_parameters))

        pending = self.client.get(f"/reports/{body['id']}")
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()["status"], "pending")
        self.assertNotIn("llm_report", pending.json())

    def test_perfect_submit_and_report_lookup(self):
        started = self.client.post("/diagnostics").json()
        submitted = self.client.post(f"/diagnostics/{started['id']}/submit", json={"answers": self._answers()})
        self.assertEqual(submitted.status_code, 202, submitted.text)
        body = submitted.json()
        self.assertEqual(body["id"], started["id"])
        self.assertEqual(body["report_id"], started["id"])
        self.assertEqual(body["user_id"], "test-user-123")
        self.assertEqual(body["summary"]["score"], 100.0)
        self.assertEqual(body["summary"]["level"], "우수")
        self.assertEqual(body["summary"]["correct_count"], 24)
        self.assertTrue(all(item["is_correct"] for item in body["question_results"]))
        self.assertIn("concept", body["question_results"][0])
        self.assertIn("explanation", body["question_results"][0])
        self.assertRegex(body["submitted_at"], ISO_UTC)

        report = self.client.get(f"/reports/{body['report_id']}")
        self.assertEqual(report.status_code, 200)
        report_body = report.json()
        self.assertEqual(report_body["id"], body["report_id"])
        self.assertEqual(report_body["diagnostic_id"], started["id"])
        self.assertEqual(report_body["vulnerabilities"], [])
        self.assertEqual(len(report_body["domain_scores"]), 4)
        self.assertEqual(report_body["status"], "completed")
        self.assertNotIn("unpassed_concepts", report_body["llm_report"])
        self.assertEqual(report_body["llm_report"]["wrong_answer_analysis"]["items"], [])
        self.assertEqual(report_body["llm_report"]["level_diagnosis"]["overall_level"], "우수")
        self.assertRegex(report_body["created_at"], ISO_UTC)

        again = self.client.post(
            f"/diagnostics/{started['id']}/submit",
            json={"answers": self._answers()},
        )
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["status"], "completed")

    def test_vulnerable_domain_is_saved_on_the_report(self):
        finance_ids = [
            question["id"]
            for question in self.questions
            if question["domain"] == "finance_investment"
        ]
        wrong = {question_id: 1 for question_id in finance_ids}
        for question in self.questions:
            if question["id"] in wrong and question["answer"] == 1:
                wrong[question["id"]] = 2

        started = self.client.post("/diagnostics").json()
        submitted = self.client.post(
            f"/diagnostics/{started['id']}/submit",
            json={"answers": self._answers(wrong)},
        )
        self.assertEqual(submitted.status_code, 202, submitted.text)
        body = submitted.json()
        finance = next(item for item in body["domain_scores"] if item["domain"] == "finance_investment")
        self.assertEqual(finance["score"], 0.0)
        self.assertTrue(finance["is_vulnerable"])
        self.assertEqual(body["summary"]["score"], 75.0)
        self.assertEqual(body["summary"]["level"], "양호")
        self.assertEqual(body["summary"]["weakest_domain"], "finance_investment")

        report = self.client.get(f"/reports/{body['report_id']}").json()
        self.assertEqual(report["vulnerabilities"][0]["domain"], "finance_investment")
        self.assertEqual(report["vulnerabilities"][0]["severity"], "high")
        self.assertEqual(len(report["vulnerabilities"][0]["missed_concepts"]), 6)
        self.assertIn("단리와 복리의 차이", report["vulnerabilities"][0]["missed_concepts"])
        wrong_items = report["llm_report"]["wrong_answer_analysis"]["items"]
        self.assertEqual([item["concept"] for item in wrong_items], report["vulnerabilities"][0]["missed_concepts"])
        self.assertEqual([item["question_id"] for item in wrong_items], finance_ids)
        self.assertNotIn("unpassed_concepts", report["llm_report"])
        self.assertEqual(report["llm_report"]["level_diagnosis"]["overall_level"], "양호")
        self.assertEqual(report["llm_report"]["recommendations"][0]["domain"], "finance_investment")
        self.assertEqual(report["llm_report"]["recommendations"][0]["priority"], 1)
        self.assertTrue(report["domain_scores"])
        self.assertTrue(
            all(item["domain"] == "finance_investment" for item in report["vulnerabilities"])
        )

    def test_invalid_submit_keeps_the_attempt_open(self):
        started = self.client.post("/diagnostics").json()
        partial = self._answers()[:-1]
        missing = self.client.post(f"/diagnostics/{started['id']}/submit", json={"answers": partial})
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(missing.json()["code"], "INVALID_ANSWERS")
        self.assertIn(self.questions[-1]["id"], missing.json()["message"])
        self.assertEqual(set(missing.json()), {"code", "message", "request_id"})

        out_of_range = self._answers()
        out_of_range[0]["selected_answer"] = 9
        ranged = self.client.post(f"/diagnostics/{started['id']}/submit", json={"answers": out_of_range})
        self.assertEqual(ranged.status_code, 422)
        self.assertIn(self.questions[0]["id"], ranged.json()["message"])

        unknown = self._answers()
        unknown[0]["question_id"] = "missing-question"
        unknown_response = self.client.post(
            f"/diagnostics/{started['id']}/submit",
            json={"answers": unknown},
        )
        self.assertEqual(unknown_response.status_code, 422)
        self.assertIn("missing-question", unknown_response.json()["message"])

        still_pending = self.client.get(f"/reports/{started['id']}")
        self.assertEqual(still_pending.status_code, 200)
        self.assertEqual(still_pending.json()["status"], "pending")

        recovered = self.client.post(
            f"/diagnostics/{started['id']}/submit",
            json={"answers": self._answers()},
        )
        self.assertEqual(recovered.status_code, 202)

    def test_generation_failure_is_visible_on_report_lookup(self):
        started = self.client.post("/diagnostics").json()
        with patch(
            "services.diagnostic_service.generate_llm_report",
            side_effect=LlmReportError("맞춤 리포트를 생성하지 못했습니다."),
        ):
            failed = self.client.post(
                f"/diagnostics/{started['id']}/submit",
                json={"answers": self._answers()},
            )
        self.assertEqual(failed.status_code, 202)

        report = self.client.get(f"/reports/{started['id']}")
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.json()["status"], "failed")
        self.assertNotIn("llm_report", report.json())
        self.assertTrue(report.json()["domain_scores"])

        again = self.client.post(
            f"/diagnostics/{started['id']}/submit",
            json={"answers": self._answers()},
        )
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["status"], "failed")

    def test_unknown_diagnostic_is_not_found(self):
        response = self.client.post(
            "/diagnostics/00000000-0000-0000-0000-000000000000/submit",
            json={"answers": self._answers()},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "DIAGNOSTIC_NOT_FOUND")
        missing_report = self.client.get("/reports/does-not-exist")
        self.assertEqual(missing_report.status_code, 404)
        self.assertEqual(missing_report.json()["code"], "REPORT_NOT_FOUND")
        self.assertEqual(set(missing_report.json()), {"code", "message", "request_id"})


if __name__ == "__main__":
    unittest.main()
