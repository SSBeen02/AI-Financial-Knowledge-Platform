from __future__ import annotations

import pytest
from pydantic import ValidationError

from chatbot.config import SEARCH_PROFILES, Settings, get_settings


def test_defaults(clean_env: None) -> None:
    settings = Settings(_env_file=None, llm_model="gpt-test")
    assert settings.qdrant_collection == "sisa_terms"
    assert settings.dense_model == "nlpai-lab/KURE-v1"
    assert settings.llm_provider == "openai"
    assert settings.band_high == 0.50
    assert settings.band_low == 0.45
    assert settings.display_source_min_score == 0.60
    assert settings.stages_json_path.as_posix() == "data/stages.json"
    assert settings.chat_db_url == "sqlite:///chat.db"
    assert settings.db_auto_create is False
    assert settings.dev_enable_tools is False
    assert settings.dev_simulate_quiz_generation_failure is False
    assert settings.relevance_model == "gpt-test"
    assert settings.llm_reasoning_effort == ""
    assert settings.llm_max_output_tokens == 1200
    assert settings.llm_temperature == 0.7
    assert settings.chat_tone == "hao"
    assert settings.answer_knowledge_mode == "dictionary_only"
    assert settings.free_question_auto_start is False


@pytest.mark.parametrize("temperature", [-0.01, 2.01])
def test_llm_temperature_must_be_in_openai_range(
    clean_env: None, temperature: float
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_model="gpt-test", llm_temperature=temperature)


def test_chat_tone_accepts_only_supported_values(clean_env: None) -> None:
    assert Settings(_env_file=None, llm_model="gpt-test", chat_tone="modern").chat_tone == "modern"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_model="gpt-test", chat_tone="formal")


def test_answer_knowledge_mode_accepts_only_supported_values(clean_env: None) -> None:
    for mode in ("dictionary_only", "dictionary_plus", "free"):
        assert (
            Settings(
                _env_file=None,
                llm_model="gpt-test",
                answer_knowledge_mode=mode,
            ).answer_knowledge_mode
            == mode
        )
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            llm_model="gpt-test",
            answer_knowledge_mode="anything",
        )


def test_llm_model_is_required(clean_env: None) -> None:
    with pytest.raises(ValidationError, match="LLM_MODEL"):
        Settings(_env_file=None)


def test_relevance_model_falls_back_to_llm_model(clean_env: None) -> None:
    settings = Settings(_env_file=None, llm_model="gpt-test", llm_relevance_model="")
    assert settings.relevance_model == "gpt-test"
    overridden = Settings(_env_file=None, llm_model="gpt-test", llm_relevance_model="gpt-small")
    assert overridden.relevance_model == "gpt-small"


def test_dev_flag_reads_environment(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_ENABLE_TOOLS", "true")
    monkeypatch.setenv("DEV_SIMULATE_QUIZ_GENERATION_FAILURE", "true")
    settings = Settings(_env_file=None, llm_model="gpt-test")
    assert settings.dev_enable_tools is True
    assert settings.dev_simulate_quiz_generation_failure is True


def test_legacy_dev_flag_logs_rename_warning(
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("DEV_USE_LOCAL_STATUS", "true")
    monkeypatch.setenv("LLM_MODEL", "gpt-test")
    get_settings()
    assert "DEV_ENABLE_TOOLS로 바뀌었습니다" in caplog.text


def test_secrets_are_hidden_from_repr(clean_env: None) -> None:
    settings = Settings(
        _env_file=None,
        llm_model="gpt-test",
        llm_api_key="sk-secret",
        qdrant_api_key="qd-secret",
    )
    text = repr(settings)
    assert "sk-secret" not in text
    assert "qd-secret" not in text


def test_band_low_must_be_below_band_high(clean_env: None) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_model="gpt-test", band_high=0.45, band_low=0.50)


def test_search_profile_has_only_sisa_terms() -> None:
    assert list(SEARCH_PROFILES) == ["sisa_terms"]
    profile = SEARCH_PROFILES["sisa_terms"]
    assert profile["mode"] == "dense"
    assert profile["k"] == 5
    assert profile["slots"] == 3
    assert profile["concept_source"] is True
    assert profile["label"] == "시사경제용어사전"


def test_qdrant_collection_renames_default_search_profile(clean_env: None) -> None:
    settings = Settings(_env_file=None, llm_model="gpt-test", qdrant_collection="custom_terms")
    assert list(settings.search_profiles) == ["custom_terms"]
    assert settings.search_profiles["custom_terms"]["concept_source"] is True
