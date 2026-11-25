from __future__ import annotations

from types import SimpleNamespace

from scripts.patch_qdrant_payload import DEFAULT_SOURCE, patch_collection, payload_patch


class FakeQdrant:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def scroll(self, **kwargs):
        del kwargs
        return (
            [
                SimpleNamespace(id="1", payload={"concept_id": "sisa_1"}),
                SimpleNamespace(
                    id="2",
                    payload={
                        "concept_id": "sisa_2",
                        "chunk_id": "sisa_2",
                        "concept_ids": ["sisa_2"],
                        "doc_version": "custom",
                        "source": "기존 출처",
                    },
                ),
            ],
            None,
        )

    def set_payload(self, **kwargs) -> None:
        self.calls.append(kwargs)


def test_payload_patch_adds_only_missing_standard_metadata() -> None:
    assert payload_patch({"doc_id": "sisa_745"}) == {
        "chunk_id": "sisa_745",
        "concept_ids": ["sisa_745"],
        "doc_version": "sisa_2026",
        "source": DEFAULT_SOURCE,
    }
    assert payload_patch({"term": "ID 없음"}) == {}


def test_patch_collection_dry_run_and_apply() -> None:
    client = FakeQdrant()
    assert patch_collection(client, "sisa_terms", apply=False) == 1
    assert client.calls == []

    assert patch_collection(client, "sisa_terms", apply=True) == 1
    assert client.calls == [
        {
            "collection_name": "sisa_terms",
            "points": ["1"],
            "payload": {
                "chunk_id": "sisa_1",
                "concept_ids": ["sisa_1"],
                "doc_version": "sisa_2026",
                "source": DEFAULT_SOURCE,
            },
        }
    ]
