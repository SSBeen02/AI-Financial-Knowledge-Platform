import base64
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pathlib import Path

from app.db import reset_quiz_database

ROOT = Path(__file__).resolve().parents[1]
TEST_DB = ROOT / "data" / "quiz_test.db"
os.environ["QUIZ_DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB.as_posix()}"
reset_quiz_database()

from httpx import ASGITransport, AsyncClient

from app.db import Base, session_scope
from app.models.quiz import QuizSet
from app.services.quiz_service import create_quiz_set, generate_quiz_with_openai
from dependencies import DUMMY_USER_ID
from main import app

SAMPLE_QUESTIONS = [
    {
        "question_index": 1,
        "question_type": "ox",
        "prompt": "복리는 이자에 다시 이자가 붙는 방식이다.",
        "choices": [{"key": "O", "text": "맞다"}, {"key": "X", "text": "틀리다"}],
        "answer": "O",
        "explanation": "복리는 원금과 이전에 붙은 이자에 다시 이자가 붙습니다.",
    },
    {
        "question_index": 2,
        "question_type": "ox",
        "prompt": "단리는 이자를 원금에만 계산한다.",
        "choices": [{"key": "O", "text": "맞다"}, {"key": "X", "text": "틀리다"}],
        "answer": "O",
        "explanation": "단리는 처음 원금에만 이자를 붙입니다.",
    },
    {
        "question_index": 3,
        "question_type": "situation",
        "prompt": "여윳돈을 3년 이상 두지 않을 계획이라면 어떤 선택이 맞을까요?",
        "choices": [
            {"key": "A", "text": "수수료가 큰 장기 상품부터 가입한다."},
            {"key": "B", "text": "필요한 시점과 수수료를 비교해 단기 상품을 고른다."},
            {"key": "C", "text": "수익률만 보고 기간은 확인하지 않는다."},
            {"key": "D", "text": "설명은 듣지 않고 바로 송금한다."},
        ],
        "answer": "B",
        "explanation": "돈을 쓸 시기와 비용을 함께 봐야 합니다.",
    },
]


async def fake_generator(*, concept_id: str, learning_session_id: str, learning_context):
    return json.loads(json.dumps(SAMPLE_QUESTIONS))


async def failing_generator(*, concept_id: str, learning_session_id: str, learning_context):
    raise RuntimeError("generation failed")


def _answers(first: str = "O", second: str = "O", third: str = "B") -> list[dict]:
    return [
        {"question_index": 1, "answer": first},
        {"question_index": 2, "answer": second},
        {"question_index": 3, "answer": third},
    ]


def _bearer(subject: str) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"sub": subject}).encode()).decode().rstrip("=")
    return f"Bearer {header}.{payload}.sig"


def _assert_no_keys(value, banned: set[str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in banned:
                raise AssertionError(key)
            _assert_no_keys(nested, banned)
    elif isinstance(value, list):
        for item in value:
            _assert_no_keys(item, banned)


class QuizModuleTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if TEST_DB.exists():
            TEST_DB.unlink()
        os.environ["QUIZ_DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB.as_posix()}"
        reset_quiz_database()
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        await self.client.__aenter__()

    async def asyncTearDown(self):
        await self.client.__aexit__(None, None, None)
        reset_quiz_database()
        if TEST_DB.exists():
            TEST_DB.unlink()

    async def _create(
        self,
        *,
        concept_id: str = "compound-interest",
        stage_id: str = "stage-1",
        user_id: str = DUMMY_USER_ID,
        session_id: str | None = None,
    ):
        async with session_scope() as session:
            return await create_quiz_set(
                session,
                user_id=user_id,
                session_id=session_id or f"session-{concept_id}",
                concept_id=concept_id,
                learning_context={"stage_id": stage_id, "summary": "복리는 이자에 이자가 붙습니다."},
                generator=fake_generator,
            )

    async def test_concept_groups_fully_filter_tabs_and_exclude_unsubmitted(self):
        await self._create(concept_id="unsubmitted", stage_id="stage1")
        quiz = await self._create(concept_id="group", stage_id="stage1")
        await self.client.post(f"/api/v1/quiz-sets/{quiz.id}/submit", json={"submitted_answers": _answers("X", "O", "B"), "idempotency_key": "group"})
        for mode, indexes in [("all", [1, 2, 3]), ("wrong", [1]), ("correct", [2, 3])]:
            r = await self.client.get("/api/v1/learning-notes/concepts", params={"filter": mode})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["total"], 1)
            group = r.json()["items"][0]
            self.assertEqual(group["concept_id"], "group")
            self.assertEqual([q["question_index"] for q in group["questions"]], indexes)
        other_stage = await self.client.get("/api/v1/learning-notes/concepts", params={"stage_id": "stage5"})
        self.assertEqual(other_stage.json()["total"], 0)

    async def test_review_is_idempotent_and_does_not_change_original_grade(self):
        quiz = await self._create()
        original = await self.client.post(f"/api/v1/quiz-sets/{quiz.id}/submit", json={"submitted_answers": _answers("X", "X", "A"), "idempotency_key": "original"})
        sid = original.json()["submission_id"]
        url = f"/api/v1/learning-notes/submissions/{sid}/questions/1/reviews"
        payload = {"answer": "O", "idempotency_key": "review"}
        first = await self.client.post(url, json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(first.json()["is_correct"])
        second = await self.client.post(url, json=payload)
        self.assertEqual(first.json(), second.json())
        conflict = await self.client.post(url, json={"answer": "X", "idempotency_key": "review"})
        self.assertEqual(conflict.status_code, 409)
        invalid = await self.client.post(url, json={"answer": "Z", "idempotency_key": "invalid"})
        self.assertEqual(invalid.status_code, 422)
        foreign = await self.client.post(url, json=payload, headers={"X-User-Id": "another-user"})
        self.assertEqual(foreign.status_code, 404)
        r = await self.client.get("/api/v1/learning-notes/concepts", params={"filter": "wrong"})
        questions = r.json()["items"][0]["questions"]
        self.assertEqual(len(questions), 3)
        self.assertFalse(questions[0]["is_correct"])
        self.assertFalse(questions[0]["is_passed"])
        self.assertEqual(len(questions[0]["reviews"]), 1)

    # This note aggregation fixture repeats a fake bank; novelty has its own latest tests.
    @patch("app.services.quiz_service._check_new_questions")
    async def test_group_keeps_all_questions_and_merges_same_concept_across_stages(self, _novelty_check):
        # 문항이 20개를 넘어도 개념별 페이지가 탭을 중간에서 자르지 않아야 한다.
        for index in range(8):
            quiz = await self._create(concept_id="same-concept", stage_id="stage1", session_id=f"group-{index}")
            await self.client.post(f"/api/v1/quiz-sets/{quiz.id}/submit", json={"submitted_answers": _answers(), "idempotency_key": f"group-{index}"})
        other = await self._create(concept_id="same-concept", stage_id="stage2", session_id="other-stage")
        await self.client.post(f"/api/v1/quiz-sets/{other.id}/submit", json={"submitted_answers": _answers(), "idempotency_key": "other-stage"})
        r = await self.client.get("/api/v1/learning-notes/concepts")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["total"], 1)
        group = r.json()["items"][0]
        self.assertEqual(set(group["stage_ids"]), {"stage1", "stage2"})
        self.assertEqual(len(group["questions"]), 27)
        r = await self.client.get("/api/v1/learning-notes/concepts", params={"stage_id": "stage1"})
        self.assertEqual(r.json()["total"], 1)
        self.assertEqual(len(r.json()["items"][0]["questions"]), 24)

    async def test_schema_has_no_note_tables(self):
        self.assertEqual(set(Base.metadata.tables), {"quiz_sets", "quiz_submissions", "quiz_reviews"})




    async def test_learning_notes_outer_join_and_filters(self):
        pending = await self._create(concept_id="pending-concept", stage_id="stage-1")
        graded = await self._create(concept_id="graded-concept", stage_id="stage-2")
        submitted = await self.client.post(
            f"/api/v1/quiz-sets/{graded.id}/submit",
            json={"submitted_answers": _answers("O", "X", "A"), "idempotency_key": "notes"},
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)

        notes = await self.client.get("/api/v1/learning-notes")
        self.assertEqual(notes.status_code, 200, notes.text)
        items = notes.json()["items"]
        self.assertEqual(notes.json()["total"], 6)
        unsubmitted = [item for item in items if item["quiz_set_id"] == pending.id]
        self.assertEqual(len(unsubmitted), 3)
        self.assertTrue(all(item["is_correct"] is None for item in unsubmitted))
        self.assertTrue(all(item["submission_id"] is None for item in unsubmitted))
        self.assertTrue(all(item["answer"] is None and item["explanation"] is None for item in unsubmitted))

        wrong = await self.client.get(
            "/api/v1/learning-notes",
            params={"filter": "wrong", "concept_id": "graded-concept"},
        )
        self.assertEqual(wrong.status_code, 200, wrong.text)
        self.assertEqual(wrong.json()["total"], 2)
        self.assertTrue(all(item["is_correct"] is False for item in wrong.json()["items"]))

        correct = await self.client.get(
            "/api/v1/learning-notes",
            params={"filter": "correct", "stage_id": "stage-2"},
        )
        self.assertEqual(correct.json()["total"], 1)
        self.assertEqual(correct.json()["items"][0]["concept_id"], "graded-concept")
        self.assertTrue(correct.json()["items"][0]["is_correct"])

        hidden = await self.client.get("/api/v1/learning-notes", params={"stage_id": "missing"})
        self.assertEqual(hidden.json()["total"], 0)

    async def test_notes_current_status_is_separate_from_historical_wrong_answer(self):
        quiz = await self._create(concept_id="sisa_1281", stage_id="stage1")
        await self.client.post(
            f"/api/v1/quiz-sets/{quiz.id}/submit",
            json={"submitted_answers": _answers("X", "X", "A"), "idempotency_key": "status-notes"},
        )
        reader = AsyncMock(return_value="passed")
        with patch("app.services.quiz_service.get_concept_status", reader):
            response = await self.client.get("/api/v1/learning-notes", params={"filter": "wrong"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total"], 3)
        self.assertTrue(all(item["concept_status"] == "passed" and item["is_correct"] is False
                            and item["is_passed"] is False for item in response.json()["items"]))
        reader.assert_awaited_once_with(user_id=DUMMY_USER_ID, concept_id="sisa_1281", stage_id="stage1")














if __name__ == "__main__":
    unittest.main()
