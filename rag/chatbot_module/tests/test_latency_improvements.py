"""배포 지연 개선(질문 임베딩 캐시·병렬 검색·첫 덩어리 조기 방출·워밍업) 회귀 테스트."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import numpy as np
from qdrant_client import models

from chatbot.answer_format import IncrementalAnswerFormatter
from chatbot.config import Settings
from chatbot.embedding_cache import CachedQueryEncoder
from chatbot.retrieval import Retriever, concept_point_id


class CountingDense:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def encode(self, texts, *args, **kwargs):
        self.calls.append(texts)
        return np.array([[float(len(t)), 1.0] for t in texts], dtype=np.float32)


def test_cache_reuses_single_query_embedding_only() -> None:
    dense = CountingDense()
    cached = CachedQueryEncoder(dense, max_entries=2)
    first = cached.encode(["복리"])
    second = cached.encode(["복리"])
    assert len(dense.calls) == 1
    assert np.array_equal(first, second)
    second[0][0] = 999.0  # 호출자가 결과를 바꿔도 캐시 값은 그대로다.
    assert cached.encode(["복리"])[0][0] == first[0][0]
    cached.encode(["복리", "단리"])  # 배치 인코딩은 캐시하지 않는다.
    cached.encode(["복리", "단리"])
    cached.encode(["단리"], batch_size=4)  # 추가 인자가 있으면 캐시하지 않는다.
    assert len(dense.calls) == 4


def test_cache_evicts_least_recently_used() -> None:
    dense = CountingDense()
    cached = CachedQueryEncoder(dense, max_entries=2)
    cached.encode(["a"])
    cached.encode(["b"])
    cached.encode(["a"])  # a를 최근 사용으로 갱신
    cached.encode(["c"])  # b가 밀려난다
    assert len(cached) == 2
    calls = len(dense.calls)
    cached.encode(["a"])
    assert len(dense.calls) == calls
    cached.encode(["b"])
    assert len(dense.calls) == calls + 1
    cached.clear()
    assert len(cached) == 0


class _Point:
    def __init__(self, concept_id: str, score: float) -> None:
        self.id = concept_point_id(concept_id)
        self.score = score
        self.payload = {"concept_id": concept_id, "term": concept_id, "text": f"{concept_id} 설명"}


class _SlowClient:
    """컬렉션마다 다른 지연을 줘서 완료 순서가 원래 순서와 달라지게 한다."""

    delays = {
        "sisa_terms": 0.30,
        "fss_practical_finance_4e_3p_kure_v1": 0.05,
        "bok_economic_financial_terms_2026_kure_v1_rrf": 0.15,
    }

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def query_points(self, collection_name=None, **kwargs):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delays[collection_name])
        finally:
            with self._lock:
                self.active -= 1
        if collection_name == "sisa_terms":
            return SimpleNamespace(points=[_Point("sisa_1", 0.7), _Point("sisa_2", 0.6)])
        if collection_name == "fss_practical_finance_4e_3p_kure_v1":
            return SimpleNamespace(points=[SimpleNamespace(
                id="book_1", score=0.5, vector={"dense": [0.1, 0.2]},
                payload={"content_markdown": "복리 설명", "section": "복리"},
            )])
        return SimpleNamespace(points=[_Point("bok_1", 0.6)])


class _CountingSparse:
    collection = "fss_practical_finance_4e_3p_kure_v1"

    def __init__(self) -> None:
        self.calls = 0
        self.threads: set[str] = set()

    def encode_query(self, query):
        self.calls += 1
        self.threads.add(threading.current_thread().name)
        return models.SparseVector(indices=[1], values=[1.0])


def test_parallel_search_keeps_sequential_order_and_overlaps_qdrant_calls() -> None:
    dense = CountingDense()
    sparse = _CountingSparse()
    client = _SlowClient()
    retriever = Retriever(client, dense, Settings(_env_file=None, llm_model="gpt-test"), sparse=sparse)
    started = time.perf_counter()
    result = retriever.search("복리")
    elapsed = time.perf_counter() - started
    assert [doc.concept_id for doc in result.sources][0] == "sisa_1"
    assert [doc.collection for doc in result.sources] == sorted(
        [doc.collection for doc in result.sources],
        key=["sisa_terms", "fss_practical_finance_4e_3p_kure_v1",
             "bok_economic_financial_terms_2026_kure_v1_rrf"].index,
    )
    assert result.top_score == 0.7 and result.band == "high"
    assert len(dense.calls) == 1  # 임베딩은 fan-out 전에 한 번만
    assert sparse.calls == 1 and sparse.threads == {threading.current_thread().name}
    assert client.max_active >= 2  # Qdrant 왕복이 겹쳤다
    assert elapsed < sum(_SlowClient.delays.values())


def _first_chunk(text: str, step: int = 1) -> tuple[list[str], IncrementalAnswerFormatter]:
    formatter = IncrementalAnswerFormatter()
    deltas: list[str] = []
    for index in range(0, len(text), step):
        deltas.extend(formatter.feed(text[index:index + step]))
        if deltas:
            break
    return deltas, formatter


def test_first_chunk_is_emitted_before_sentence_end() -> None:
    text = "복리이자는 원금뿐 아니라 그동안 붙은 이자에도 다시 이자가 붙는 방식이오. 단리는 원금에만 붙소."
    deltas, formatter = _first_chunk(text)
    assert deltas, "첫 덩어리가 문장 끝 전에 나와야 한다"
    assert not deltas[0].endswith("이오.")
    assert len(formatter.body) >= 15
    streamed = IncrementalAnswerFormatter()
    for char in text:
        streamed.feed(char)
    streamed.finish()
    whole = IncrementalAnswerFormatter()
    whole.feed(text)
    whole.finish()
    assert streamed.body == whole.body


def test_first_chunk_rule_does_not_leak_source_or_open_markup() -> None:
    source = "출처: 모델이 적은 아주 긴 출처 문구가 여기에 이어지고 계속 이어진다"
    deltas, _ = _first_chunk(source)
    assert deltas == []
    bold = "**복리이자와 단리이자의 차이를 길게 설명하는 굵은 글씨 문장이 계속된다"
    deltas, _ = _first_chunk(bold)
    assert deltas == []


def test_warm_up_failure_does_not_stop_startup(monkeypatch) -> None:
    from chatbot import deps

    cleared = []

    class Broken:
        def search(self, query):
            raise RuntimeError("qdrant offline")

    monkeypatch.setattr(deps, "get_retriever", lambda: Broken())
    monkeypatch.setattr(deps, "get_dense_encoder", lambda: SimpleNamespace(clear=lambda: cleared.append(1)))
    monkeypatch.delenv("CHATBOT_WARMUP", raising=False)
    assert deps.warm_up_retrieval() is None
    assert cleared == [1]


def test_warm_up_runs_search_and_can_be_disabled(monkeypatch) -> None:
    from chatbot import deps

    queries = []
    monkeypatch.setattr(deps, "get_retriever", lambda: SimpleNamespace(search=queries.append))
    monkeypatch.setattr(deps, "get_dense_encoder", lambda: SimpleNamespace(clear=lambda: None))
    monkeypatch.setenv("CHATBOT_WARMUP", "true")
    assert deps.warm_up_retrieval() is not None
    assert queries == [deps.WARMUP_QUERY]
    monkeypatch.setenv("CHATBOT_WARMUP", "false")
    assert deps.warm_up_retrieval() is None
    assert queries == [deps.WARMUP_QUERY]
