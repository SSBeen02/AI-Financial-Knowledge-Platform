"""개념별 예비 세트. 런타임에는 LLM/외부 사전을 호출하지 않는다."""
from __future__ import annotations

import copy
from functools import lru_cache
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.quiz import GeneratedQuestion

logger = logging.getLogger("quiz")
BANK_PATH = Path(__file__).resolve().parents[2] / "fallback_questions.json"


class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["source_and_model_checked", "human_checked"]
    verified_on: str
    model: str
    source_url: str = Field(min_length=8)
    source_title: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    questions_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    human_reviewed: bool


class FallbackSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    set_id: str = Field(min_length=1)
    concept_id: str = Field(min_length=1)
    stage_id: Literal["stage1", "stage2", "stage3", "stage4"]
    concept_name: str = Field(min_length=1)
    questions: list[GeneratedQuestion] = Field(min_length=3, max_length=3)
    verification: Verification


def questions_digest(questions: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(questions, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@lru_cache(maxsize=1)
def load_fallback_bank() -> tuple[FallbackSet, ...]:
    raw = json.loads(BANK_PATH.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1 or not isinstance(raw.get("sets"), list):
        raise ValueError("예비 문항 파일의 버전 또는 형식이 올바르지 않습니다.")
    sets = []
    seen = set()
    for entry in raw["sets"]:
        try:
            item = FallbackSet.model_validate(entry)
            if item.set_id in seen:
                raise ValueError("중복 예비 세트 식별자입니다.")
            actual = questions_digest([q.model_dump() for q in item.questions])
            if actual != item.verification.questions_sha256:
                raise ValueError("검토 후 예비 문항 내용이 변경됐습니다.")
            seen.add(item.set_id)
            sets.append(item)
        except Exception as error:
            # 원문과 검토 데이터는 로깅하지 않는다. 다른 정상 세트는 계속 사용할 수 있다.
            logger.warning("예비 문항 항목 로드 제외 reason=%s", type(error).__name__)
    return tuple(sets)


def select_fallback_set(
    *, concept_id: str, stage_id: str | None, previous_questions: list[dict[str, Any]],
    normalizer: Callable, novelty_checker: Callable,
) -> tuple[str, list[dict[str, Any]]] | None:
    try:
        bank = load_fallback_bank()
    except Exception as error:
        logger.warning("예비 문항 파일 사용 불가 reason=%s", type(error).__name__)
        return None
    for item in bank:
        if item.concept_id != concept_id or item.stage_id != stage_id:
            continue
        try:
            questions = normalizer(copy.deepcopy([q.model_dump() for q in item.questions]))
            # 세트뿐 아니라 문항 단위의 과거 제공 이력을 비교한다. 소진 후 자동 재사용하지 않는다.
            novelty_checker(questions, previous_questions)
        except ValueError:
            continue
        return item.set_id, questions
    return None
