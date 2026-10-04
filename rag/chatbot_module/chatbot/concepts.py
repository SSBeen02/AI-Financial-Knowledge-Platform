"""stages.json 로딩과 개념 추천.

추천은 현재 스테이지의 미학습 개념만 order 순으로 반환한다.
재학습은 미통과 개념의 최신 퀴즈 상태가 failed일 때만 연다.
퀴즈가 대기 중이거나, 통과로 기록됐지만 개념 상태가 아직 미통과이면 quiz_pending이다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from chatbot.schemas import ChatMode, ConceptOut, ConceptsResponse, StageOut

STATUS_UNLEARNED = "미학습"
STATUS_FAILED = "미통과"
STATUS_PASSED = "통과"
SELECTABLE_STAGE = "stage5"


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
    doc_id: str
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
    by_doc: dict[str, tuple[ConceptRef, ...]]


class FailedConceptView(Protocol):
    doc_id: str
    term: str
    stage: str


class ConceptStatusReader(Protocol):
    def get_current_stage(self, user_id: str) -> str: ...

    def get_statuses(self, user_id: str, stage: str) -> dict[str, str]: ...

    def get_failed_concept(self, user_id: str) -> FailedConceptView | None: ...


def load_stage_catalog(path: Path) -> StageCatalog:
    if not path.is_file():
        raise FileNotFoundError(f"stages.json을 찾을 수 없습니다: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    stages: dict[str, StageRef] = {}
    by_doc: dict[str, list[ConceptRef]] = {}
    for raw_stage in data["stages"]:
        stage_id = raw_stage["id"]
        if stage_id in stages:
            raise ValueError(f"중복 스테이지입니다: {stage_id}")
        concepts: list[ConceptRef] = []
        for raw in raw_stage["concepts"]:
            ref = ConceptRef(
                doc_id=raw["doc_id"],
                term=raw["term"],
                term_full=raw["term_full"],
                subcategory=raw["subcategory"],
                order=raw["order"],
                stage_id=stage_id,
                stage_name_ko=raw_stage["name_ko"],
            )
            concepts.append(ref)
            by_doc.setdefault(ref.doc_id, []).append(ref)
        stages[stage_id] = StageRef(
            id=stage_id,
            name_ko=raw_stage["name_ko"],
            concepts=tuple(concepts),
        )
    return StageCatalog(
        stages=stages,
        by_doc={doc_id: tuple(refs) for doc_id, refs in by_doc.items()},
    )


def recommend_concepts(
    catalog: StageCatalog,
    status_service: ConceptStatusReader,
    user_id: str,
    *,
    offset: int,
    limit: int,
    stage: str | None,
    screen_mode: ChatMode = "normal",
    locked_concept: ConceptRef | None = None,
) -> ConceptsResponse:
    """미학습 개념 페이지와 현재 모드의 잠금을 만든다."""
    if offset < 0 or limit < 1:
        raise StageQueryError("offset은 0 이상, limit은 1 이상이어야 합니다.")
    stage_id = _resolve_stage(stage, status_service.get_current_stage(user_id))
    stage_ref = catalog.stages.get(stage_id)
    if stage_ref is None:
        raise ConceptCatalogError(f"알 수 없는 스테이지입니다: {stage_id}")

    statuses = status_service.get_statuses(user_id, stage_id)
    unlearned = [
        concept
        for concept in sorted(stage_ref.concepts, key=lambda item: item.order)
        if statuses.get(concept.doc_id, STATUS_UNLEARNED) == STATUS_UNLEARNED
    ]
    page = unlearned[offset : offset + limit]
    has_more = offset + limit < len(unlearned)
    mode, locked, notice, suggested = lock_presentation(screen_mode, locked_concept)
    return ConceptsResponse(
        mode=mode,
        stage=StageOut(id=stage_ref.id, name_ko=stage_ref.name_ko),
        concepts=[_to_out(concept) for concept in page],
        next_offset=offset + limit if has_more else None,
        has_more=has_more,
        locked_concept=locked,
        notice=notice,
        suggested_message=suggested,
    )


def _resolve_stage(requested: str | None, current_stage: str) -> str:
    if requested is None:
        return current_stage
    text = requested.strip()
    if text != SELECTABLE_STAGE:
        raise StageQueryError("stage는 stage5만 지정할 수 있습니다.")
    return text


def lock_presentation(
    mode: ChatMode,
    concept: ConceptRef | None,
) -> tuple[ChatMode, ConceptOut | None, str | None, str | None]:
    """재학습 안내와 퀴즈 대기 안내를 만든다. 모드 판정은 서비스가 한다."""
    if concept is None or mode == "normal":
        return "normal", None, None, None
    locked = _to_out(concept)
    if mode == "quiz_pending":
        notice = f"현재 {concept.term} 개념의 퀴즈 결과를 기다리는 중입니다."
        return "quiz_pending", locked, notice, None
    notice = (
        f"현재 미통과인 {concept.term} 개념 학습중입니다. "
        "통과해야 다음 개념을 넘어갈 수 있습니다."
    )
    return "relearn", locked, notice, f"{concept.term}에 대해 다시 알려줘"


def find_concept(catalog: StageCatalog, doc_id: str, stage_id: str) -> ConceptRef:
    for concept in catalog.by_doc.get(doc_id, ()):
        if concept.stage_id == stage_id:
            return concept
    raise ConceptCatalogError(f"스테이지 {stage_id}에서 개념을 찾을 수 없습니다: {doc_id}")


def _to_out(concept: ConceptRef) -> ConceptOut:
    return ConceptOut(
        doc_id=concept.doc_id,
        term=concept.term,
        term_full=concept.term_full,
        subcategory=concept.subcategory,
        order=concept.order,
    )
