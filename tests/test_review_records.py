import asyncio
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.api.deps import get_authenticated_user_id
from app.api.v1.endpoints.quiz_reviews import router
from app.db import Base, get_session
from app.errors import register_quiz_exception_handlers
from app.models.quiz import QuizSet, QuizSubmission, QuizReview


def test_review_storage_replay_and_owner_isolation(tmp_path):
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///" + (tmp_path / "reviews.db").as_posix())
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        question = {"question_index": 1, "question_type": "ox", "prompt": "질문",
                    "choices": [{"key": "O", "text": "O"}, {"key": "X", "text": "X"}],
                    "answer": "O", "explanation": "해설"}
        async with factory() as session:
            session.add(QuizSet(id="quiz", user_id="owner", concept_id="concept", stage_id="stage1",
                                learning_session_id="learning", status="completed", questions=[question]))
            await session.flush()
            session.add(QuizSubmission(id="submission", quiz_set_id="quiz", user_id="owner",
                idempotency_key="first", submitted_answers=[{"question_index": 1, "answer": "X"}],
                is_correct_list=[False], correct_count=0, is_passed=False))
            await session.commit()
        app = FastAPI()
        app.include_router(router)
        register_quiz_exception_handlers(app)
        identity = {"user": "owner"}
        app.dependency_overrides[get_authenticated_user_id] = lambda: identity["user"]
        async def session_dependency():
            async with factory() as session:
                yield session
                await session.commit()
        app.dependency_overrides[get_session] = session_dependency
        path = "/api/v1/learning-notes/submissions/submission/questions/1/reviews"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get(path)).json() == []
            body = {"answer": "O", "idempotency_key": "review-one"}
            first = await client.post(path, json=body)
            assert first.status_code == 200
            assert first.json()["is_correct"] is True
            assert (await client.post(path, json=body)).json()["id"] == first.json()["id"]
            assert (await client.post(path, json={**body, "answer": "X"})).status_code == 409
            second = await client.post(path, json={"answer": "X", "idempotency_key": "review-two"})
            assert second.json()["is_correct"] is False
            history = (await client.get(path)).json()
            assert len(history) == 2
            assert history[0]["id"] == second.json()["id"]
            assert history[0]["submitted_answer"] == "X"
            assert (await client.post(path, json={"answer": "Z", "idempotency_key": "bad"})).status_code == 422
            identity["user"] = "other"
            assert (await client.get(path)).status_code == 404
            assert (await client.post(path, json=body)).status_code == 404
        async with factory() as session:
            original = await session.get(QuizSubmission, "submission")
            assert original.submitted_answers == [{"question_index": 1, "answer": "X"}]
            assert original.correct_count == 0 and original.is_passed is False
            assert await session.scalar(select(func.count()).select_from(QuizReview)) == 2
        await engine.dispose()
    asyncio.run(scenario())


def test_status_popup_lists_all_current_stage_concepts(monkeypatch):
    import run_integration as integration
    from fastapi.testclient import TestClient
    app = integration.create_app()
    service = SimpleNamespace(get_current_stage=lambda user: "stage1",
        get_statuses=lambda user, stage: {"a": "passed", "b": "in_progress"})
    catalog = SimpleNamespace(stages={"stage1": SimpleNamespace(concepts=[
        SimpleNamespace(concept_id="a", term="통과 개념"),
        SimpleNamespace(concept_id="b", term="학습 중 개념"),
        SimpleNamespace(concept_id="c", term="미학습 개념"),
    ])})
    app.dependency_overrides[integration.get_verified_user_id] = lambda: "owner"
    app.dependency_overrides[integration.deps.get_concept_status_service] = lambda: service
    app.dependency_overrides[integration.deps.get_stage_catalog] = lambda: catalog
    client = TestClient(app)
    for status, concept in [("passed", "a"), ("in_progress", "b"), ("not_started", "c")]:
        response = client.get("/learning/concept-statuses", params={"status": status})
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["concepts"][0]["concept_id"] == concept
    assert client.get("/learning/concept-statuses", params={"status": "invalid"}).status_code == 422
    assert "/api/v1/learning-notes/submissions/{submission_id}/questions/{question_index}/reviews" in app.openapi()["paths"]
