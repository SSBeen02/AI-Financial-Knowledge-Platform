import unittest

from app.services.quiz_tone import choice_in_polite, explanation_in_polite, question_in_polite
from app.services.stage5_bank import load_bank, fixed_questions
from app.services.quiz_service import normalize_questions


class QuizToneTests(unittest.TestCase):
    def test_question_polite_endings_regression(self):
        cases = {
            '옳지 않나요?':'옳지 않습니까?', '올바른 선택이 아닌가요?':'올바른 선택이 아닙니까?',
            '어떻게 하나요?':'어떻게 합니까?', '이 조건이 좋나요?':'이 조건이 좋습니까?',
            '이 방법이 좋아요.':'이 방법이 좋습니다.', '금액이 같아요.':'금액이 같습니다.',
            '원금 100원이 5% 증가했어요.':'원금 100원이 5% 증가했습니다.',
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(question_in_polite(source),expected)
                self.assertEqual(question_in_polite(expected),expected)

    def test_situation_choice_endings_and_nouns_regression(self):
        cases={
            '각자 맡은 일을 하면서 다음 공정을 기다리오.':'각자 맡은 일을 하면서 다음 공정을 기다립니다.',
            '역할을 나누오.':'역할을 나눕니다.', '잘하는 업무를 맡으오.':'잘하는 업무를 맡습니다.',
            '비용을 줄이오.':'비용을 줄입니다.', '설명서를 읽으오.':'설명서를 읽습니다.',
            '회의 장소':'회의 장소', '라디오':'라디오', '시나리오':'시나리오',
            '100원, 5%, A, B':'100원, 5%, A, B',
        }
        for source,expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(choice_in_polite(source),expected)
                self.assertEqual(choice_in_polite(expected),expected)

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

    def test_questions_and_choices_use_polite_style(self):
        for original, expected in [
            ('분업은 일을 나누는 것이다.', '분업은 일을 나누는 것입니다.'),
            ('어떤 선택이 맞을까요?', '어떤 선택이 맞겠습니까?'),
            ('알맞은 것은?', '알맞은 것은 무엇입니까?'),
            ('어떤 방법인가요?', '어떤 방법입니까?'),
            ('원금 100원은 10% 증가합니다. 결과는?', '원금 100원은 10% 증가합니다. 결과는 무엇입니까?'),
        ]:
            self.assertEqual(question_in_polite(original), expected)
            self.assertEqual(question_in_polite(expected), expected)
        self.assertEqual(choice_in_polite('역할을 나누어 맡고 특정 업무에 집중하오.'), '역할을 나누어 맡고 특정 업무에 집중합니다.')
        self.assertEqual(choice_in_polite('안내 자료를 살펴보오.'), '안내 자료를 살펴봅니다.')
        self.assertEqual(choice_in_polite('회의 장소'), '회의 장소')
        self.assertEqual(choice_in_polite('라디오'), '라디오')

    def test_all_fixed_questions_have_polite_endings(self):
        for concept_id in load_bank():
            for q in fixed_questions(concept_id):
                with self.subTest(concept_id=concept_id, question=q['question_index']):
                    self.assertNotRegex(q['prompt'], r'(?:하오|이오|있소|없소|겠소)[.!?]')
                    self.assertEqual(question_in_polite(q['prompt']), q['prompt'])

    def test_endings_and_numbers(self):
        self.assertEqual(
            explanation_in_polite("탄력성은 2로 1보다 큽니다. 총수입은 감소합니다. 관련이 있습니다. 정답입니다."),
            "탄력성은 2로 1보다 큽니다. 총수입은 감소합니다. 관련이 있습니다. 정답입니다.",
        )
        self.assertEqual(explanation_in_polite("이는 역의 관계입니다."), "이는 역의 관계입니다.")
        text = "정답은 B이오. 수익률은 10%가 되오. 이 방식이 좋소."
        self.assertEqual(explanation_in_polite(text), "정답은 B입니다. 수익률은 10%가 됩니다. 이 방식이 좋습니다.")

    def test_all_fixed_explanations_are_normalized(self):
        for concept_id in load_bank():
            for question in fixed_questions(concept_id):
                self.assertNotRegex(question["explanation"], r"(?:하오|이오|있소|없소)[.!?]")
                self.assertEqual(explanation_in_polite(question["explanation"]), question["explanation"])


    def test_legacy_learning_note_is_polite_without_mutating_original(self):
        import copy
        from types import SimpleNamespace
        from datetime import datetime, timezone
        from app.services.quiz_service import _note_items, _public_question, _submit_response
        question = dict(question_index=1, question_type='situation',
            prompt='100원을 나누는 선택이 맞소?',
            choices=[dict(key='A', text='역할을 나눈다.'), dict(key='B', text='일을 맡으오.')],
            answer='A', explanation='역할을 나누는 것이오. 효율이 높소.')
        original = copy.deepcopy(question)
        quiz = SimpleNamespace(id='quiz', concept_id='concept', stage_id='stage1',
            learning_session_id='session', questions=[question], created_at=datetime.now(timezone.utc))
        submission = SimpleNamespace(id='submission', submitted_answers=[dict(question_index=1, answer='B')],
            is_correct_list=[False], correct_count=0, is_passed=False, created_at=quiz.created_at)
        note = _note_items(quiz, submission)[0]
        self.assertEqual(note.prompt, '100원을 나누는 선택이 맞습니까?')
        self.assertEqual(note.choices[0].text, '역할을 나눕니다.')
        self.assertEqual(note.explanation, '역할을 나누는 것입니다. 효율이 높습니다.')
        self.assertEqual((note.answer, note.submitted_answer, note.is_correct, note.is_passed), ('A', 'B', False, False))
        self.assertEqual(_public_question(question).prompt, note.prompt)
        self.assertEqual(question, original)

    def test_prompt_requires_polite_korean(self):
        from app.services.quiz_service import QUIZ_SYSTEM_PROMPT
        self.assertIn('현대 존댓말', QUIZ_SYSTEM_PROMPT)
        self.assertIn('질문은', QUIZ_SYSTEM_PROMPT)
        self.assertNotIn('현대 하오체로 씁니다', QUIZ_SYSTEM_PROMPT)

    def test_nouns_and_annotations_are_preserved(self):
        for noun in ['금융연구소', '오디오', '수요', '필요', '회의 장소', '시나리오', '100원']:
            self.assertEqual(choice_in_polite(noun), noun)
        self.assertEqual(explanation_in_polite('공급이 많소(예시).'), '공급이 많습니다(예시).')
        self.assertEqual(explanation_in_polite('정답은 아니에요.'), '정답은 아닙니다.')


    def test_reported_hao_exceptions_in_all_output_functions(self):
        for converter in (question_in_polite, choice_in_polite, explanation_in_polite):
            for source, expected in [('옳소.', '옳습니다.'), ('비교해 보시오.', '비교해 보십시오.'), ('모으오.', '모읍니다.'),
                                     ('옳소?', '옳습니까?'), ('설명을 읽으시오.', '설명을 읽으십시오.')]:
                with self.subTest(converter=converter.__name__, source=source):
                    self.assertEqual(converter(source, strict=True), expected)
                    self.assertEqual(converter(expected, strict=True), expected)

    def test_unknown_ending_is_rejected_or_hidden_never_returned(self):
        from app.services.quiz_tone import PoliteToneError
        for converter in (question_in_polite, choice_in_polite, explanation_in_polite):
            for text in ['이것을 살펴봤노라.', '이 선택이 옳소! 다른 방법은 모르겠네.', '돈을 모으시오. 다른 것은 살펴보게.']:
                with self.subTest(converter=converter.__name__, text=text):
                    with self.assertRaises(PoliteToneError):
                        converter(text, strict=True)
                    self.assertEqual(converter(text), '이 문장의 존댓말 표현을 확인할 수 없습니다.')

    def test_dynamic_payload_rejects_unconverted_tone(self):
        import copy
        from app.services.quiz_tone import PoliteToneError
        questions = fixed_questions(next(iter(load_bank())))
        for field in ['prompt', 'explanation']:
            bad = copy.deepcopy(questions)
            bad[0][field] = '이 선택이 옳겠구나.'
            with self.subTest(field=field):
                with self.assertRaises(PoliteToneError):
                    normalize_questions(bad)


    def test_every_fixed_text_passes_without_fallback_or_data_loss(self):
        import json
        from pathlib import Path
        from app.services.quiz_tone import validate_polite_text
        bank = json.loads((Path(__file__).parents[1] / 'stage5_questions.json').read_text(encoding='utf-8'))
        for concept in bank:
            for original, rendered in zip(concept['questions'], fixed_questions(concept['concept_id']), strict=True):
                self.assertEqual(rendered['answer'], original['answer'])
                for text in [rendered['prompt'], rendered['explanation']] + [c['text'] for c in rendered['choices']]:
                    self.assertNotIn('존댓말 표현을 확인할 수 없습니다', text)
                    validate_polite_text(text, allow_fragments=True)
                if '(다)' in original['question']:
                    self.assertIn('(다)', rendered['prompt'])


    def test_parentheses_and_unpunctuated_imperatives_cannot_bypass_validation(self):
        from app.services.quiz_tone import PoliteToneError, validate_polite_text
        bad_texts = [
            '이 선택이 맞습니다. (다른 방법도 살펴보게.)',
            '이 선택이 맞습니다. （다른 방법도 살펴보게.）',
            '이 선택이 맞습니다. (참고 (다른 방법도 살펴보게.))',
            '은행에 돈을 맡겨라', '다른 방법도 살펴보게',
            '이 선택이 맞습니다. 은행에 돈을 맡겨라',
            '이 선택이 맞습니까? (가) 은행에 돈을 맡겨라',
        ]
        for text in bad_texts:
            for fragments in [False, True]:
                with self.subTest(text=text, fragments=fragments):
                    with self.assertRaises(PoliteToneError):
                        validate_polite_text(text, allow_fragments=fragments)
            for convert in (question_in_polite, choice_in_polite, explanation_in_polite):
                with self.subTest(text=text, convert=convert.__name__):
                    with self.assertRaises(PoliteToneError):
                        convert(text, strict=True)
                    self.assertNotEqual(convert(text), text)

    def test_real_payload_fields_reject_both_reported_bypasses(self):
        import copy
        from app.services.quiz_tone import PoliteToneError
        original = fixed_questions(next(iter(load_bank())))
        for text in ['이 선택이 맞습니다. (다른 방법도 살펴보게.)', '은행에 돈을 맡겨라']:
            for field in ['prompt', 'explanation', 'choice']:
                bad = copy.deepcopy(original)
                if field == 'choice':
                    bad[2]['choices'][0]['text'] = text
                else:
                    bad[0][field] = text
                with self.subTest(field=field, text=text):
                    with self.assertRaises(PoliteToneError):
                        normalize_questions(bad)

    def test_parenthesized_polite_sentences_and_noun_choices_are_allowed(self):
        from app.services.quiz_tone import validate_polite_text
        for text in ['이 선택이 맞습니다. (다른 방법도 살펴보십시오.)',
                     '이 선택이 맞습니다. (참고 (다른 방법도 살펴보십시오.))']:
            validate_polite_text(text)
        for text in ['정기예금', '회의 장소', '100원', '4.8%', '자본 200억 원, 부채비율 60%']:
            self.assertEqual(choice_in_polite(text, strict=True), text)


    def test_financial_noun_options_keep_their_content(self):
        from app.services.quiz_tone import PoliteToneError, validate_polite_text
        for text in ['주식', '채권', '정기적금', '적금', '금융 상품', '원금 보장', '금융상품', '원금보장', '한국어 보기']:
            with self.subTest(text=text):
                self.assertEqual(choice_in_polite(text, strict=True), text)
                self.assertEqual(choice_in_polite(text), text)
                # Bare nouns are options, not complete prompts or explanations.
                with self.assertRaises(PoliteToneError):
                    validate_polite_text(text)

    def test_financial_nouns_survive_generated_and_public_quiz_payloads(self):
        from app.services.quiz_service import _public_question
        for labels in [('주식', '채권', '정기적금', '금융 상품'),
                       ('원금 보장', '정기예금', '금융상품', '적금')]:
            questions = fixed_questions(next(iter(load_bank())))
            questions[2]['choices'] = [dict(key=key, text=text) for key, text in zip('ABCD', labels)]
            expected_answer = questions[2]['answer']
            result = normalize_questions(questions)[2]
            self.assertEqual(result['answer'], expected_answer)
            self.assertEqual([c['text'] for c in result['choices']], list(labels))
            self.assertEqual([c.text for c in _public_question(result).choices], list(labels))
