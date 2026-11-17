"""스테이지 표기의 검증 가능한 영문 동의어를 시작 시 한 번 준비한다."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

SYNONYMS_BY_CONCEPT_ID: dict[str, tuple[str, ...]] = {
    "sisa_1410": ("ETF", "Exchange Traded Fund"),
    "sisa_104": ("자유무역협정",),
    "sisa_182": ("경제협력개발기구",),
    "sisa_84": ("주가연계증권",),
    "sisa_220": ("공급망관리",),
    "sisa_65": ("기업의 사회적 책임",),
    "sisa_1510": ("개인파산",),
    "sisa_2433": ("지적소유권",),
    "sisa_1659": ("파리기후협약",),
    "sisa_2844": ("사전채무조정제도",),
    "sisa_2567": ("담합",),
    "sisa_2091": ("Inflation",),
    "sisa_2309": ("Gentrification",),
    "sisa_2777": ("Pandemic",),
    "sisa_1001": ("Reshoring",),
    "sisa_1064": ("Moratorium",),
    "sisa_2859": ("FinTech",),
    "sisa_1664": ("Start-Up",),
    "sisa_1754": ("cryptocurrency",),
    "sisa_813": ("No-Show",),
    "sisa_897": ("Masstige",),
    "sisa_980": ("Rent-Poor",),
    "sisa_1932": ("Externalities",),
    "sisa_2606": ("KOSPI200",),
}

_DEFAULT_STAGES = Path(__file__).resolve().parents[1] / "data" / "stages.json"
_ACRONYM = re.compile(r"(?:[A-Z]{2,5}|[A-Z]{1,5}&[A-Z]{1,5})")
_ENGLISH_NAME = re.compile(r"[A-Za-z][A-Za-z'-]*(?:\s+[A-Za-z][A-Za-z'-]*)+")
_KOREAN = re.compile(r"[가-힣]")
_KOREAN_PARTICLES = tuple(sorted((
    "이", "가", "은", "는", "을", "를", "의", "에", "에서", "에게", "도", "만",
    "랑", "이랑", "와", "과", "로", "으로", "란", "이란", "라는", "이라는",
    "처럼", "보다", "하고", "라고", "이라고", "라", "이라",
), key=len, reverse=True))


def other_name_candidates(term_full: str) -> tuple[str, ...]:
    """괄호 내용과 슬래시로 구분된 표기를 분리한다."""
    parenthesized = re.findall(r"\(([^()]*)\)", term_full)
    outside = re.sub(r"\([^()]*\)", "", term_full)
    pieces = [*parenthesized]
    if "/" in outside:
        pieces.extend(outside.split("/"))
    candidates: list[str] = []
    for piece in pieces:
        for value in re.split(r"[:;,/]", piece):
            value = value.strip()
            if value and value not in candidates:
                candidates.append(value)
    return tuple(candidates)


def _candidate_kind(value: str) -> str:
    if _KOREAN.search(value):
        # LTV비율처럼 약어에 설명용 한글 접미어가 붙은 경우는 약어만 후보로 삼는다.
        if re.fullmatch(r"(?:[A-Z]{2,5}|[A-Z]{1,5}&[A-Z]{1,5})(?:비율)", value):
            return "acronym_with_suffix"
        return "korean"
    if _ACRONYM.fullmatch(value):
        return "acronym"
    if _ENGLISH_NAME.fullmatch(value):
        if value.startswith("Not in ") or " or " in value:
            return "english_fragment"
        return "english_name"
    return "single_english_word" if re.fullmatch(r"[A-Za-z][A-Za-z'-]*", value) else "other"


@lru_cache(maxsize=1)
def automatic_synonym_report() -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[tuple[str, str, str], ...]]]:
    """파일을 한 번만 읽고 등록·보류 후보를 고유 concept_id별로 집계한다."""
    data = json.loads(_DEFAULT_STAGES.read_text(encoding="utf-8"))
    return build_auto_synonyms(data)


def build_auto_synonyms(data: dict) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[tuple[str, str, str], ...]]]:
    """중복 단계의 같은 ID는 하나로 세고 다른 개념 사이의 충돌은 보류한다."""
    names: dict[str, str] = {}
    found: dict[str, set[str]] = defaultdict(set)
    rejected: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    owners: dict[str, set[str]] = defaultdict(set)
    display: dict[str, str] = {}
    canonical_owners: dict[str, set[str]] = defaultdict(set)
    for stage in data["stages"]:
        for concept in stage["concepts"]:
            canonical_owners[concept["term"].casefold()].add(concept["concept_id"])
    for stage in data["stages"]:
        for concept in stage["concepts"]:
            concept_id, term = concept["concept_id"], concept["term"]
            names[concept_id] = term
            term_parts = tuple(
                part.strip() for part in re.split(r"[/·]", term)
                if len(part.strip()) >= 2 and part.strip() != term
            )
            for part in term_parts:
                key = part.casefold()
                owners[key].add(concept_id)
                owners[key].update(canonical_owners.get(key, set()))
                display.setdefault(key, part)
            for candidate in other_name_candidates(concept["term_full"]):
                if candidate == term:
                    continue
                kind = _candidate_kind(candidate)
                if kind == "acronym_with_suffix":
                    candidate = _ACRONYM.match(candidate).group()  # type: ignore[union-attr]
                    kind = "acronym"
                if kind not in {"acronym", "english_name"}:
                    if candidate not in term_parts:
                        rejected[kind].add((concept_id, term, candidate))
                    continue
                key = candidate.casefold()
                owners[key].add(concept_id)
                display.setdefault(key, candidate)
    manual_owners = {
        alias.casefold(): concept_id
        for concept_id, aliases in SYNONYMS_BY_CONCEPT_ID.items()
        for alias in aliases
    }
    for key, concept_ids in owners.items():
        if len(concept_ids) > 1:
            for concept_id in concept_ids:
                rejected["duplicate"].add((concept_id, names[concept_id], display[key]))
            continue
        concept_id = next(iter(concept_ids))
        if key in manual_owners and manual_owners[key] != concept_id:
            rejected["manual_conflict"].add((concept_id, names[concept_id], display[key]))
            continue
        found[concept_id].add(display[key])
    registered = {concept_id: tuple(sorted(aliases, key=str.casefold)) for concept_id, aliases in found.items()}
    report = {kind: tuple(sorted(rows)) for kind, rows in rejected.items()}
    return registered, report


def concept_terms(concept_id: str, term: str, aliases: tuple[str, ...] = ()) -> tuple[str, ...]:
    auto, _ = automatic_synonym_report()
    return tuple(dict.fromkeys((term, *aliases, *SYNONYMS_BY_CONCEPT_ID.get(concept_id, ()), *auto.get(concept_id, ()))))


def term_spans(text: str, term: str) -> list[tuple[int, int]]:
    """영문 뒤 한글은 완전한 조사일 때만 허용하고 용어 본문 위치를 돌려준다."""
    if not term.strip():
        return []
    if re.search(r"[A-Za-z]", term):
        pattern = re.escape(term.strip()).replace(r"\ ", r"\s+")
        spans = []
        for match in re.finditer(rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])", text, re.IGNORECASE):
            tail = text[match.end():]
            if tail and _KOREAN.match(tail):
                if not any(
                    tail.startswith(particle)
                    and (len(tail) == len(particle) or not _KOREAN.match(tail[len(particle)]))
                    for particle in _KOREAN_PARTICLES
                ):
                    continue
            spans.append(match.span())
        return spans
    pattern = r"\s*".join(re.escape(character) for character in term if not character.isspace())
    return [match.span() for match in re.finditer(pattern, text, re.IGNORECASE)]


def term_mentioned(text: str, term: str) -> bool:
    return bool(term_spans(text, term))


def explicit_matches(text: str, entries: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """긴 사전 용어 안에 포함된 짧은 별칭은 명시적 언급에서 제외한다."""
    found = [
        (concept_id, term, start, end)
        for concept_id, term in entries
        for start, end in term_spans(text, term)
    ]
    return list(dict.fromkeys(
        (concept_id, term)
        for concept_id, term, start, end in found
        if not any(
            other_start <= start and end <= other_end and other_end - other_start > end - start
            for _, _, other_start, other_end in found
        )
    ))
