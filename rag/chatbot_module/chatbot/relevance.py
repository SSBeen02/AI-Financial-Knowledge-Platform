"""개념 감지와 현재 학습 개념 관련성 판정."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from chatbot.concepts import ConceptRef
from chatbot.llm import LLMAdapter, LLMError
from chatbot.retrieval import CachedConcept, ConceptCache, RetrievalResult


def normalize_term(value: str) -> str:
    return "".join(value.casefold().split())


def detect_concept(
    *,
    question: str,
    candidates: Sequence[ConceptRef],
    cache: ConceptCache,
    retrieval: RetrievalResult,
    band_high: float,
) -> ConceptRef | None:
    """현재 스테이지 미학습 후보에서 명시 언급 또는 고신뢰 검색 1위를 고른다."""
    by_doc = {candidate.doc_id: candidate for candidate in candidates}
    exact = [candidate for candidate in candidates if _mentions(question, candidate, cache.get(candidate.doc_id))]
    if exact:
        rank = {hit.doc_id: index for index, hit in enumerate(retrieval.concept_hits)}
        return min(exact, key=lambda item: (rank.get(item.doc_id, len(rank)), item.order))
    if retrieval.concept_hits:
        top = retrieval.concept_hits[0]
        if top.score >= band_high and top.doc_id in by_doc:
            return by_doc[top.doc_id]
    return None


def is_question_related(
    *,
    question: str,
    current: CachedConcept,
    cache: ConceptCache,
    retrieval: RetrievalResult,
    llm: LLMAdapter,
    force_true: bool = False,
) -> bool:
    if force_true:
        return True
    if _contains_any(question, (current.term, *current.aliases)):
        return True
    if any(
        concept.doc_id != current.doc_id
        and _contains_any(question, (concept.term, *concept.aliases))
        for concept in cache.values()
    ):
        return False
    if any(hit.doc_id == current.doc_id for hit in retrieval.concept_hits[:5]):
        return True
    try:
        return llm.judge_relevance(question=question, current_term=current.term)
    except LLMError:
        return False


def mentioned_concepts(
    question: str,
    concepts: Iterable[CachedConcept],
    *,
    exclude_doc_id: str,
) -> list[CachedConcept]:
    return [
        concept
        for concept in concepts
        if concept.doc_id != exclude_doc_id
        and _contains_any(question, (concept.term, *concept.aliases))
    ]


def _mentions(question: str, concept: ConceptRef, cached: CachedConcept | None) -> bool:
    aliases = cached.aliases if cached is not None else ()
    cached_term = (cached.term,) if cached is not None else ()
    return _contains_any(question, (concept.term, *cached_term, *aliases))


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    normalized = normalize_term(text)
    return any((term_text := normalize_term(term)) and term_text in normalized for term in terms)
