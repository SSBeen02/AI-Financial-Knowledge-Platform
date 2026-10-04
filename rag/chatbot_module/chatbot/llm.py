"""교체 가능한 LLM 어댑터와 OpenAI Responses API 구현."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from chatbot.config import Settings
from chatbot.prompts import Prompt, build_relevance_prompt


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
    def judge_relevance(self, *, question: str, current_term: str) -> bool: ...


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
        )

    def stream(self, prompt: Prompt) -> Iterator[str]:
        kwargs = self._request_kwargs(
            model=self._settings.llm_model,
            prompt=prompt,
            max_output_tokens=self._settings.llm_max_output_tokens,
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

    def judge_relevance(self, *, question: str, current_term: str) -> bool:
        prompt = build_relevance_prompt(question=question, current_term=current_term)
        text = self._create(
            model=self._settings.relevance_model,
            prompt=prompt,
            max_output_tokens=min(self._settings.llm_max_output_tokens, 128),
        )
        normalized = text.strip().casefold()
        return normalized.startswith("yes") or normalized.startswith("예")

    def _create(self, *, model: str, prompt: Prompt, max_output_tokens: int) -> str:
        kwargs = self._request_kwargs(
            model=model,
            prompt=prompt,
            max_output_tokens=max_output_tokens,
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
        self, *, model: str, prompt: Prompt, max_output_tokens: int
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
        return kwargs
