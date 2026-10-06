"""stages.json 로딩과 개념 추천.

추천은 현재 스테이지의 not_started 개념만 order 순으로 반환한다.
재학습은 in_progress 개념의 최신 퀴즈 상태가 failed일 때만 연다.
퀴즈가 대기 중이거나, 통과로 기록됐지만 개념 상태가 아직 in_progress이면 quiz_pending이다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from chatbot.schemas import ChatMode, ConceptOut, ConceptsResponse
from chatbot.tone import (
    ChatTone,
    quiz_generation_failed_notice,
    quiz_pending_notice,
    relearn_notice,
)

STATUS_NOT_STARTED = "not_started"
STATUS_IN_PROGRESS = "in_progress"
STATUS_PASSED = "passed"


class StageQueryError(Exception):
    """stage 쿼리가 허용 값이 아닐 때."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ConceptCatalogError(Exception):
    """스테이지 목록과 개념 상태가 맞지 않을 때."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class ConceptRef:
    concept_id: str
    term: str
    term_full: str
    subcategory: str
    order: int
    stage_id: str
    stage_name_ko: str


@dataclass(frozen=True)
class StageRef:
    id: str
    name_ko: str
    concepts: tuple[ConceptRef, ...]


@dataclass(frozen=True)
class StageCatalog:
    stages: dict[str, StageRef]
    by_concept: dict[str, tuple[ConceptRef, ...]]


class InProgressConceptView(Protocol):
    concept_id: str
    term: str
    stage: str


class ConceptStatusReader(Protocol):
    def get_current_stage(self, user_id: str) -> str: ...

    def get_statuses(self, user_id: str, stage: str) -> dict[str, str]: ...

    def get_in_progress_concept(self, user_id: str, stage: str) -> InProgressConceptView | None: ...


def load_stage_catalog(path: Path) -> StageCatalog:
    if not path.is_file():
        raise FileNotFoundError(f"stages.json을 찾을 수 없습니다: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    stages: dict[str, StageRef] = {}
    by_concept: dict[str, list[ConceptRef]] = {}
    for raw_stage in data["stages"]:
        stage_id = raw_stage["id"]
        if stage_id in stages:
            raise ValueError(f"중복 스테이지입니다: {stage_id}")
        concepts: list[ConceptRef] = []
        for raw in raw_stage["concepts"]:
            ref = ConceptRef(
                concept_id=raw["concept_id"],
                term=raw["term"],
                term_full=raw["term_full"],
                subcategory=raw["subcategory"],
                order=raw["order"],
                stage_id=stage_id,
                stage_name_ko=raw_stage["name_ko"],
            )
            concepts.append(ref)
            by_concept.setdefault(ref.concept_id, []).append(ref)
        stages[stage_id] = StageRef(
            id=stage_id,
            name_ko=raw_stage["name_ko"],
            concepts=tuple(concepts),
        )
    return StageCatalog(
        stages=stages,
        by_concept={concept_id: tuple(refs) for concept_id, refs in by_concept.items()},
    )


def recommend_concepts(
    catalog: StageCatalog,
    status_service: ConceptStatusReader,
    user_id: str,
    *,
    offset: int,
    limit: int,
    screen_mode: ChatMode = "normal",
    locked_concept: ConceptRef | None = None,
    chat_tone: ChatTone = "hao",
) -> ConceptsResponse:
    """not_started 개념 페이지와 현재 모드의 잠금을 만든다."""
    if offset < 0 or limit < 1:
        raise StageQueryError("offset은 0 이상, limit은 1 이상이어야 합니다.")
    stage_id = status_service.get_current_stage(user_id)
    stage_ref = catalog.stages.get(stage_id)
    if stage_ref is None:
        raise ConceptCatalogError(f"알 수 없는 스테이지입니다: {stage_id}")

    statuses = status_service.get_statuses(user_id, stage_id)
    unlearned = [
        concept
        for concept in sorted(stage_ref.concepts, key=lambda item: item.order)
        if statuses.get(concept.concept_id, STATUS_NOT_STARTED) == STATUS_NOT_STARTED
    ]
    page = unlearned[offset : offset + limit]
    has_more = offset + limit < len(unlearned)
    mode, locked, notice, suggested = lock_presentation(
        screen_mode,
        locked_concept,
        chat_tone=chat_tone,
    )
    return ConceptsResponse(
        mode=mode,
        stage_id=stage_ref.id,  # type: ignore[arg-type]
        stage_name_ko=stage_ref.name_ko,
        concepts=[_to_out(concept) for concept in page],
        next_offset=offset + limit if has_more else None,
        has_more=has_more,
        locked_concept=locked,
        notice=notice,
        suggested_message=suggested,
    )

def lock_presentation(
    mode: ChatMode,
    concept: ConceptRef | None,
    *,
    chat_tone: ChatTone = "hao",
) -> tuple[ChatMode, ConceptOut | None, str | None, str | None]:
    """재학습 안내와 퀴즈 대기 안내를 만든다. 모드 판정은 서비스가 한다."""
    if concept is None or mode == "normal":
        return "normal", None, None, None
    locked = _to_out(concept)
    if mode == "quiz_pending":
        notice = quiz_pending_notice(concept.term, chat_tone)
        return "quiz_pending", locked, notice, None
    if mode == "quiz_generation_failed":
        return (
            "quiz_generation_failed",
            locked,
            quiz_generation_failed_notice(chat_tone),
            None,
        )
    notice = relearn_notice(concept.term, chat_tone)
    return "relearn", locked, notice, f"{concept.term}에 대해 다시 알려줘"


def find_concept(catalog: StageCatalog, concept_id: str, stage_id: str) -> ConceptRef:
    for concept in catalog.by_concept.get(concept_id, ()):
        if concept.stage_id == stage_id:
            return concept
    raise ConceptCatalogError(f"스테이지 {stage_id}에서 개념을 찾을 수 없습니다: {concept_id}")


def _to_out(concept: ConceptRef) -> ConceptOut:
    return ConceptOut(
        concept_id=concept.concept_id,
        term=concept.term,
        term_full=concept.term_full,
        subcategory=concept.subcategory,
        order=concept.order,
    )
