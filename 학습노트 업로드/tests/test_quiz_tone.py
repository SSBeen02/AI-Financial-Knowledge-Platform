import unittest

from app.services.quiz_tone import explanation_in_hao
from app.services.stage5_bank import load_bank, fixed_questions


class QuizToneTests(unittest.TestCase):
    def test_endings_and_numbers(self):
        self.assertEqual(
            explanation_in_hao("탄력성은 2로 1보다 큽니다. 총수입은 감소합니다. 관련이 있습니다. 정답입니다."),
            "탄력성은 2로 1보다 크오. 총수입은 감소하오. 관련이 있소. 정답이오.",
        )
        self.assertEqual(explanation_in_hao("이는 역의 관계입니다."), "이는 역의 관계요.")
        text = "정답은 B이오. 수익률은 10%가 되오. 이 방식이 좋소."
        self.assertEqual(explanation_in_hao(text), text)

    def test_all_fixed_explanations_are_normalized(self):
        for concept_id in load_bank():
            for question in fixed_questions(concept_id):
                self.assertNotRegex(question["explanation"], r"(?:습니다|[가-힣]니다|입니다)[.!?]")
