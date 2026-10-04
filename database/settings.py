import os
from dataclasses import dataclass

from dotenv import load_dotenv

_dotenv_loaded = False


def _ensure_dotenv() -> None:
    global _dotenv_loaded
    if not _dotenv_loaded:
        load_dotenv()
        _dotenv_loaded = True


@dataclass(frozen=True)
class Settings:
    supabase_url: str | None
    supabase_key: str | None
    repository: str
    openai_api_key: str | None
    openai_model: str
    gemini_api_key: str | None
    gemini_model: str
    llm_report_mode: str


def load_settings() -> Settings:
    _ensure_dotenv()
    url = os.getenv("SUPABASE_URL", "").strip() or None
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_KEY", "").strip()
        or None
    )
    repository = os.getenv("DIAGNOSTIC_REPOSITORY", "auto").strip().lower() or "auto"
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip() or None
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip() or None
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
    llm_report_mode = os.getenv("LLM_REPORT_MODE", "auto").strip().lower() or "auto"
    return Settings(
        supabase_url=url,
        supabase_key=key,
        repository=repository,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        llm_report_mode=llm_report_mode,
    )
