"""LLM 장애/시간초과에서도 미사용 예비 세트로 저장·채점·학습노트를 연결한다."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models.quiz import QuizSet
from app.services.fallback_bank import FallbackSet, load_fallback_bank, questions_digest, select_fallback_set
from app.services.quiz_service import QuizService, normalize_questions, _check_new_questions
from tests.test_quiz_content import questions


def entry(number=1):
    rows = questions()
    if number == 2:
        rows[0].update(prompt="시간을 한 활동에 쓰면 같은 시간에 할 수 있었던 다른 활동의 편익을 포기하게 됩니다.", answer="O", explanation="하나를 선택하며 포기한 최선의 대안의 편익이 기회비용입니다.")
        rows[1].update(prompt="선택하지 않은 대안이 여러 개라면 그 가치 전부를 합쳐야 기회비용이 됩니다.", answer="X", explanation="포기한 대안 중 가장 가치가 큰 하나의 대안을 기준으로 합니다.")
        rows[2].update(prompt="서로 동시에 할 수 없는 공부, 휴식, 단기 업무 중 단기 업무를 선택했습니다. 포기한 공부의 가치를 휴식보다 높게 평가합니다. 기회비용에 대한 올바른 설명은 무엇입니까?",
            choices=[dict(key="A",text="선택한 업무의 보수 자체입니다."), dict(key="B",text="포기한 공부에서 얻을 수 있었던 가치입니다."), dict(key="C",text="공부와 휴식의 가치의 합입니다."), dict(key="D",text="비교할 대안이 없으므로 항상 0입니다.")], answer="B",
            explanation="포기한 대안인 공부와 휴식 중 더 높게 평가한 공부의 가치가 기회비용입니다.")
    rows = normalize_questions(rows)
    return dict(set_id=f"sisa_745-test-{number}", concept_id="sisa_745", stage_id="stage3", concept_name="기회비용", questions=rows,
        verification=dict(status="source_and_model_checked", verified_on="2026-11-26", model="fixture", source_url="https://www.stlouisfed.org/", source_title="fixture", source_sha256="a"*64, questions_sha256=questions_digest(rows), human_reviewed=False))


class BankSelectionTests(unittest.TestCase):
    def setUp(self):
        load_fallback_bank.cache_clear()
    def tearDown(self):
        load_fallback_bank.cache_clear()

    def select(self, **kwargs):
        return select_fallback_set(concept_id=kwargs.get("concept_id","sisa_745"), stage_id=kwargs.get("stage_id","stage3"),
            previous_questions=kwargs.get("previous",[]), normalizer=normalize_questions, novelty_checker=_check_new_questions)

    def test_exact_concept_and_stage_and_unseen_questions(self):
        rows=[FallbackSet.model_validate(entry(1)),FallbackSet.model_validate(entry(2))]
        with patch("app.services.fallback_bank.load_fallback_bank",return_value=rows):
            first=self.select()
            second=self.select(previous=first[1])
            self.assertEqual((first[0],second[0]),("sisa_745-test-1","sisa_745-test-2"))
            self.assertIsNone(self.select(previous=first[1]+second[1]))
            self.assertIsNone(self.select(stage_id="stage2"))
            self.assertIsNone(self.select(concept_id="sisa_2358"))
            self.assertIsNone(self.select(stage_id=None))
            first[1][0]["answer"]="X"
            self.assertEqual(self.select()[1][0]["answer"],"O")

    def test_tampered_unreviewed_and_malformed_entries_are_excluded(self):
        valid=entry()
        tampered=copy.deepcopy(valid);tampered["questions"][0]["answer"]="X"
        draft=copy.deepcopy(valid);draft["verification"]["status"]="draft"
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"bank.json"
            path.write_text(json.dumps({"schema_version":1,"sets":[tampered,draft,{"bad":"entry"},valid]},ensure_ascii=False),encoding="utf-8")
            with patch("app.services.fallback_bank.BANK_PATH",path):
                loaded=load_fallback_bank()
            self.assertEqual([r.set_id for r in loaded],[valid["set_id"]])

    def test_missing_bank_does_not_publish_a_fabricated_default(self):
        with patch("app.services.fallback_bank.load_fallback_bank",side_effect=FileNotFoundError):
            self.assertIsNone(self.select())


class FallbackServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="quiz-fallback-")
        self.engine=create_async_engine("sqlite+aiosqlite:///"+(Path(self.temp.name)/"test.db").as_posix())
        async with self.engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
        self.factory=async_sessionmaker(self.engine,expire_on_commit=False)
        self.fail_notify=AsyncMock()
        self.patches=[patch("app.services.quiz_service.report_quiz_generation_failed",self.fail_notify),
            patch("app.services.fallback_bank.load_fallback_bank",return_value=tuple(FallbackSet.model_validate(entry(i)) for i in (1,2)))]
        for p in self.patches:p.start();self.addCleanup(p.stop)

    async def asyncTearDown(self):
        await self.engine.dispose();self.temp.cleanup()

    async def create(self,service,session_id="one",user="owner",concept="sisa_745",stage="stage3"):
        async with self.factory() as session:
            result=await service.create_quiz_set(session,user_id=user,session_id=session_id,concept_id=concept,stage_id=stage,learning_context="기회비용 학습 자료")
            saved=await session.get(QuizSet,result.id)
            return result,copy.deepcopy(saved.questions)

    async def test_transport_failure_uses_bank_without_review_api_and_supports_grading_notes(self):
        generator=AsyncMock(side_effect=RuntimeError("offline"));reviewer=AsyncMock(side_effect=AssertionError("LLM forbidden"))
        service=QuizService(generator,content_reviewer=reviewer)
        result,saved=await self.create(service)
        self.assertEqual((result.status,len(saved)),("completed",3))
        generator.assert_awaited_once();reviewer.assert_not_awaited();self.fail_notify.assert_not_awaited()

    async def test_stored_bank_set_has_same_grade_and_learning_note_contract(self):
        service=QuizService(AsyncMock(side_effect=RuntimeError("offline")))
        result,saved=await self.create(service)
        with patch("app.services.quiz_service.report_quiz_result",AsyncMock()):
            async with self.factory() as session:
                graded=await service.submit_quiz_answers(session,user_id="owner",quiz_set_id=result.id,
                    submitted_answers=[dict(question_index=q["question_index"],answer=q["answer"]) for q in saved],idempotency_key="answer")
                replay=await service.submit_quiz_answers(session,user_id="owner",quiz_set_id=result.id,
                    submitted_answers=[dict(question_index=q["question_index"],answer="X") for q in saved],idempotency_key="another-key")
                notes=await service.list_learning_notes(session,user_id="owner",stage_id=None,concept_id=None,note_filter="all",page=1)
                public=await service.get_quiz_set(session,quiz_set_id=result.id,user_id="owner")
        self.assertEqual(graded.correct_count,3)
        self.assertEqual(replay.submission_id,graded.submission_id)
        self.assertEqual(len(notes.items),3)
        self.assertNotIn("answer",public.questions[0].model_dump())

    async def test_history_rotation_exhaustion_and_other_user_isolation(self):
        service=QuizService(AsyncMock(side_effect=RuntimeError("offline")))
        first,one=await self.create(service,"first")
        second,two=await self.create(service,"second")
        third,none=await self.create(service,"third")
        other,again=await self.create(service,"other",user="another-user")
        self.assertEqual([first.status,second.status,third.status,other.status],["completed","completed","failed","completed"])
        self.assertNotEqual(one,two);self.assertEqual(one,again);self.assertEqual(none,[])
        self.fail_notify.assert_awaited_once_with("third",user_id="owner")

    async def test_same_session_does_not_consume_another_bank_set(self):
        generator=AsyncMock(side_effect=RuntimeError("offline"));service=QuizService(generator)
        first,one=await self.create(service)
        same,two=await self.create(service)
        self.assertEqual(first.id,same.id);self.assertEqual(one,two);generator.assert_awaited_once()

    async def test_generation_deadline_can_fall_back_without_any_extra_model_call(self):
        cancelled=asyncio.Event()
        async def slow(**kwargs):
            try:await asyncio.sleep(10)
            finally:cancelled.set()
        reviewer=AsyncMock(side_effect=AssertionError("no live review of bank"))
        with patch("app.services.quiz_service.GENERATION_TIMEOUT_SECONDS",.03):
            result,rows=await self.create(QuizService(slow,content_reviewer=reviewer))
        self.assertTrue(cancelled.is_set());self.assertEqual((result.status,len(rows)),("completed",3));reviewer.assert_not_awaited()

    async def test_unknown_concept_or_wrong_stage_preserves_failed_behavior(self):
        service=QuizService(AsyncMock(side_effect=RuntimeError("offline")))
        unknown,none=await self.create(service,"unknown",concept="not-in-bank")
        wrong,also_none=await self.create(service,"wrong",stage="stage2")
        self.assertEqual((unknown.status,none,wrong.status,also_none),("failed",[],"failed",[]))


class FullBankCoverageTests(unittest.TestCase):
    def test_all_180_concepts_have_two_valid_nonrepeated_sets(self):
        load_fallback_bank.cache_clear()
        bank=load_fallback_bank()
        self.assertEqual(len(bank),360)
        grouped={}
        for row in bank:
            normalized=normalize_questions([q.model_dump() for q in row.questions])
            self.assertEqual(row.verification.questions_sha256,questions_digest(normalized))
            grouped.setdefault((row.stage_id,row.concept_id),[]).append(normalized)
        self.assertEqual(len(grouped),180)
        self.assertEqual({s:sum(k[0]==s for k in grouped) for s in ["stage1","stage2","stage3","stage4"]},{"stage1":30,"stage2":40,"stage3":50,"stage4":60})
        for key,sets in grouped.items():
            with self.subTest(concept=key):
                self.assertEqual(len(sets),2)
                _check_new_questions(sets[0],sets[1])
        catalog=Path(__file__).resolve().parents[2]/"rag/chatbot_module/data/stages.json"
        if catalog.exists():
            data=json.loads(catalog.read_text(encoding="utf-8"))
            expected={(s["id"],c["concept_id"]) for s in data["stages"][:4] for c in s["concepts"]}
            self.assertEqual(set(grouped),expected)


class FullBankServiceMatrixTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_catalog_concept_can_complete_from_its_own_bank_without_llm(self):
        load_fallback_bank.cache_clear()
        bank=load_fallback_bank()
        concepts={(row.stage_id,row.concept_id) for row in bank}
        self.assertEqual(len(concepts),180)
        engine=create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:await conn.run_sync(Base.metadata.create_all)
            factory=async_sessionmaker(engine,expire_on_commit=False)
            generator=AsyncMock(side_effect=RuntimeError("offline"))
            reviewer=AsyncMock(side_effect=AssertionError("fallback must not need an LLM"))
            service=QuizService(generator,content_reviewer=reviewer)
            failed=AsyncMock()
            with patch("app.services.quiz_service.report_quiz_generation_failed",failed):
                for stage,cid in sorted(concepts):
                    async with factory() as session:
                        result=await service.create_quiz_set(session,user_id="matrix-user",session_id=cid,concept_id=cid,
                            stage_id=stage,learning_context="로컬 시험용 미사용 학습 자료")
                        self.assertEqual(result.status,"completed",(stage,cid))
                        stored=await session.get(QuizSet,result.id)
                        self.assertEqual(stored.concept_id,cid)
                        self.assertEqual(stored.stage_id,stage)
                        self.assertEqual(len(stored.questions),3)
            self.assertEqual(generator.await_count,180)
            reviewer.assert_not_awaited();failed.assert_not_awaited()
        finally:
            await engine.dispose()
