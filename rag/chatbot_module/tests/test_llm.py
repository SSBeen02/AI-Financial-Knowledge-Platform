from __future__ import annotations

from types import SimpleNamespace

import pytest

from chatbot.config import Settings
from chatbot.llm import (
    FakeLLMAdapter,
    LLMConfigurationError,
    LLMError,
    OpenAIAdapter,
    supports_temperature,
)
from chatbot.prompts import Prompt


class Responses:
    def __init__(self, output: str = "답변") -> None:
        self.output = output
        self.calls: list[dict] = []
        self.error: Exception | None = None

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(output_text=self.output)


class StreamContext:
    def __init__(self, events: list[object]) -> None:
        self.events = events

    def __enter__(self):
        return iter(self.events)

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class StreamingResponses(Responses):
    def __init__(self, events: list[object]) -> None:
        super().__init__()
        self.events = events
        self.stream_calls: list[dict] = []

    def stream(self, **kwargs):
        self.stream_calls.append(kwargs)
        return StreamContext(self.events)


def _settings(**kwargs) -> Settings:
    return Settings(
        _env_file=None,
        llm_model="gpt-test",
        llm_api_key="test-key",
        **kwargs,
    )


def test_openai_adapter_omits_blank_reasoning_effort() -> None:
    responses = Responses()
    adapter = OpenAIAdapter(_settings(llm_reasoning_effort=""), client=SimpleNamespace(responses=responses))
    assert adapter.generate(Prompt("지시", "입력")) == "답변"
    call = responses.calls[0]
    assert call["model"] == "gpt-test"
    assert call["instructions"] == "지시"
    assert call["input"] == "입력"
    assert call["max_output_tokens"] == 1200
    assert call["store"] is False
    assert "reasoning" not in call
    assert call["temperature"] == 0.7


def test_openai_adapter_passes_configured_reasoning_effort() -> None:
    responses = Responses()
    adapter = OpenAIAdapter(_settings(llm_reasoning_effort="low"), client=SimpleNamespace(responses=responses))
    adapter.generate(Prompt("지시", "입력"))
    assert responses.calls[0]["reasoning"] == {"effort": "low"}
    assert "temperature" not in responses.calls[0]


def test_openai_adapter_passes_configured_temperature_to_supported_model() -> None:
    responses = Responses()
    adapter = OpenAIAdapter(
        _settings(llm_temperature=0.35), client=SimpleNamespace(responses=responses)
    )
    adapter.generate(Prompt("지시", "입력"))
    assert responses.calls[0]["temperature"] == 0.35


@pytest.mark.parametrize(
    ("model", "reasoning_effort", "expected"),
    [
        ("gpt-4.1-mini", "", True),
        ("gpt-5.6-luna", "", False),
        ("gpt-5.6-luna", "low", False),
        ("gpt-5.6-luna", "none", True),
        ("o3-mini", "", False),
    ],
)
def test_temperature_support_rule(
    model: str, reasoning_effort: str, expected: bool
) -> None:
    assert supports_temperature(model=model, reasoning_effort=reasoning_effort) is expected


def test_relevance_uses_fallback_model_and_yes_no() -> None:
    responses = Responses("yes")
    adapter = OpenAIAdapter(
        _settings(llm_relevance_model="gpt-relevance"), client=SimpleNamespace(responses=responses)
    )
    assert adapter.judge_relevance(question="질문", current_term="분업", history=[]) is True
    assert responses.calls[0]["model"] == "gpt-relevance"
    assert responses.calls[0]["max_output_tokens"] == 128
    assert "최근 대화" in responses.calls[0]["input"]
    assert "temperature" not in responses.calls[0]


def test_openai_adapter_wraps_external_and_empty_responses() -> None:
    responses = Responses()
    responses.error = RuntimeError("secret provider detail")
    adapter = OpenAIAdapter(_settings(), client=SimpleNamespace(responses=responses))
    with pytest.raises(LLMError, match="LLM 호출에 실패"):
        adapter.generate(Prompt("지시", "입력"))

    empty = OpenAIAdapter(
        _settings(), client=SimpleNamespace(responses=Responses("   "))
    )
    with pytest.raises(LLMError, match="비어 있는 응답"):
        empty.generate(Prompt("지시", "입력"))


def test_openai_adapter_streams_text_deltas() -> None:
    responses = StreamingResponses(
        [
            SimpleNamespace(type="response.created"),
            SimpleNamespace(type="response.output_text.delta", delta="첫 "),
            SimpleNamespace(type="response.output_text.delta", delta="답변"),
            SimpleNamespace(type="response.completed"),
        ]
    )
    adapter = OpenAIAdapter(_settings(), client=SimpleNamespace(responses=responses))
    assert list(adapter.stream(Prompt("지시", "입력"))) == ["첫 ", "답변"]
    assert responses.stream_calls[0]["store"] is False


@pytest.mark.parametrize(
    "events",
    [
        [SimpleNamespace(type="response.failed")],
        [SimpleNamespace(type="response.completed")],
    ],
)
def test_openai_adapter_stream_rejects_failed_or_empty_response(events: list[object]) -> None:
    adapter = OpenAIAdapter(
        _settings(),
        client=SimpleNamespace(responses=StreamingResponses(events)),
    )
    with pytest.raises(LLMError):
        list(adapter.stream(Prompt("지시", "입력")))


def test_openai_adapter_requires_key_and_provider() -> None:
    with pytest.raises(LLMConfigurationError, match="LLM_API_KEY"):
        OpenAIAdapter(Settings(_env_file=None, llm_model="gpt-test"), client=object())
    with pytest.raises(LLMConfigurationError, match="LLM_PROVIDER"):
        OpenAIAdapter(
            Settings(
                _env_file=None,
                llm_model="gpt-test",
                llm_api_key="key",
                llm_provider="other",
            ),
            client=object(),
        )


def test_fake_adapter_returns_deterministic_answer_without_external_client() -> None:
    adapter = FakeLLMAdapter()
    prompt = Prompt("지시", "입력")
    answer = "개발용 가짜 답변이오. 실제 OpenAI 호출은 이루어지지 않았소."
    assert adapter.generate(prompt) == answer
    assert list(adapter.stream(prompt)) == [answer]
    assert adapter.judge_relevance(
        question="분업을 더 알려줘", current_term="분업", history=[]
    ) is True
    assert adapter.judge_relevance(
        question="인플레이션을 알려줘", current_term="분업", history=[]
    ) is False
    modern = FakeLLMAdapter(_settings(chat_tone="modern"))
    assert modern.generate(prompt).endswith("이루어지지 않았어요.")
