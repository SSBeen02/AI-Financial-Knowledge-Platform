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

    async def test_schema_has_no_note_tables(self):
        self.assertEqual(set(Base.metadata.tables), {"quiz_sets", "quiz_submissions"})

    async def test_get_hides_answer_and_explanation(self):
        created = await self._create()
        response = await self.client.get(f"/api/v1/quiz-sets/{created.id}")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(len(body["questions"]), 3)
        self.assertEqual([item["question_type"] for item in body["questions"]], ["ox", "ox", "situation"])
        self.assertEqual(body["questions"][0]["choices"][0]["key"], "O")
        _assert_no_keys(body, {"answer", "explanation"})
        self.assertNotIn("user_id", body)

        spec = (await self.client.get("/openapi.json")).json()
        submit_schema = spec["paths"]["/api/v1/quiz-sets/{id}/submit"]["post"]["requestBody"]
        schema_name = submit_schema["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
        properties = spec["components"]["schemas"][schema_name]["properties"]
        self.assertNotIn("user_id", properties)
        self.assertIn("idempotency_key", properties)
        self.assertIn("submitted_answers", properties)

    async def test_pass_threshold_and_idempotency(self):
        created = await self._create()
        passed = await self.client.post(
            f"/api/v1/quiz-sets/{created.id}/submit",
            json={"submitted_answers": _answers(), "idempotency_key": "submit-1"},
        )
        self.assertEqual(passed.status_code, 200, passed.text)
        body = passed.json()
        self.assertEqual(body["correct_count"], 3)
        self.assertTrue(body["is_passed"])
        self.assertEqual(body["is_correct_list"], [True, True, True])
        self.assertEqual(body["results"][2]["explanation"], SAMPLE_QUESTIONS[2]["explanation"])
        self.assertEqual(
            body["learning_module_result"],
            {
                "submission_id": body["submission_id"],
                "concept_id": "compound-interest",
                "correct_count": 3,
                "is_passed": True,
            },
        )

        replay = await self.client.post(
            f"/api/v1/quiz-sets/{created.id}/submit",
            json={"submitted_answers": _answers("X", "X", "A"), "idempotency_key": "submit-1"},
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["submission_id"], body["submission_id"])
        self.assertEqual(replay.json()["correct_count"], 3)

        other = await self._create(concept_id="simple-interest")
        conflict = await self.client.post(
            f"/api/v1/quiz-sets/{other.id}/submit",
            json={"submitted_answers": _answers(), "idempotency_key": "submit-1"},
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(set(conflict.json()), {"code", "message", "request_id"})
        self.assertEqual(conflict.json()["code"], "IDEMPOTENCY_CONFLICT")

    async def test_two_correct_passes_and_one_correct_fails(self):
        created = await self._create()
        passed = await self.client.post(
            f"/api/v1/quiz-sets/{created.id}/submit",
            json={"submitted_answers": _answers("O", "X", "B"), "idempotency_key": "two"},
        )
        self.assertEqual(passed.status_code, 200, passed.text)
        self.assertEqual(passed.json()["correct_count"], 2)
        self.assertTrue(passed.json()["is_passed"])

        failed = await self.client.post(
            f"/api/v1/quiz-sets/{created.id}/submit",
            json={"submitted_answers": _answers("X", "X", "B"), "idempotency_key": "one"},
        )
        self.assertEqual(failed.status_code, 200, failed.text)
        self.assertEqual(failed.json()["correct_count"], 1)
        self.assertFalse(failed.json()["is_passed"])
        self.assertFalse(failed.json()["learning_module_result"]["is_passed"])

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

    async def test_generation_failure_returns_failed_without_passing(self):
        notices: list[str] = []

        async def capture(session_id: str, *, user_id: str) -> None:
            notices.append(session_id)

        import app.services.quiz_service as quiz_service

        original = quiz_service.report_quiz_generation_failed
        quiz_service.report_quiz_generation_failed = capture
        try:
            async with session_scope() as session:
                created = await create_quiz_set(
                    session,
                    user_id=DUMMY_USER_ID,
                    session_id="session-1",
                    concept_id="inflation",
                    learning_context="물가가 오르면 돈의 가치가 떨어집니다.",
                    generator=failing_generator,
                )
        finally:
            quiz_service.report_quiz_generation_failed = original

        self.assertEqual(created.status, "failed")
        self.assertEqual(notices, ["session-1"])

        async with session_scope() as session:
            quiz = await session.get(QuizSet, created.id)
            self.assertIsNotNone(quiz)
            self.assertEqual(quiz.status, "failed")
            self.assertEqual(quiz.questions, [])

        missing = await self.client.get(f"/api/v1/quiz-sets/{created.id}")
        self.assertEqual(missing.status_code, 200)
        self.assertEqual(missing.json()["status"], "failed")
        self.assertEqual(missing.json()["questions"], [])

        blocked = await self.client.post(
            f"/api/v1/quiz-sets/{created.id}/submit",
            json={"submitted_answers": _answers(), "idempotency_key": "failed"},
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["code"], "QUIZ_NOT_READY")

    async def test_same_session_returns_the_existing_three_questions(self):
        calls = {"count": 0}

        async def counting_generator(*, concept_id: str, learning_session_id: str, learning_context):
            calls["count"] += 1
            return json.loads(json.dumps(SAMPLE_QUESTIONS))

        async with session_scope() as session:
            first = await create_quiz_set(
                session,
                user_id=DUMMY_USER_ID,
                session_id="session-replay",
                concept_id="compound-interest",
                learning_context={"stage_id": "stage-1", "summary": "복리"},
                generator=counting_generator,
            )
        async with session_scope() as session:
            second = await create_quiz_set(
                session,
                user_id=DUMMY_USER_ID,
                session_id="session-replay",
                concept_id="compound-interest",
                learning_context={"stage_id": "stage-1", "summary": "복리"},
                generator=counting_generator,
            )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(second.id, first.id)
        self.assertEqual(second.quiz_set_id, first.id)
        self.assertEqual(second.status, "completed")
        response = await self.client.get(f"/api/v1/quiz-sets/{second.id}")
        self.assertEqual(len(response.json()["questions"]), 3)

    async def test_failed_session_returns_the_same_failure(self):
        calls = {"count": 0}
        notices: list[str] = []

        async def counting_failure(*, concept_id: str, learning_session_id: str, learning_context):
            calls["count"] += 1
            raise RuntimeError("generation failed")

        async def capture(session_id: str, *, user_id: str) -> None:
            notices.append(session_id)

        import app.services.quiz_service as quiz_service

        original = quiz_service.report_quiz_generation_failed
        quiz_service.report_quiz_generation_failed = capture
        try:
            async with session_scope() as session:
                first = await create_quiz_set(
                    session,
                    user_id=DUMMY_USER_ID,
                    session_id="session-failed",
                    concept_id="inflation",
                    learning_context="물가",
                    generator=counting_failure,
                )
            async with session_scope() as session:
                replay = await create_quiz_set(
                    session,
                    user_id=DUMMY_USER_ID,
                    session_id="session-failed",
                    concept_id="inflation",
                    learning_context="물가",
                    generator=counting_failure,
                )
        finally:
            quiz_service.report_quiz_generation_failed = original

        self.assertEqual(calls["count"], 1)
        self.assertEqual(notices, ["session-failed"])
        self.assertEqual(replay.id, first.id)
        self.assertEqual(replay.status, "failed")
        self.assertEqual(replay.quiz_set_id, first.quiz_set_id)

    async def test_retry_session_reports_the_new_session_id(self):
        reports: list[dict] = []

        async def capture(**payload) -> None:
            reports.append(payload)

        import app.services.quiz_service as quiz_service

        original = quiz_service.report_quiz_result
        quiz_service.report_quiz_result = capture
        try:
            async with session_scope() as session:
                created = await create_quiz_set(
                    session,
                    user_id=DUMMY_USER_ID,
                    session_id="retry-session",
                    concept_id="compound-interest",
                    stage_id="stage-2",
                    learning_context={"stage_id": "stage-1", "summary": "복리"},
                    reference_chunk_ids=["chunk-1"],
                    generator=fake_generator,
                )
            submitted = await self.client.post(
                f"/api/v1/quiz-sets/{created.id}/submit",
                json={"submitted_answers": _answers(), "idempotency_key": "retry-grade"},
            )
        finally:
            quiz_service.report_quiz_result = original

        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(created.stage_id, "stage-2")
        self.assertEqual(reports[0]["session_id"], "retry-session")
        self.assertEqual(reports[0]["concept_id"], "compound-interest")
        self.assertEqual(reports[0]["stage_id"], "stage-2")
        self.assertEqual(reports[0]["submission_id"], submitted.json()["submission_id"])
        self.assertEqual(reports[0]["correct_count"], submitted.json()["correct_count"])
        self.assertEqual(reports[0]["passed"], submitted.json()["is_passed"])

    async def test_unknown_quiz_and_foreign_user_use_error_shape(self):
        created = await self._create(user_id="owner-1")
        missing = await self.client.get(
            "/api/v1/quiz-sets/missing",
            headers={"X-Request-Id": "req-quiz-404"},
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(
            missing.json(),
            {
                "code": "QUIZ_SET_NOT_FOUND",
                "message": "퀴즈를 찾을 수 없습니다.",
                "request_id": "req-quiz-404",
            },
        )

        foreign = await self.client.get(f"/api/v1/quiz-sets/{created.id}")
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(foreign.json()["code"], "QUIZ_SET_NOT_FOUND")

        owned = await self.client.get(f"/api/v1/quiz-sets/{created.id}", headers={"X-User-Id": "owner-1"})
        self.assertEqual(owned.status_code, 200, owned.text)

        rejected = await self.client.post(
            f"/api/v1/quiz-sets/{created.id}/submit",
            headers={"X-User-Id": "owner-1"},
            json={"user_id": "owner-1", "submitted_answers": _answers(), "idempotency_key": "body-user"},
        )
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(rejected.json()["code"], "VALIDATION_ERROR")
        self.assertNotIn("detail", rejected.json())

    async def test_bearer_subject_identifies_the_user(self):
        created = await self._create(user_id="auth-user")
        response = await self.client.get(
            f"/api/v1/quiz-sets/{created.id}",
            headers={"Authorization": _bearer("auth-user")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["concept_id"], "compound-interest")

    async def test_processing_quiz_does_not_leak_a_stored_answer(self):
        async with session_scope() as session:
            quiz = QuizSet(
                user_id=DUMMY_USER_ID,
                concept_id="draft",
                learning_session_id="session-1",
                questions=[{"question_index": 1, "answer": "O", "explanation": "숨김"}],
                status="processing",
            )
            session.add(quiz)
            await session.commit()
            quiz_id = quiz.id

        response = await self.client.get(f"/api/v1/quiz-sets/{quiz_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "processing")
        self.assertEqual(response.json()["questions"], [])
        _assert_no_keys(response.json(), {"answer", "explanation"})

    async def test_openai_request_uses_env_key_model_and_schema(self):
        from app.schemas.quiz import GeneratedQuizPayload
        parsed = GeneratedQuizPayload(questions=SAMPLE_QUESTIONS)
        parse = AsyncMock(return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed, refusal=None))]
        ))
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.beta.chat.completions.parse = parse
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key-not-real", "OPENAI_MODEL": "gpt-4o-mini"}), \
                patch("app.services.quiz_service.AsyncOpenAI", return_value=client) as factory:
            questions = await generate_quiz_with_openai(
                concept_id="compound-interest",
                learning_session_id="session-9",
                learning_context="복리 설명",
            )
        factory.assert_called_once_with(api_key="test-key-not-real", timeout=40.0, max_retries=1)
        self.assertEqual(questions, SAMPLE_QUESTIONS)
        args = parse.call_args.kwargs
        self.assertEqual(args["model"], "gpt-4o-mini")
        self.assertIs(args["response_format"], GeneratedQuizPayload)
        self.assertIn("compound-interest", args["messages"][1]["content"])
        self.assertIn("session-9", args["messages"][1]["content"])
        self.assertIn("복리 설명", args["messages"][1]["content"])
        self.assertNotIn("test-key-not-real", json.dumps(args["messages"]))

    async def test_openai_rejects_empty_refused_and_unparsed_responses(self):
        for completion in (
            SimpleNamespace(choices=[]),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=None, refusal="refused"))]),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=None, refusal=None))]),
        ):
            with self.subTest(completion=completion):
                client = AsyncMock()
                client.__aenter__.return_value = client
                client.beta.chat.completions.parse = AsyncMock(return_value=completion)
                with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key-not-real"}), \
                        patch("app.services.quiz_service.AsyncOpenAI", return_value=client):
                    with self.assertRaises(RuntimeError):
                        await generate_quiz_with_openai(
                            concept_id="compound-interest", learning_session_id="session-9", learning_context="복리 설명",
                        )

    async def test_openai_missing_key_does_not_request_generation(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}), \
                patch("app.services.quiz_service.AsyncOpenAI") as factory:
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                await generate_quiz_with_openai(
                    concept_id="compound-interest", learning_session_id="session-9", learning_context="복리 설명",
                )
            factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
