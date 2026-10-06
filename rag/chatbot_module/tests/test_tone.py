from __future__ import annotations

import pytest

from chatbot.tone import has_korean_final_consonant, with_korean_particle


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
    assert with_korean_particle(term, with_final="과", without_final="와") == expected


@pytest.mark.parametrize("term", ["분업", "M", "경제 0", "경제 8"])
def test_has_korean_final_consonant(term: str) -> None:
    assert has_korean_final_consonant(term) is True


@pytest.mark.parametrize("term", ["특화", "GDP", "경제 2", "경제 9"])
def test_has_no_korean_final_consonant(term: str) -> None:
    assert has_korean_final_consonant(term) is False
