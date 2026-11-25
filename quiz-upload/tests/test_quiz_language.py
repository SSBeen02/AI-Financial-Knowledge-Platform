"""Finance terminology stays intact while explanatory prose remains Korean."""
import copy
import unittest
from unittest.mock import AsyncMock, patch
from tests import test_quiz_requirements as requirements
from app.services.quiz_language import localize_quiz_text, validate_korean_text, QuizLanguageError
from app.services.quiz_service import normalize_questions
from app.models.quiz import QuizSet


def ltv_questions():
    questions = copy.deepcopy(requirements.SAMPLE)
    questions[0]['prompt'] = 'LTV는 주택 가격 대비 대출 비율입니다.'
    questions[0]['explanation'] = 'LTV는 주택담보인정비율입니다.'
    questions[2]['choices'][0]['text'] = 'LTV를 확인합니다.'
    return questions


class QuizLanguageTests(unittest.TestCase):
    def test_finance_terms_are_preserved(self):
        for raw, expected in (('LTV', 'LTV'), ('ltv', 'ltv'), ('Ltv', 'Ltv'),
                              ('ＬＴＶ', 'LTV'), ('LTV비율', 'LTV비율'),
                              ('주택담보인정비율(LTV)', '주택담보인정비율(LTV)'),
                              ('Loan-to-Value ratio', 'Loan-to-Value ratio')):
            with self.subTest(raw=raw):
                self.assertEqual(localize_quiz_text(raw), expected)
        self.assertEqual(localize_quiz_text('LTV는 70%입니다.'), 'LTV는 70%입니다.')

    def test_all_fields_preserve_finance_terms(self):
        raw = ltv_questions()
        normalized = normalize_questions(raw)
        self.assertIn('LTV', normalized[0]['prompt'])
        self.assertIn('LTV', normalized[0]['explanation'])
        self.assertIn('LTV', normalized[2]['choices'][0]['text'])
        self.assertEqual([q['answer'] for q in normalized], [q['answer'] for q in raw])
        self.assertEqual([c['key'] for c in normalized[2]['choices']], ['A', 'B', 'C', 'D'])
        self.assertEqual([c['text'] for c in normalized[0]['choices']], ['O', 'X'])

    def test_existing_known_gdp_prompt_is_accepted(self):
        questions = copy.deepcopy(requirements.SAMPLE)
        questions[0]['prompt'] = 'GDP는 국내총생산입니다.'
        self.assertIn('GDP', normalize_questions(questions)[0]['prompt'])

    def test_english_finance_phrase_is_preserved_in_korean_explanation(self):
        questions = ltv_questions()
        questions[0]['explanation'] = 'Loan-to-Value ratio는 담보 가치 대비 대출 비율입니다.'
        normalized = normalize_questions(questions)
        self.assertIn('Loan-to-Value ratio', normalized[0]['explanation'])

    def test_unlisted_finance_terms_in_korean_prose_are_accepted(self):
        for field in ('prompt', 'explanation', 'choice'):
            questions = ltv_questions()
            if field == 'choice':
                questions[2]['choices'][0]['text'] = 'UNKNOWNRATIO를 확인합니다.'
            else:
                questions[0][field] = 'UNKNOWNRATIO를 확인합니다.'
            with self.subTest(field=field):
                normalized = normalize_questions(questions)
                actual = normalized[2]['choices'][0]['text'] if field == 'choice' else normalized[0][field]
                self.assertIn('UNKNOWNRATIO', actual)

    def test_english_explanation_is_rejected(self):
        with self.assertRaises(QuizLanguageError) as ctx:
            validate_korean_text('The LTV is high. 비율을 확인합니다.')
        self.assertEqual(ctx.exception.reason, 'english_prose')
        self.assertEqual(len(ctx.exception.text_sha256), 64)
        self.assertNotIn('The LTV is high', str(ctx.exception))

    def test_sensitive_values_are_redacted(self):
        with self.assertRaises(QuizLanguageError) as ctx:
            validate_korean_text('설명 api_key=sk-secret-example')
        self.assertEqual(ctx.exception.rejected_tokens, ('[redacted]',))


class QuizLanguageGenerationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = requirements.OriginalQuizRequirementsTests.asyncSetUp
    asyncTearDown = requirements.OriginalQuizRequirementsTests.asyncTearDown
    create = requirements.OriginalQuizRequirementsTests.create
    async def test_ltv_completes_without_wasted_regeneration(self):
        generator = AsyncMock(return_value=ltv_questions())
        created = await self.create(generator)
        self.assertEqual(created.status, 'completed')
        self.assertEqual(generator.await_count, 1)

    async def test_unknown_logs_fields_and_fails_without_publishing(self):
        questions = ltv_questions()
        questions[0]['explanation'] = 'The LTV is high. 비율을 확인합니다.'
        generator = AsyncMock(return_value=questions)
        notify = AsyncMock()
        with patch('app.services.quiz_service.report_quiz_generation_failed', notify), self.assertLogs('quiz', level='WARNING') as logs:
            created = await self.create(generator)
        self.assertEqual(created.status, 'failed')
        async with self.factory() as session:
            self.assertEqual((await session.get(QuizSet, created.id)).questions, [])
        self.assertEqual(generator.await_count, 3)
        notify.assert_awaited_once()
        diagnostics = [line for line in logs.output if 'rejected_tokens=' in line]
        self.assertEqual(len(diagnostics), 3)
        self.assertTrue(all('questions[1].explanation' in line and 'english_prose' in line for line in diagnostics))
        self.assertFalse(any(questions[0]['explanation'] in line for line in logs.output))


class QuizLanguageRegressionTests(unittest.TestCase):
    def test_finance_only_options_survive_generation_and_stored_display(self):
        from app.services.quiz_service import _public_question, _note_items
        from datetime import datetime, timezone
        from types import SimpleNamespace
        for term in ('LTV', 'GDP', 'M&A', 'Loan-to-Value ratio',
                     '주택담보인정비율(LTV)', 'The Great Depression', 'LTV 70%'):
            with self.subTest(term=term):
                raw = ltv_questions()
                raw[2]['choices'][0]['text'] = term
                normalized = normalize_questions(raw)
                self.assertEqual(normalized[2]['choices'][0]['text'], term)
                self.assertEqual(_public_question(normalized[2]).choices[0].text, term)
                quiz = SimpleNamespace(id='quiz', learning_session_id='session', concept_id='sisa_2358',
                    stage_id='stage1', created_at=datetime.now(timezone.utc), questions=normalized)
                note = _note_items(quiz, None)[2]
                self.assertEqual(note.choices[0].text, term)
                self.assertEqual([q['answer'] for q in normalized], [q['answer'] for q in raw])

    def test_foreign_clauses_cannot_be_hidden_by_a_korean_ending(self):
        for text in ('Mortgage lenders require stable income입니다.',
                     'Borrowers repay loans every month입니다.',
                     'The LTV is high. 비율을 확인합니다.',
                     'レンタ貧困は、単に家賃が高いという意味だけである。'):
            for field in ('prompt', 'explanation', 'choice'):
                with self.subTest(text=text, field=field):
                    raw = ltv_questions()
                    if field == 'choice': raw[2]['choices'][0]['text'] = text
                    else: raw[0][field] = text
                    with self.assertRaises(QuizLanguageError): normalize_questions(raw)

    def test_terms_do_not_replace_explanations_or_allow_arbitrary_english(self):
        for field in ('prompt', 'explanation'):
            raw = ltv_questions()
            raw[0][field] = 'LTV'
            with self.subTest(field=field):
                with self.assertRaises(QuizLanguageError): normalize_questions(raw)
        for text in ('Unknown confidential wording', 'Unknown wording 70%'):
            raw = ltv_questions()
            raw[2]['choices'][0]['text'] = text
            with self.subTest(text=text):
                with self.assertRaises(QuizLanguageError) as ctx: normalize_questions(raw)
                self.assertEqual(ctx.exception.field, 'questions[3].choices[0].text')
                self.assertEqual(ctx.exception.reason, 'missing_korean_content')

    def test_financial_proper_name_is_preserved_in_korean_prose(self):
        raw = ltv_questions()
        raw[0]['explanation'] = 'The Great Depression은 대공황을 뜻합니다.'
        self.assertEqual(normalize_questions(raw)[0]['explanation'], raw[0]['explanation'])
