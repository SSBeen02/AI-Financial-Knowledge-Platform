"""질문 임베딩 재사용 캐시.

배포 환경(공유 CPU)에서 KURE 쿼리 임베딩이 질문당 수 초 걸리므로, 같은 질문 문자열의
단일 쿼리 임베딩만 프로세스 안에 보관한다. 문서·배치 인코딩은 그대로 위임한다.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

from chatbot.timing import current_timing

DEFAULT_MAX_ENTRIES = 512


class CachedQueryEncoder:
    """`encode([query])` 형태의 단일 쿼리 호출 결과만 LRU로 재사용한다."""

    def __init__(self, delegate: Any, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._delegate = delegate
        self._max_entries = max_entries
        self._entries: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()

    def encode(self, texts: Any, *args: Any, **kwargs: Any) -> Any:
        key = _single_query_key(texts, args, kwargs)
        if key is None or self._max_entries <= 0:
            return self._delegate.encode(texts, *args, **kwargs)
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
        timing = current_timing()
        if cached is not None:
            if timing is not None:
                timing.mark("embedding_cache_hit")
            return cached.copy() if hasattr(cached, "copy") else cached
        if timing is not None:
            timing.mark("embedding_cache_miss")
        result = self._delegate.encode(texts, *args, **kwargs)
        stored = result.copy() if hasattr(result, "copy") else result
        with self._lock:
            self._entries[key] = stored
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return result

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)


def _single_query_key(texts: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    if args or kwargs:
        return None
    if isinstance(texts, (list, tuple)) and len(texts) == 1 and isinstance(texts[0], str):
        return texts[0]
    return None
