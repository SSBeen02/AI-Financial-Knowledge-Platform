import ast
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

from app.services.quiz_service import _note_items, _public_question, normalize_questions


JAPANESE_PROMPT = "レンタ貧困は、単に家賃が高いという意味だけである。"
tree = ast.parse(Path("tests/test_quizzes.py").read_text(encoding="utf-8-sig"))
SAMPLE = next(
    ast.literal_eval(node.value)
    for node in tree.body
    if isinstance(node, ast.Assign)
    and any(isinstance(target, ast.Name) and target.id == "SAMPLE_QUESTIONS" for target in node.targets)
)


class QuizLanguageTests(unittest.TestCase):
    def test_non_korean_generated_text_is_rejected(self):
        normalize_questions(deepcopy(SAMPLE))
        for field, value in [
            ("prompt", JAPANESE_PROMPT),
            ("prompt", "Rent poverty means rent is high."),
            ("explanation", "한국어 설명에 日本語가 섞였소."),
            ("choices", "価格を下げる"),
        ]:
            with self.subTest(field=field, value=value):
                questions = deepcopy(SAMPLE)
                if field == "choices":
                    questions[2]["choices"][0]["text"] = value
                else:
                    questions[0][field] = value
                with self.assertRaises(ValueError):
                    normalize_questions(questions)

    def test_saved_japanese_is_replaced_without_changing_grades(self):
        questions = normalize_questions(deepcopy(SAMPLE))
        questions[0]["prompt"] = JAPANESE_PROMPT
        questions[0]["explanation"] = "これは日本語です。"
        questions[1]["prompt"] = "別の質問です。"
        questions[2]["choices"][0]["text"] = "価格を下げる"
        now = datetime.now(timezone.utc)
        quiz = SimpleNamespace(
            id="quiz", concept_id="concept", stage_id="stage1",
            learning_session_id="session", questions=questions, created_at=now,
        )
        submission = SimpleNamespace(
            id="submission", created_at=now, submitted_answers=[{"question_index": 1, "answer": "O"}],
            is_correct_list=[False, False, False], is_passed=False,
        )
        items = _note_items(quiz, submission)
        self.assertEqual(items[0].prompt, "렌트 푸어는 단순히 임대료가 높다는 뜻이오.")
        self.assertEqual(_public_question(questions[0]).prompt, items[0].prompt)
        self.assertIn("한국어 해설", items[0].explanation)
        self.assertIn("한국어 문제", items[1].prompt)
        self.assertIn("한국어 내용", items[2].choices[0].text)
        self.assertFalse(items[0].is_correct)
        self.assertEqual(items[0].submitted_answer, "O")
        self.assertEqual(questions[0]["prompt"], JAPANESE_PROMPT)
