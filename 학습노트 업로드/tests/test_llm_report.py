import os
import unittest

os.environ["LLM_REPORT_MODE"] = "local"

from schemas.llm_report import (
    LevelDiagnosis,
    LlmReportAnalysis,
    WrongAnswerAnalysis,
    WrongAnswerItem,
)
from services.errors import LlmReportError
from services.grading import grade_attempt
from services.llm_report import (
    _resolved_mode,
    align_llm_report,
    generate_openai_report,
)


def _question(question_id: str, domain: str, answer: int = 1) -> dict:
    return {
        "id": question_id,
        "domain": domain,
        "category": "sample",
        "difficulty": 1,
        "concept": f"개념-{question_id}",
        "question": "질문",
        "options": ["1) a", "2) b", "3) c", "4) d"],
        "answer": answer,
        "explanation": {"correct": "해설", "options_detail": ["d1"]},
    }


def _graded():
    questions = [
        _question("a1", "finance_investment", 1),
        _question("a2", "finance_investment", 1),
    ]
    return grade_attempt(questions, {"a1": 2, "a2": 1})


class _Message:
    def __init__(self, parsed, refusal=None):
        self.parsed = parsed
        self.refusal = refusal


class _Completion:
    def __init__(self, message):
        self.choices = [type("Choice", (), {"message": message})()]


class _Completions:
    def __init__(self, message):
        self.message = message
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return _Completion(self.message)


class _Client:
    def __init__(self, message):
        self.chat = type("Chat", (), {})()
        self.chat.completions = _Completions(message)
        self.beta = type("Beta", (), {"chat": self.chat})()


class OpenAiReportParseTest(unittest.TestCase):
    def test_parse_uses_structured_schema_and_keeps_graded_facts(self):
        graded = _graded()
        drafted = LlmReportAnalysis(
            level_diagnosis=LevelDiagnosis(
                overall_level="보완필요",
                summary="금융 기초를 다시 봐야 합니다.",
                domain_comments=[],
            ),
            wrong_answer_analysis=WrongAnswerAnalysis(
                summary="복리 개념이 비어 있습니다.",
                items=[
                    WrongAnswerItem(
                        question_id="a1",
                        concept="다른 이름",
                        domain="finance_investment",
                        domain_label="다른 라벨",
                        vulnerability="이자 계산 방식을 혼동했습니다.",
                    ),
                    WrongAnswerItem(
                        question_id="없는-문항",
                        concept="없는 개념",
                        domain="finance_investment",
                        domain_label="금융·투자",
                        vulnerability="입력에 없는 분석",
                    ),
                ],
            ),
            recommendations=[],
        )
        client = _Client(_Message(drafted))

        report = generate_openai_report(client, graded, "gpt-4o-mini")

        self.assertIs(client.chat.completions.kwargs["response_format"], LlmReportAnalysis)
        self.assertEqual(client.chat.completions.kwargs["model"], "gpt-4o-mini")
        self.assertEqual(report.level_diagnosis.overall_level, graded["summary"]["level"])
        self.assertEqual(report.level_diagnosis.summary, "금융 기초를 다시 봐야 합니다.")
        self.assertEqual(report.level_diagnosis.domain_comments[0].score, graded["domain_scores"][0]["score"])
        self.assertEqual([item.question_id for item in report.wrong_answer_analysis.items], ["a1"])
        self.assertEqual(report.wrong_answer_analysis.items[0].vulnerability, "이자 계산 방식을 혼동했습니다.")
        self.assertEqual(report.wrong_answer_analysis.items[0].concept, "개념-a1")

    def test_unparsed_response_is_rejected(self):
        with self.assertRaises(LlmReportError):
            generate_openai_report(_Client(_Message(None)), _graded(), "gpt-4o-mini")

    def test_refusal_is_rejected(self):
        with self.assertRaises(LlmReportError):
            generate_openai_report(_Client(_Message(None, refusal="거절")), _graded(), "gpt-4o-mini")

    def test_align_drops_concepts_that_were_not_wrong(self):
        graded = _graded()
        draft = LlmReportAnalysis(
            level_diagnosis=LevelDiagnosis(
                overall_level="우수",
                summary="요약",
                domain_comments=[],
            ),
            wrong_answer_analysis=WrongAnswerAnalysis(summary="오답 요약", items=[]),
            recommendations=[],
        )
        aligned = align_llm_report(draft, graded)
        self.assertEqual(aligned.level_diagnosis.overall_level, "보완필요")
        self.assertEqual(len(aligned.wrong_answer_analysis.items), 1)
        self.assertEqual(aligned.recommendations[0].priority, 1)
        self.assertEqual(aligned.recommendations[0].domain, "finance_investment")


class ResolveModeTest(unittest.TestCase):
    def test_auto_uses_openai_key_or_local(self):
        self.assertEqual(_resolved_mode(_settings("auto", openai="o")), "openai")
        self.assertEqual(_resolved_mode(_settings("auto")), "local")
        self.assertEqual(_resolved_mode(_settings("openai")), "openai")
        self.assertEqual(_resolved_mode(_settings("local", openai="o")), "local")

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(LlmReportError):
            _resolved_mode(_settings("unsupported"))


def _settings(mode: str, openai: str | None = None):
    return type("Settings", (), {"llm_report_mode": mode, "openai_api_key": openai})()


if __name__ == "__main__":
    unittest.main()


class ReportEvidenceTest(unittest.TestCase):
    def test_actual_selected_option_explanation_is_sent(self):
        from services.llm_report import build_llm_input
        q = _question("a1", "finance_investment")
        q["explanation"]["options_detail"] = ["correct clue", "selected clue", "third", "fourth"]
        row = build_llm_input(grade_attempt([q], {"a1": 2}))["wrong_answers"][0]
        self.assertEqual(row["selected_option"], "2) b")
        self.assertEqual(row["selected_option_explanation"], "selected clue")
        self.assertEqual(row["correct_option_explanation"], "correct clue")

    def test_legacy_incomplete_explanations_are_not_misattributed(self):
        from services.llm_report import build_llm_input
        row = build_llm_input(_graded())["wrong_answers"][0]
        self.assertEqual(row["selected_option_explanation"], "")

    def test_local_fallback_uses_actual_answer_pair(self):
        from services.llm_report import generate_local_report
        report = generate_local_report(_graded())
        text = report.wrong_answer_analysis.items[0].vulnerability
        self.assertIn("b", text)
        self.assertIn("a", text)
