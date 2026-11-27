"""The temporary deployment entry point must isolate a one-shot failure."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import run_integration_quiz_failure_test as target


USER = "integration-test-user"
CONCEPT = "sisa_745"
TOKEN = "integration-test-secret-with-at-least-32-characters"


def test_arm_requires_existing_account_and_token(monkeypatch):
    monkeypatch.setenv("INTEGRATION_TEST_USER_ID", USER)
    monkeypatch.setenv("INTEGRATION_TEST_STAGE_TOKEN", TOKEN)
    target._verify_test_account(USER, TOKEN)
    for user, token in ((USER, None), (USER, "wrong"), ("another-user", TOKEN)):
        with pytest.raises(HTTPException) as denied:
            target._verify_test_account(user, token)
        assert denied.value.status_code == 403
    monkeypatch.delenv("INTEGRATION_TEST_STAGE_TOKEN")
    with pytest.raises(HTTPException) as disabled:
        target._verify_test_account(USER, TOKEN)
    assert disabled.value.status_code == 404


def test_failure_is_one_shot_and_scoped_to_user_and_concept(monkeypatch):
    monkeypatch.setattr(target.time, "monotonic", lambda: 100.0)
    with target._lock:
        target._armed.clear()
        target._armed[USER] = (CONCEPT, 100.0 + target.ARM_TTL_SECONDS)
    assert not target._consume_failure("another-user", CONCEPT)
    assert not target._consume_failure(USER, "another-concept")
    assert target._consume_failure(USER, CONCEPT)
    assert not target._consume_failure(USER, CONCEPT)
    with target._lock:
        target._armed[USER] = (CONCEPT, 99.0)
    assert not target._consume_failure(USER, CONCEPT)


def test_only_armed_creation_uses_failing_generator(monkeypatch):
    calls = []

    class NormalService:
        _generator = staticmethod(lambda **_kwargs: None)
        _content_reviewer = staticmethod(lambda **_kwargs: None)

        async def create_quiz_set(self, session, **kwargs):
            calls.append(("normal", kwargs["user_id"], kwargs["concept_id"]))
            return "normal-result"

    class InjectedService:
        def __init__(self, generator, content_reviewer):
            assert content_reviewer is adapter.service._content_reviewer
            self.generator = generator

        async def create_quiz_set(self, session, **kwargs):
            try:
                await self.generator()
            except RuntimeError:
                calls.append(("injected", kwargs["user_id"], kwargs["concept_id"]))
                return "fallback-result"
            raise AssertionError("the armed generator did not fail")

    adapter = SimpleNamespace(service=NormalService())
    monkeypatch.setattr(target, "_normal_register", lambda *_args, **_kwargs: adapter)
    monkeypatch.setattr(target, "QuizService", InjectedService)
    target._register_with_failure_hook(object())
    with target._lock:
        target._armed.clear()
        target._armed[USER] = (CONCEPT, target.time.monotonic() + 600)

    def create(user, concept):
        coroutine = adapter.service.create_quiz_set(
            object(), user_id=user, session_id="new-session", concept_id=concept,
        )
        with pytest.raises(StopIteration) as completed:
            coroutine.send(None)
        return completed.value.value

    assert create("another-user", CONCEPT) == "normal-result"
    assert create(USER, "another-concept") == "normal-result"
    assert create(USER, CONCEPT) == "fallback-result"
    assert create(USER, CONCEPT) == "normal-result"
    assert [call[0] for call in calls] == ["normal", "normal", "injected", "normal"]
