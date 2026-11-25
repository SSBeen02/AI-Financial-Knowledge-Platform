import unittest

from app.services.quiz_tone import choice_in_modern, explanation_in_hao, question_in_hao
from app.services.stage5_bank import load_bank, fixed_questions
from app.services.quiz_service import normalize_questions


class QuizToneTests(unittest.TestCase):
    def test_question_polite_endings_regression(self):
        cases = {
            '옳지 않나요?':'옳지 않소?', '올바른 선택이 아닌가요?':'올바른 선택이 아니오?',
            '어떻게 하나요?':'어떻게 하오?', '이 조건이 좋나요?':'이 조건이 좋소?',
            '이 방법이 좋아요.':'이 방법이 좋소.', '금액이 같아요.':'금액이 같소.',
            '원금 100원이 5% 증가했어요.':'원금 100원이 5% 증가했소.',
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(question_in_hao(source),expected)
                self.assertEqual(question_in_hao(expected),expected)

    def test_situation_choice_endings_and_nouns_regression(self):
        cases={
            '각자 맡은 일을 하면서 다음 공정을 기다리오.':'각자 맡은 일을 하면서 다음 공정을 기다린다.',
            '역할을 나누오.':'역할을 나눈다.', '잘하는 업무를 맡으오.':'잘하는 업무를 맡는다.',
            '비용을 줄이오.':'비용을 줄인다.', '설명서를 읽으오.':'설명서를 읽는다.',
            '회의 장소':'회의 장소', '라디오':'라디오', '시나리오':'시나리오',
            '100원, 5%, A, B':'100원, 5%, A, B',
        }
        for source,expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(choice_in_modern(source),expected)
                self.assertEqual(choice_in_modern(expected),expected)

    def test_ox_labels_are_consistent_for_generated_and_fixed_questions(self):
        concept_id = next(iter(load_bank()))
        for labels in [("맞소", "아니오"), ("O", "X"), ("맞아요", "아니에요")]:
            with self.subTest(labels=labels):
                questions = fixed_questions(concept_id)
                for question in questions[:2]:
                    question['choices'] = [{'key':'O','text':labels[0]}, {'key':'X','text':labels[1]}]
                normalized = normalize_questions(questions)
                for question in normalized[:2]:
                    self.assertEqual(question['choices'], [{'key':'O','text':'O'}, {'key':'X','text':'X'}])
                self.assertEqual([q['answer'] for q in normalized], [q['answer'] for q in questions])

    def test_questions_use_hao_and_situation_choices_use_modern_style(self):
        for original, expected in [
            ('분업은 일을 나누는 것이다.', '분업은 일을 나누는 것이오.'),
            ('어떤 선택이 맞을까요?', '어떤 선택이 맞겠소?'),
            ('알맞은 것은?', '알맞은 것은 무엇이오?'),
            ('어떤 방법인가요?', '어떤 방법이오?'),
            ('원금 100원은 10% 증가합니다. 결과는?', '원금 100원은 10% 증가하오. 결과는 무엇이오?'),
        ]:
            self.assertEqual(question_in_hao(original), expected)
            self.assertEqual(question_in_hao(expected), expected)
        self.assertEqual(choice_in_modern('역할을 나누어 맡고 특정 업무에 집중하오.'), '역할을 나누어 맡고 특정 업무에 집중한다.')
        self.assertEqual(choice_in_modern('안내 자료를 살펴보오.'), '안내 자료를 살펴본다.')
        self.assertEqual(choice_in_modern('회의 장소'), '회의 장소')
        self.assertEqual(choice_in_modern('라디오'), '라디오')

    def test_all_fixed_questions_have_hao_endings(self):
        for concept_id in load_bank():
            for q in fixed_questions(concept_id):
                with self.subTest(concept_id=concept_id, question=q['question_index']):
                    self.assertRegex(q['prompt'], r'[오소][.!?。！？]*$')
                    self.assertEqual(question_in_hao(q['prompt']), q['prompt'])

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
