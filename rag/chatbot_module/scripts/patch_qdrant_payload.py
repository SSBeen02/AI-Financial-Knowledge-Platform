"""기존 Qdrant 포인트의 퀴즈 연동 payload를 보강한다.

벡터는 건드리지 않으며 재임베딩하지 않는다. 기본 실행은 dry-run이고,
``--apply``를 명시한 경우에만 payload를 실제로 갱신한다.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from typing import Any

from qdrant_client import QdrantClient

from chatbot.config import Settings

DEFAULT_SOURCE = "시사경제용어사전"
DEFAULT_DOC_VERSION = "sisa_2026"


def payload_patch(payload: dict[str, Any]) -> dict[str, Any]:
    """기존 값을 보존하면서 누락된 표준 메타데이터만 반환한다."""

    concept_id = str(payload.get("concept_id") or payload.get("doc_id") or "").strip()
    if not concept_id:
        return {}
    patch: dict[str, Any] = {}
    if not payload.get("chunk_id"):
        patch["chunk_id"] = concept_id
    if not payload.get("concept_ids"):
        patch["concept_ids"] = [concept_id]
    if not payload.get("doc_version"):
        patch["doc_version"] = DEFAULT_DOC_VERSION
    if not payload.get("source"):
        patch["source"] = DEFAULT_SOURCE
    return patch


def patch_collection(client: Any, collection_name: str, *, apply: bool) -> int:
    """보강 대상 포인트 수를 반환하고 apply일 때만 Qdrant를 수정한다."""

    offset = None
    pending = 0
    while True:
        points, offset = client.scroll(
            collection_name=collection_name,
            limit=128,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            patch = payload_patch(point.payload or {})
            if not patch:
                continue
            pending += 1
            if apply:
                client.set_payload(
                    collection_name=collection_name,
                    points=[point.id],
                    payload=patch,
                )
        if offset is None:
            break
    return pending


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제 Qdrant payload를 갱신한다. 생략하면 변경 예정 건수만 출력한다.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> None:
    args = _parse_args(argv)
    settings = Settings()
    if not settings.qdrant_url or not settings.qdrant_api_key:
        raise SystemExit("QDRANT_URL과 QDRANT_API_KEY가 필요합니다.")
    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    count = patch_collection(client, settings.qdrant_collection, apply=args.apply)
    if args.apply:
        print(f"mode=apply updated={count}")
    else:
        print(f"mode=dry-run pending={count}")


if __name__ == "__main__":
    main()
