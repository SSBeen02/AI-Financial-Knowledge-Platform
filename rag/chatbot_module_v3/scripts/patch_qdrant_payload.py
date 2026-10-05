"""기존 Qdrant 포인트에 퀴즈 연동용 payload만 추가한다.

벡터는 건드리지 않으며 재임베딩하지 않는다. 실행 전 .env의 QDRANT_*를 확인한다.
"""

from __future__ import annotations

from qdrant_client import QdrantClient

from chatbot.config import Settings


def main() -> None:
    settings = Settings()
    if not settings.qdrant_url or not settings.qdrant_api_key:
        raise SystemExit("QDRANT_URL과 QDRANT_API_KEY가 필요합니다.")
    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    offset = None
    updated = 0
    while True:
        points, offset = client.scroll(
            collection_name=settings.qdrant_collection,
            limit=128,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            concept_id = str(payload.get("concept_id") or payload.get("doc_id") or "").strip()
            if not concept_id:
                continue
            client.set_payload(
                collection_name=settings.qdrant_collection,
                points=[point.id],
                payload={
                    "chunk_id": concept_id,
                    "concept_ids": [concept_id],
                    "doc_version": "sisa_2026",
                },
            )
            updated += 1
        if offset is None:
            break
    print(f"updated={updated}")


if __name__ == "__main__":
    main()
