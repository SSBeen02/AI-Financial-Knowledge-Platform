"""검색 소스 순회, 자리 배분, 신뢰 구간, 개념 문서 캐시.

검색은 `rag_common.search`를 그대로 쓴다. 점수 범위가 소스마다 다르므로
결과를 점수 순으로 다시 섞지 않고, 소스별 `slots`만큼만 이어 붙인다.
band는 `concept_source` 소스의 Dense 최고 점수로만 정한다.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from chatbot.config import SEARCH_PROFILES, SearchProfile, Settings
from chatbot.schemas import Band, SourceOut

PointId = str
_BATCH = 128


class ConceptCacheError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class RetrievalError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class _Point(Protocol):
    id: Any
    payload: dict[str, Any] | None
    score: float


class _Qdrant(Protocol):
    def retrieve(self, collection_name: str, ids: Sequence[str], **kwargs: Any) -> list[Any]: ...

    def scroll(self, collection_name: str, **kwargs: Any) -> tuple[list[Any], Any]: ...


def concept_point_id(doc_id: str) -> PointId:
    """Qdrant 포인트 ID. uuid5(NAMESPACE_URL, doc_id)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, doc_id))


def judge_band(score: float, *, high: float, low: float) -> Band:
    if score >= high:
        return "high"
    if score >= low:
        return "mid"
    return "low"


@dataclass(frozen=True)
class CachedConcept:
    doc_id: str
    term: str
    aliases: tuple[str, ...]
    text: str
    images: tuple[str, ...] | None


@dataclass(frozen=True)
class RetrievedDoc:
    doc_id: str
    term: str
    score: float
    collection: str
    label: str
    text: str
    images: tuple[str, ...] | None
    stages: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalResult:
    sources: list[RetrievedDoc]
    concept_hits: list[RetrievedDoc]
    band: Band
    top_score: float


class ConceptCache:
    """서버 시작 시 학습 개념 payload를 한 번 읽어 둔다."""

    def __init__(self, client: _Qdrant, collection: str, doc_ids: Iterable[str]):
        unique = list(dict.fromkeys(doc_ids))
        self._docs = _load_concepts(client, collection, unique)

    def get(self, doc_id: str) -> CachedConcept | None:
        return self._docs.get(doc_id)

    def values(self) -> tuple[CachedConcept, ...]:
        return tuple(self._docs.values())

    def __len__(self) -> int:
        return len(self._docs)


class Retriever:
    def __init__(
        self,
        client: Any,
        dense: Any,
        settings: Settings,
        *,
        profiles: Mapping[str, SearchProfile] | None = None,
        search_fn: Callable[..., list[Any]] | None = None,
        dense_score_fn: Callable[..., float] | None = None,
        sparse: Any = None,
    ):
        self._client = client
        self._dense = dense
        self._settings = settings
        self._profiles = profiles if profiles is not None else settings.search_profiles
        self._sparse = sparse
        if search_fn is None or dense_score_fn is None:
            from rag_common import search, top_dense_score

            search_fn = search_fn or search
            dense_score_fn = dense_score_fn or top_dense_score
        self._search = search_fn
        self._dense_score = dense_score_fn

    def search(self, query: str) -> RetrievalResult:
        merged: list[RetrievedDoc] = []
        concept_hits: list[RetrievedDoc] = []
        concept_scores: list[float] = []
        for name, profile in self._profiles.items():
            hits = self._search_profile(query, name, profile)
            merged.extend(hits[: profile["slots"]])
            if profile["concept_source"]:
                concept_hits.extend(hits)
                concept_scores.append(self._dense_top(query, name, profile, hits))
        top_score = max(concept_scores) if concept_scores else 0.0
        band = judge_band(top_score, high=self._settings.band_high, low=self._settings.band_low)
        return RetrievalResult(
            sources=[] if band == "low" else merged,
            concept_hits=concept_hits,
            band=band,
            top_score=top_score,
        )

    def _search_profile(self, query: str, collection: str, profile: SearchProfile) -> list[RetrievedDoc]:
        if profile["mode"] != "dense" and self._sparse is None:
            raise RetrievalError(f"{collection}의 {profile['mode']} 검색에는 희소 인코더가 필요합니다.")
        points = self._search(
            self._client,
            query,
            self._dense,
            self._sparse,
            mode=profile["mode"],
            k=profile["k"],
            collection=collection,
        )
        return [_retrieved(point, collection, profile["label"]) for point in points]

    def _dense_top(self, query: str, collection: str, profile: SearchProfile, hits: list[RetrievedDoc]) -> float:
        if profile["mode"] == "dense":
            return hits[0].score if hits else 0.0
        return float(self._dense_score(self._client, query, self._dense, collection=collection))


def to_source_out(doc: RetrievedDoc) -> SourceOut:
    return SourceOut(
        doc_id=doc.doc_id,
        term=doc.term,
        score=doc.score,
        collection=doc.collection,
        label=doc.label,
        images=list(doc.images) if doc.images is not None else None,
    )


def _load_concepts(client: _Qdrant, collection: str, doc_ids: list[str]) -> dict[str, CachedConcept]:
    found: dict[str, CachedConcept] = {}
    by_point = {concept_point_id(doc_id): doc_id for doc_id in doc_ids}
    for chunk in _chunks(doc_ids, _BATCH):
        points = client.retrieve(
            collection_name=collection,
            ids=[concept_point_id(doc_id) for doc_id in chunk],
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            concept = _cached(point, by_point)
            if concept is not None:
                found[concept.doc_id] = concept
    missing = [doc_id for doc_id in doc_ids if doc_id not in found]
    if missing:
        _fill_by_doc_id(client, collection, missing, found)
    still_missing = [doc_id for doc_id in doc_ids if doc_id not in found]
    if still_missing:
        sample = ", ".join(still_missing[:5])
        raise ConceptCacheError(f"개념 문서를 찾지 못했습니다: {len(still_missing)}건 ({sample})")
    return found


def _fill_by_doc_id(
    client: _Qdrant,
    collection: str,
    doc_ids: list[str],
    found: dict[str, CachedConcept],
) -> None:
    from qdrant_client import models

    for chunk in _chunks(doc_ids, _BATCH):
        points, _offset = client.scroll(
            collection_name=collection,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(key="doc_id", match=models.MatchAny(any=chunk))]
            ),
            limit=len(chunk),
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            concept = _cached(point, {})
            if concept is not None and concept.doc_id in set(chunk):
                found[concept.doc_id] = concept


def _cached(point: Any, by_point: Mapping[str, str]) -> CachedConcept | None:
    payload = point.payload or {}
    doc_id = payload.get("doc_id") or by_point.get(str(point.id))
    if not isinstance(doc_id, str) or not doc_id:
        return None
    aliases = payload.get("aliases") or []
    if not isinstance(aliases, list):
        aliases = []
    return CachedConcept(
        doc_id=doc_id,
        term=str(payload.get("term") or ""),
        aliases=tuple(str(alias) for alias in aliases),
        text=str(payload.get("text") or ""),
        images=_images(payload),
    )


def _retrieved(point: Any, collection: str, label: str) -> RetrievedDoc:
    payload = point.payload or {}
    return RetrievedDoc(
        doc_id=str(payload.get("doc_id") or ""),
        term=str(payload.get("term") or ""),
        score=float(point.score),
        collection=collection,
        label=label,
        text=str(payload.get("text") or ""),
        images=_images(payload),
        stages=_stages(payload),
    )


def _images(payload: Mapping[str, Any]) -> tuple[str, ...] | None:
    if "images" not in payload:
        return None
    images = payload["images"]
    if not isinstance(images, list):
        return None
    return tuple(str(item) for item in images)


def _stages(payload: Mapping[str, Any]) -> tuple[str, ...]:
    stages = payload.get("stages") or []
    if not isinstance(stages, list):
        return ()
    return tuple(str(item) for item in stages)


def _chunks(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
