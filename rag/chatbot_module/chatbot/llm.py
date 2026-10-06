"""교체 가능한 LLM 어댑터와 제공자별 API 구현."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
import logging
from typing import Any

from chatbot.config import Settings
from chatbot.prompts import HistoryTurn, Prompt, build_relevance_prompt


logger = logging.getLogger(__name__)


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


class UpstageAdapter(LLMAdapter):
    """OpenAI SDK로 Upstage의 Chat Completions 호환 API를 사용한다."""

    def __init__(self, settings: Settings, *, client: Any | None = None):
        if settings.llm_provider.casefold() != "upstage":
            raise LLMConfigurationError(f"지원하지 않는 LLM_PROVIDER입니다: {settings.llm_provider}")
        if not settings.llm_api_key.strip():
            raise LLMConfigurationError("LLM_API_KEY 환경변수를 지정해야 합니다.")
        self._settings = settings
        if client is None:
            from openai import OpenAI

            client = OpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
            )
        self._client = client

    def generate(self, prompt: Prompt) -> str:
        return self._create(
            model=self._settings.llm_model,
            prompt=prompt,
            max_tokens=self._settings.llm_max_output_tokens,
            use_temperature=True,
        )

    def stream(self, prompt: Prompt) -> Iterator[str]:
        kwargs = self._request_kwargs(
            model=self._settings.llm_model,
            prompt=prompt,
            max_tokens=self._settings.llm_max_output_tokens,
            use_temperature=True,
        )
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}
        metadata: dict[str, Any] = {}
        received_text = False
        for chunk in self._iter_stream(kwargs, metadata):
            received_text = True
            yield chunk
        if not received_text and self._should_retry_without_reasoning(metadata):
            logger.warning(
                "Upstage stream returned no answer; retrying without reasoning (%s)",
                _safe_response_metadata(metadata),
            )
            retry_kwargs = self._request_kwargs(
                model=self._settings.llm_model,
                prompt=prompt,
                max_tokens=self._settings.llm_max_output_tokens,
                use_temperature=True,
                use_reasoning=False,
            )
            retry_kwargs["stream"] = True
            retry_kwargs["stream_options"] = {"include_usage": True}
            metadata = {}
            for chunk in self._iter_stream(retry_kwargs, metadata):
                received_text = True
                yield chunk
        if not received_text:
            logger.warning(
                "Upstage stream returned no answer (%s)",
                _safe_response_metadata(metadata),
            )
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
            max_tokens=min(self._settings.llm_max_output_tokens, 128),
            use_temperature=False,
            use_reasoning=False,
        )
        normalized = text.strip().casefold()
        return normalized.startswith("yes") or normalized.startswith("예")

    def _create(
        self,
        *,
        model: str,
        prompt: Prompt,
        max_tokens: int,
        use_temperature: bool,
        use_reasoning: bool = True,
    ) -> str:
        kwargs = self._request_kwargs(
            model=model,
            prompt=prompt,
            max_tokens=max_tokens,
            use_temperature=use_temperature,
            use_reasoning=use_reasoning,
        )
        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise LLMError("LLM 호출에 실패했습니다.") from exc
        output = _upstage_output(response)
        metadata = _upstage_response_metadata(response)
        if not output and use_reasoning and self._should_retry_without_reasoning(metadata):
            logger.warning(
                "Upstage response returned no answer; retrying without reasoning (%s)",
                _safe_response_metadata(metadata),
            )
            retry_kwargs = self._request_kwargs(
                model=model,
                prompt=prompt,
                max_tokens=max_tokens,
                use_temperature=use_temperature,
                use_reasoning=False,
            )
            try:
                response = self._client.chat.completions.create(**retry_kwargs)
            except Exception as exc:
                raise LLMError("LLM 호출에 실패했습니다.") from exc
            output = _upstage_output(response)
            metadata = _upstage_response_metadata(response)
        if not output:
            logger.warning(
                "Upstage response returned no answer (%s)",
                _safe_response_metadata(metadata),
            )
            raise LLMError("LLM이 비어 있는 응답을 반환했습니다.")
        return output

    def _request_kwargs(
        self,
        *,
        model: str,
        prompt: Prompt,
        max_tokens: int,
        use_temperature: bool,
        use_reasoning: bool = True,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt.instructions},
                {"role": "user", "content": prompt.input},
            ],
            "max_tokens": max_tokens,
        }
        if use_reasoning and self._settings.llm_reasoning_effort:
            kwargs["reasoning_effort"] = self._settings.llm_reasoning_effort
        elif use_temperature:
            kwargs["temperature"] = self._settings.llm_temperature
        return kwargs

    def _iter_stream(
        self,
        kwargs: dict[str, Any],
        metadata: dict[str, Any],
    ) -> Iterator[str]:
        finish_reason: str | None = None
        field_names: set[str] = set()
        usage: Any = None
        try:
            stream = self._client.chat.completions.create(**kwargs)
            for chunk in stream:
                field_names.update(_field_names(chunk))
                if getattr(chunk, "usage", None) is not None:
                    usage = chunk.usage
                choices = getattr(chunk, "choices", None) or []
                for choice in choices:
                    if getattr(choice, "finish_reason", None):
                        finish_reason = str(choice.finish_reason)
                    delta = getattr(choice, "delta", None)
                    field_names.update(_field_names(delta))
                    text = getattr(delta, "content", None) if delta is not None else None
                    if text:
                        yield str(text)
        except Exception as exc:
            raise LLMError("LLM 스트리밍 호출에 실패했습니다.") from exc
        metadata.update(
            {
                "finish_reason": finish_reason,
                "field_names": sorted(field_names),
                "usage": usage,
            }
        )

    def _should_retry_without_reasoning(self, metadata: dict[str, Any]) -> bool:
        return bool(
            self._settings.llm_reasoning_effort
            and metadata.get("finish_reason") == "length"
            and (
                _reasoning_tokens(metadata.get("usage")) > 0
                or "reasoning" in metadata.get("field_names", [])
            )
        )


def _upstage_output(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    message = getattr(choices[0], "message", None) if choices else None
    content = getattr(message, "content", None) if message is not None else None
    return str(content or "").strip()


def _upstage_response_metadata(response: Any) -> dict[str, Any]:
    choices = getattr(response, "choices", None) or []
    choice = choices[0] if choices else None
    message = getattr(choice, "message", None) if choice is not None else None
    return {
        "finish_reason": getattr(choice, "finish_reason", None),
        "field_names": sorted(
            set(_field_names(response))
            | set(_field_names(choice))
            | set(_field_names(message))
        ),
        "usage": getattr(response, "usage", None),
    }


def _field_names(value: Any) -> list[str]:
    if value is None:
        return []
    names: set[str] = set()
    model_extra = getattr(value, "model_extra", None)
    if isinstance(model_extra, dict):
        names.update(str(key) for key in model_extra)
    model_fields_set = getattr(value, "model_fields_set", None)
    if model_fields_set:
        names.update(str(key) for key in model_fields_set)
    elif hasattr(value, "__dict__"):
        names.update(str(key) for key in vars(value))
    return sorted(names)


def _reasoning_tokens(usage: Any) -> int:
    details = getattr(usage, "completion_tokens_details", None)
    if details is None and isinstance(usage, dict):
        details = usage.get("completion_tokens_details")
    value = getattr(details, "reasoning_tokens", None)
    if value is None and isinstance(details, dict):
        value = details.get("reasoning_tokens")
    return int(value or 0)


def _safe_response_metadata(metadata: dict[str, Any]) -> str:
    usage = metadata.get("usage")
    completion_tokens = getattr(usage, "completion_tokens", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    if isinstance(usage, dict):
        completion_tokens = usage.get("completion_tokens")
        prompt_tokens = usage.get("prompt_tokens")
    return (
        f"finish_reason={metadata.get('finish_reason')!r}, "
        f"field_names={metadata.get('field_names', [])!r}, "
        f"prompt_tokens={prompt_tokens!r}, completion_tokens={completion_tokens!r}, "
        f"reasoning_tokens={_reasoning_tokens(usage)!r}"
    )


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
