"""교체 가능한 LLM 어댑터와 OpenAI Responses API 구현."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from chatbot.config import Settings
from chatbot.prompts import HistoryTurn, Prompt, build_relevance_prompt


def supports_temperature(*, model: str, reasoning_effort: str) -> bool:
    """Return whether answer requests may safely include temperature.

    OpenAI reasoning requests with a non-``none`` effort reject sampling
    controls. GPT-5+ models are treated as reasoning models unless reasoning
    is explicitly disabled; older ``o`` reasoning models omit it entirely.
    """

    normalized_model = model.strip().casefold()
    normalized_effort = reasoning_effort.strip().casefold()
    if normalized_effort and normalized_effort != "none":
        return False
    if normalized_model.startswith(("o1", "o3", "o4")):
        return False
    if normalized_model.startswith(("gpt-5", "gpt-6")):
        return normalized_effort == "none"
    return True


class LLMError(Exception):
    """LLM 외부 호출 또는 응답 해석 실패."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class LLMConfigurationError(LLMError):
    """LLM 설정이 없어 요청을 시작할 수 없을 때."""


class LLMAdapter(ABC):
    @abstractmethod
    def generate(self, prompt: Prompt) -> str: ...

    @abstractmethod
    def stream(self, prompt: Prompt) -> Iterator[str]: ...

    @abstractmethod
    def judge_relevance(
        self,
        *,
        question: str,
        current_term: str,
        history: list[HistoryTurn],
    ) -> bool: ...


class OpenAIAdapter(LLMAdapter):
    """공식 OpenAI Python SDK의 Responses API를 사용한다."""

    def __init__(self, settings: Settings, *, client: Any | None = None):
        if settings.llm_provider.casefold() != "openai":
            raise LLMConfigurationError(f"지원하지 않는 LLM_PROVIDER입니다: {settings.llm_provider}")
        if not settings.llm_api_key.strip():
            raise LLMConfigurationError("LLM_API_KEY 환경변수를 지정해야 합니다.")
        self._settings = settings
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=settings.llm_api_key)
        self._client = client

    def generate(self, prompt: Prompt) -> str:
        return self._create(
            model=self._settings.llm_model,
            prompt=prompt,
            max_output_tokens=self._settings.llm_max_output_tokens,
            use_temperature=True,
        )

    def stream(self, prompt: Prompt) -> Iterator[str]:
        kwargs = self._request_kwargs(
            model=self._settings.llm_model,
            prompt=prompt,
            max_output_tokens=self._settings.llm_max_output_tokens,
            use_temperature=True,
        )
        received_text = False
        try:
            with self._client.responses.stream(**kwargs) as stream:
                for event in stream:
                    event_type = getattr(event, "type", "")
                    if event_type in {"response.failed", "response.incomplete"}:
                        raise LLMError("LLM 스트리밍 호출에 실패했습니다.")
                    if event_type != "response.output_text.delta":
                        continue
                    delta = str(getattr(event, "delta", "") or "")
                    if delta:
                        received_text = True
                        yield delta
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError("LLM 스트리밍 호출에 실패했습니다.") from exc
        if not received_text:
            raise LLMError("LLM이 비어 있는 응답을 반환했습니다.")

    def judge_relevance(
        self,
        *,
        question: str,
        current_term: str,
        history: list[HistoryTurn],
    ) -> bool:
        prompt = build_relevance_prompt(
            question=question,
            current_term=current_term,
            history=history,
        )
        text = self._create(
            model=self._settings.relevance_model,
            prompt=prompt,
            max_output_tokens=min(self._settings.llm_max_output_tokens, 128),
            use_temperature=False,
        )
        normalized = text.strip().casefold()
        return normalized.startswith("yes") or normalized.startswith("예")

    def _create(
        self,
        *,
        model: str,
        prompt: Prompt,
        max_output_tokens: int,
        use_temperature: bool,
    ) -> str:
        kwargs = self._request_kwargs(
            model=model,
            prompt=prompt,
            max_output_tokens=max_output_tokens,
            use_temperature=use_temperature,
        )
        try:
            response = self._client.responses.create(**kwargs)
        except Exception as exc:
            raise LLMError("LLM 호출에 실패했습니다.") from exc
        output = str(getattr(response, "output_text", "") or "").strip()
        if not output:
            raise LLMError("LLM이 비어 있는 응답을 반환했습니다.")
        return output

    def _request_kwargs(
        self,
        *,
        model: str,
        prompt: Prompt,
        max_output_tokens: int,
        use_temperature: bool,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": prompt.instructions,
            "input": prompt.input,
            "max_output_tokens": max_output_tokens,
            "store": False,
        }
        if self._settings.llm_reasoning_effort:
            kwargs["reasoning"] = {"effort": self._settings.llm_reasoning_effort}
        if use_temperature and supports_temperature(
            model=model,
            reasoning_effort=self._settings.llm_reasoning_effort,
        ):
            kwargs["temperature"] = self._settings.llm_temperature
        return kwargs


class FakeLLMAdapter(LLMAdapter):
    """프론트 개발과 테스트에서 외부 호출 없이 쓰는 결정적 어댑터."""

    def __init__(self, settings: Settings | None = None):
        self._answer = (
            "개발용 가짜 답변이에요. 실제 OpenAI 호출은 이루어지지 않았어요."
            if settings is not None and settings.chat_tone == "modern"
            else "개발용 가짜 답변이오. 실제 OpenAI 호출은 이루어지지 않았소."
        )

    def generate(self, prompt: Prompt) -> str:
        del prompt
        return self._answer

    def stream(self, prompt: Prompt) -> Iterator[str]:
        del prompt
        yield self._answer

    def judge_relevance(
        self,
        *,
        question: str,
        current_term: str,
        history: list[HistoryTurn],
    ) -> bool:
        del history
        return current_term.casefold() in question.casefold()
