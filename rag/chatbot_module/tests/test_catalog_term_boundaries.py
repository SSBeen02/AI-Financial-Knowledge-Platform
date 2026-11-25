"""Generate term matching checks from every distinct stage concept."""

from chatbot.concepts import load_stage_catalog
from chatbot.concept_synonyms import concept_terms, explicit_matches, term_mentioned
from tests.conftest import STAGES_PATH


def _catalog_entries():
    catalog = load_stage_catalog(STAGES_PATH)
    concepts = {ref.concept_id: ref for stage in catalog.stages.values() for ref in stage.concepts}
    entries = [(ref.concept_id, term) for ref in concepts.values()
               for term in concept_terms(ref.concept_id, ref.term)]
    return concepts, entries


def test_every_catalog_name_and_synonym_matches_question_forms():
    concepts, entries = _catalog_entries()
    for concept_id, term in entries:
        for question in (f"{term}가 뭐야?", f"{term}이 뭐야?",
                         f"{term}에 대해 알려줘", f"{term} 설명해줘"):
            assert concept_id in {owner for owner, _ in explicit_matches(question, entries)}, (concept_id, term, question)


def test_all_contained_cross_concept_terms_prefer_longer_name():
    _, entries = _catalog_entries()
    pairs = [(short_id, short, long_id, long) for short_id, short in entries
             for long_id, long in entries if short_id != long_id and short.casefold() in long.casefold()
             and len(short) < len(long)]
    assert pairs
    for short_id, short, long_id, long in pairs:
        matched = {owner for owner, _ in explicit_matches(f"{long}에 대해 알려줘", entries)}
        assert long_id in matched and short_id not in matched, (short, long, matched)


def test_every_english_alias_rejects_attached_korean_nouns():
    _, entries = _catalog_entries()
    english = [term for _, term in entries if any("A" <= char.upper() <= "Z" for char in term)]
    assert english
    for term in english:
        for suffix in ("갭", "형", "율"):
            assert not term_mentioned(f"{term}{suffix}이 뭐야?", term), (term, suffix)
