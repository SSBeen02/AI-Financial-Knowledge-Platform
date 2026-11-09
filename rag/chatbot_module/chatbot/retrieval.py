"""검색 소스 순회, 자리 배분, 신뢰 구간, 개념 문서 캐시.

검색은 `rag_common.search`를 그대로 쓴다. 점수 범위가 소스마다 다르므로
결과를 점수 순으로 다시 섞지 않고, 소스별 `slots`만큼만 이어 붙인다.
band는 `concept_source` 소스의 Dense 최고 점수로만 정한다.
"""

from __future__ import annotations

import uuid
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from chatbot.config import SEARCH_PROFILES, SearchProfile, Settings
from chatbot.schemas import Band, SourceOut

PointId = str
_BATCH = 128
PUBLIC_DATA_SOURCE_LABEL = SEARCH_PROFILES["sisa_terms"]["label"]
FSS_COLLECTION = "fss_practical_finance_4e_3p_kure_v1"


def display_source_label(label: str, collection: str) -> str:
    """옛 메타데이터의 축약명을 사용자용 공식 데이터셋 이름으로 바꾼다."""
    if collection == "sisa_terms":
        return PUBLIC_DATA_SOURCE_LABEL
    return label


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


def concept_point_id(concept_id: str) -> PointId:
    """Qdrant 포인트 ID. 기존 적재 규칙과 같은 concept ID 기반 UUID다."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, concept_id))


def judge_band(score: float, *, high: float, low: float) -> Band:
    if score >= high:
        return "high"
    if score >= low:
        return "mid"
    return "low"


@dataclass(frozen=True)
class CachedConcept:
    concept_id: str
    term: str
    aliases: tuple[str, ...]
    text: str
    images: tuple[str, ...] | None


@dataclass(frozen=True)
class RetrievedDoc:
    concept_id: str
    term: str
    score: float
    collection: str
    label: str
    text: str
    images: tuple[str, ...] | None
    stages: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    printed_page: int | None = None
    source_url: str | None = None


@dataclass(frozen=True)
class RetrievalResult:
    sources: list[RetrievedDoc]
    concept_hits: list[RetrievedDoc]
    band: Band
    top_score: float


class ConceptCache:
    """서버 시작 시 학습 개념 payload를 한 번 읽어 둔다."""

    def __init__(self, client: _Qdrant, collection: str, concept_ids: Iterable[str]):
        unique = list(dict.fromkeys(concept_ids))
        self._docs = _load_concepts(client, collection, unique)

    def get(self, concept_id: str) -> CachedConcept | None:
        return self._docs.get(concept_id)

    def values(self) -> tuple[CachedConcept, ...]:
        return tuple(self._docs.values())

    def __len__(self) -> int:
        return len(self._docs)


_HANGUL_TERM = re.compile(r"[가-힣]{4,}")


def normalize_search_query(query: str, known_terms: Iterable[str]) -> str:
    """검색용으로만 캐시 용어·별칭의 한 글자 띄어쓰기 표기를 붙인다."""
    candidates = {
        compact
        for term in known_terms
        if (compact := re.sub(r"\s+", "", term)) and _HANGUL_TERM.fullmatch(compact)
    }
    for term in sorted(candidates, key=len, reverse=True):
        pattern = re.compile(
            r"(?<![가-힣])" + r"[ \t]+".join(re.escape(char) for char in term)
            + r"(?![가-힣]{2,})"
        )
        query = pattern.sub(term, query)
    return query


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
        self._use_real_search = search_fn is None
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
        search_kwargs = dict(
            mode=profile["mode"],
            k=profile["k"],
            collection=collection,
        )
        if profile["mode"] == "hybrid":
            search_kwargs["prefetch_k"] = profile.get("prefetch_k", 30)
        if self._use_real_search and profile.get("sparse_vector"):
            points = self._search_named_sparse(query, collection, profile)
        else:
            points = self._search(
                self._client,
                query,
                self._dense,
                self._sparse,
                **search_kwargs,
            )
        return [_retrieved(point, collection, profile["label"]) for point in points]

    def _search_named_sparse(self, query: str, collection: str, profile: SearchProfile) -> list[Any]:
        """공용 검색 함수를 바꾸지 않고 교재의 bm25 벡터 이름을 사용한다."""
        from qdrant_client import models
        from rag_common import DENSE_NAME
        import numpy as np

        if getattr(self._sparse, "collection", collection) != collection:
            raise RetrievalError(f"{collection}에 맞는 희소 인코더가 설정되지 않았습니다.")

        dense_query = self._dense.encode([query])[0].tolist()
        sparse_query = self._sparse.encode_query(query)
        candidates = profile.get("prefetch_k", 30)
        prefetch = [models.Prefetch(query=dense_query, using=DENSE_NAME, limit=candidates)]
        if sparse_query.indices:
            prefetch.append(models.Prefetch(
                query=sparse_query, using=profile["sparse_vector"], limit=candidates
            ))
        response = self._client.query_points(
            collection_name=collection,
            prefetch=prefetch,
            query=models.RrfQuery(rrf=models.Rrf(k=2, weights=[1.0] * len(prefetch))),
            limit=profile["k"],
            with_payload=True,
            with_vectors=[DENSE_NAME] if "min_dense_score" in profile else False,
        )
        if "min_dense_score" not in profile:
            return response.points
        query_vector = np.asarray(dense_query, dtype=np.float32)
        query_norm = np.linalg.norm(query_vector)
        selected = []
        for point in response.points:
            vector = (point.vector or {}).get(DENSE_NAME) if isinstance(point.vector, dict) else None
            if vector is None:
                raise RetrievalError(f"{collection}의 Dense 벡터를 검색 결과에서 읽지 못했습니다.")
            document_vector = np.asarray(vector, dtype=np.float32)
            denominator = query_norm * np.linalg.norm(document_vector)
            if denominator == 0:
                continue
            similarity = float(np.dot(query_vector, document_vector) / denominator)
            if similarity >= profile["min_dense_score"]:
                selected.append(point)
        return selected

    def _dense_top(self, query: str, collection: str, profile: SearchProfile, hits: list[RetrievedDoc]) -> float:
        if profile["mode"] == "dense":
            return hits[0].score if hits else 0.0
        return float(self._dense_score(self._client, query, self._dense, collection=collection))


def to_source_out(doc: RetrievedDoc) -> SourceOut:
    return SourceOut(
        concept_id=doc.concept_id,
        term=doc.term,
        score=doc.score,
        collection=doc.collection,
        label=display_source_label(doc.label, doc.collection),
        images=list(doc.images) if doc.images is not None else None,
        printed_page=doc.printed_page,
        source_url=doc.source_url,
    )


def _load_concepts(client: _Qdrant, collection: str, concept_ids: list[str]) -> dict[str, CachedConcept]:
    found: dict[str, CachedConcept] = {}
    by_point = {concept_point_id(concept_id): concept_id for concept_id in concept_ids}
    for chunk in _chunks(concept_ids, _BATCH):
        points = client.retrieve(
            collection_name=collection,
            ids=[concept_point_id(concept_id) for concept_id in chunk],
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            concept = _cached(point, by_point)
            if concept is not None:
                found[concept.concept_id] = concept
    missing = [concept_id for concept_id in concept_ids if concept_id not in found]
    if missing:
        _fill_by_concept_id(client, collection, missing, found)
    still_missing = [concept_id for concept_id in concept_ids if concept_id not in found]
    if still_missing:
        sample = ", ".join(still_missing[:5])
        raise ConceptCacheError(f"개념 문서를 찾지 못했습니다: {len(still_missing)}건 ({sample})")
    return found


def _fill_by_concept_id(
    client: _Qdrant,
    collection: str,
    concept_ids: list[str],
    found: dict[str, CachedConcept],
) -> None:
    from qdrant_client import models

    for chunk in _chunks(concept_ids, _BATCH):
        points, _offset = client.scroll(
            collection_name=collection,
            scroll_filter=models.Filter(
                should=[
                    models.FieldCondition(
                        key="concept_id", match=models.MatchAny(any=chunk)
                    ),
                    # 기존 Qdrant 컬렉션의 payload는 doc_id를 사용한다.
                    models.FieldCondition(key="doc_id", match=models.MatchAny(any=chunk)),
                ]
            ),
            limit=len(chunk),
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            concept = _cached(point, {})
            if concept is not None and concept.concept_id in set(chunk):
                found[concept.concept_id] = concept


def _cached(point: Any, by_point: Mapping[str, str]) -> CachedConcept | None:
    payload = point.payload or {}
    concept_id = (
        payload.get("concept_id")
        or payload.get("doc_id")
        or by_point.get(str(point.id))
    )
    if not isinstance(concept_id, str) or not concept_id:
        return None
    aliases = payload.get("aliases") or []
    if not isinstance(aliases, list):
        aliases = []
    return CachedConcept(
        concept_id=concept_id,
        term=str(payload.get("term") or ""),
        aliases=tuple(str(alias) for alias in aliases),
        text=str(payload.get("text") or payload.get("content") or payload.get("page_content") or ""),
        images=_images(payload),
    )


def _retrieved(point: Any, collection: str, label: str) -> RetrievedDoc:
    payload = point.payload or {}
    section = str(payload.get("subsection") or payload.get("section") or "").strip()
    if len(section) > 40 or ("." in section and len(section) > 25) or section.endswith(("?", "!", "。")):
        section = ""
    return RetrievedDoc(
        concept_id=str(payload.get("concept_id") or payload.get("doc_id") or payload.get("chunk_id") or point.id),
        term=str(payload.get("term") or section or payload.get("chapter_title") or payload.get("section_title") or payload.get("title") or payload.get("chunk_id") or ""),
        score=float(point.score),
        collection=collection,
        label=label,
        text=str(payload.get("text") or payload.get("content_markdown") or payload.get("content") or payload.get("page_content") or ""),
        images=_images(payload),
        stages=_stages(payload),
        aliases=_aliases(payload),
        printed_page=payload.get("printed_page") if type(payload.get("printed_page")) is int else None,
        source_url=(url if (url := str(payload.get("source_url") or "")).startswith(("https://", "http://")) else None),
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


def _aliases(payload: Mapping[str, Any]) -> tuple[str, ...]:
    aliases = payload.get("aliases") or []
    if not isinstance(aliases, list):
        return ()
    return tuple(str(item) for item in aliases)


def _chunks(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
