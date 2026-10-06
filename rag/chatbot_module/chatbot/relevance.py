"""개념 감지와 현재 학습 개념 관련성 판정."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from chatbot.concepts import ConceptRef
from chatbot.llm import LLMAdapter, LLMError
from chatbot.prompts import HistoryTurn
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
    """현재 스테이지 not_started 후보에서 명시 언급 또는 고신뢰 검색 1위를 고른다."""
    by_concept = {candidate.concept_id: candidate for candidate in candidates}
    exact = [candidate for candidate in candidates if _mentions(question, candidate, cache.get(candidate.concept_id))]
    if exact:
        rank = {hit.concept_id: index for index, hit in enumerate(retrieval.concept_hits)}
        return min(exact, key=lambda item: (rank.get(item.concept_id, len(rank)), item.order))
    if retrieval.concept_hits:
        top = retrieval.concept_hits[0]
        if top.score >= band_high and top.concept_id in by_concept:
            return by_concept[top.concept_id]
    return None


def is_question_related(
    *,
    question: str,
    current: CachedConcept,
    cache: ConceptCache,
    retrieval: RetrievalResult,
    llm: LLMAdapter,
    history: Sequence[HistoryTurn],
    force_true: bool = False,
) -> bool:
    if force_true:
        return True
    if _contains_any(question, (current.term, *current.aliases)):
        return True
    mentions_other = any(
        concept.concept_id != current.concept_id
        and _contains_any(question, (concept.term, *concept.aliases))
        for concept in cache.values()
    )
    if not mentions_other and any(
        hit.concept_id == current.concept_id for hit in retrieval.concept_hits[:5]
    ):
        return True
    try:
        return llm.judge_relevance(
            question=question,
            current_term=current.term,
            history=list(history[-2:]),
        )
    except LLMError:
        return False


def mentioned_concepts(
    question: str,
    concepts: Iterable[CachedConcept],
    *,
    exclude_concept_id: str,
) -> list[CachedConcept]:
    return [
        concept
        for concept in concepts
        if concept.concept_id != exclude_concept_id
        and _contains_any(question, (concept.term, *concept.aliases))
    ]


def _mentions(question: str, concept: ConceptRef, cached: CachedConcept | None) -> bool:
    aliases = cached.aliases if cached is not None else ()
    cached_term = (cached.term,) if cached is not None else ()
    return _contains_any(question, (concept.term, *cached_term, *aliases))


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    normalized = normalize_term(text)
    return any((term_text := normalize_term(term)) and term_text in normalized for term in terms)
