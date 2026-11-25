"""Offline catalog contract for all five stages and the Stage 5 fixed quiz bank.

This cannot prove deployed browser behavior, live LLM retrieval, or user progress.
"""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_all_five_stage_catalogs_are_complete():
    catalog = json.loads((ROOT / "rag/chatbot_module/data/stages.json").read_text(encoding="utf-8"))
    stages = catalog["stages"]
    assert [stage["id"] for stage in stages] == [f"stage{i}" for i in range(1, 6)]
    assert [stage["order"] for stage in stages] == list(range(1, 6))
    assert sum(len(stage["concepts"]) for stage in stages) == catalog["total_concepts"]
    all_ids = set()
    for stage in stages:
        concepts = stage["concepts"]
        assert len(concepts) == stage["concept_count"]
        assert [item["order"] for item in concepts] == list(range(1, len(concepts) + 1))
        ids = [item["concept_id"] for item in concepts]
        assert len(ids) == len(set(ids)), stage["id"]
        all_ids.update(ids)
    assert len(all_ids) == catalog["unique_concepts"]


def test_stage5_fixed_bank_covers_every_stage5_concept():
    from app.services.stage5_bank import fixed_questions, load_bank

    catalog = json.loads((ROOT / "rag/chatbot_module/data/stages.json").read_text(encoding="utf-8"))
    stage5_ids = {item["concept_id"] for item in catalog["stages"][4]["concepts"]}
    assert set(load_bank()) == stage5_ids
    for concept_id in stage5_ids:
        assert len(fixed_questions(concept_id)) == 3
