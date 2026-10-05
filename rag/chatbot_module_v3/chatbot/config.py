"""환경변수와 검색 소스 설정."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal, TypedDict

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SearchProfile(TypedDict):
    mode: str
    k: int
    slots: int
    label: str
    concept_source: bool


SEARCH_PROFILES: dict[str, SearchProfile] = {
    "sisa_terms": {
        "mode": "dense",
        "k": 5,
        "slots": 3,
        "label": "시사경제용어사전",
        "concept_source": True,
    },
}

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """프로세스 설정. API 키는 repr에 포함하지 않는다."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    qdrant_url: str = ""
    qdrant_api_key: str = Field(default="", repr=False)
    qdrant_collection: str = "sisa_terms"
    dense_model: str = "nlpai-lab/KURE-v1"
    llm_provider: str = "openai"
    llm_model: str = ""
    llm_api_key: str = Field(default="", repr=False)
    llm_relevance_model: str = ""
    llm_reasoning_effort: str = ""
    llm_max_output_tokens: int = Field(default=1200, ge=1)
    llm_temperature: float = Field(default=0.7, ge=0, le=2)
    chat_tone: Literal["hao", "modern"] = "hao"
    free_question_auto_start: bool = False
    band_high: float = 0.50
    band_low: float = 0.45
    display_source_min_score: float = Field(default=0.60, ge=0, le=1)
    stages_json_path: Path = Path("data/stages.json")
    chat_db_url: str = "sqlite:///chat.db"
    dev_enable_tools: bool = False
    dev_simulate_quiz_generation_failure: bool = False

    @field_validator("llm_model")
    @classmethod
    def _llm_model_is_required(cls, value: str) -> str:
        model = value.strip()
        if not model:
            raise ValueError("LLM_MODEL 환경변수를 지정해야 합니다.")
        return model

    @field_validator("llm_relevance_model", "llm_reasoning_effort")
    @classmethod
    def _strip_optional_llm_values(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _check_bands(self) -> Settings:
        if self.band_low < 0 or self.band_high < 0 or self.band_low >= self.band_high:
            raise ValueError("BAND_LOW는 0 이상이고 BAND_HIGH보다 작아야 합니다.")
        return self

    @property
    def relevance_model(self) -> str:
        return self.llm_relevance_model or self.llm_model

    @property
    def search_profiles(self) -> dict[str, SearchProfile]:
        """기본 concept source 이름을 QDRANT_COLLECTION 설정과 맞춘다."""
        profiles = {name: dict(profile) for name, profile in SEARCH_PROFILES.items()}
        if self.qdrant_collection == "sisa_terms":
            return profiles  # type: ignore[return-value]
        primary = profiles.pop("sisa_terms")
        return {self.qdrant_collection: primary, **profiles}  # type: ignore[return-value]


def get_settings() -> Settings:
    _warn_legacy_dev_flag()
    return Settings()


def _warn_legacy_dev_flag() -> None:
    """이전 개발 플래그를 값 노출 없이 안내한다."""

    legacy_name = "DEV_USE_LOCAL_STATUS"
    found = legacy_name in os.environ
    env_path = Path(".env")
    if not found and env_path.is_file():
        try:
            found = any(
                line.strip().split("=", 1)[0].strip() == legacy_name
                for line in env_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            )
        except OSError:
            found = False
    if found:
        logger.warning(
            "DEV_USE_LOCAL_STATUS는 DEV_ENABLE_TOOLS로 바뀌었습니다. "
            "이전 환경변수를 제거하고 새 이름을 사용하세요."
        )
