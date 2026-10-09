from __future__ import annotations

import pytest

from chatbot.tone import (
    excluded_concept_notice,
    extra_concept_notice,
    has_korean_final_consonant,
    other_stage_notice,
    passed_concept_notice,
    suggested_concept_notice,
    with_korean_particle,
)


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("분업", "분업과"),
        ("특화", "특화와"),
        ("분업/특화", "분업/특화와"),
        ("GDP", "GDP와"),
        ("M", "M과"),
        ("경제 1", "경제 1과"),
        ("경제 2", "경제 2와"),
    ],
)
def test_with_korean_particle_handles_hangul_latin_and_digits(
    term: str,
    expected: str,
) -> None:
    assert with_korean_particle(term, "와/과") == expected


@pytest.mark.parametrize(
    ("term", "particle", "expected"),
    [
        ("분업", "을/를", "분업을"),
        ("정부실패", "을/를", "정부실패를"),
        ("분업", "은/는", "분업은"),
        ("정부실패", "은/는", "정부실패는"),
        ("GDP", "이/가", "GDP가"),
        ("M", "이/가", "M이"),
        ("88만원세대", "와/과", "88만원세대와"),
        ("경제 1", "와/과", "경제 1과"),
        ("집", "으로/로", "집으로"),
        ("학교", "으로/로", "학교로"),
        ("서울", "으로/로", "서울로"),
        ("R", "으로/로", "R로"),
        ("경제 8", "으로/로", "경제 8로"),
    ],
)
def test_common_particle_pairs(
    term: str,
    particle: str,
    expected: str,
) -> None:
    assert with_korean_particle(term, particle) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize("term", ["분업", "M", "경제 0", "경제 8"])
def test_has_korean_final_consonant(term: str) -> None:
    assert has_korean_final_consonant(term) is True


@pytest.mark.parametrize("term", ["특화", "GDP", "경제 2", "경제 9"])
def test_has_no_korean_final_consonant(term: str) -> None:
    assert has_korean_final_consonant(term) is False


@pytest.mark.parametrize(
    ("notice", "expected_start"),
    [
        (passed_concept_notice, "정부실패는 이미 통과한"),
        (extra_concept_notice, "정부실패는 학당의 정규 과정에는"),
        (excluded_concept_notice, "정부실패는 경제 학습 범위 밖의"),
        (suggested_concept_notice, "정부실패는 이번 스테이지에서"),
    ],
)
@pytest.mark.parametrize("tone", ["hao", "modern"])
def test_term_notices_use_the_common_particle_selector(
    notice,
    expected_start: str,
    tone: str,
) -> None:
    assert notice("정부실패", tone).startswith(expected_start)


def test_other_stage_notice_selects_particles_for_term_and_stage_name() -> None:
    notice = other_stage_notice("정부실패", "경제 정책", "시장 이해", "hao")
    assert notice.startswith("정부실패를 궁금해하는")
    assert "경제 정책이 아니라" in notice
