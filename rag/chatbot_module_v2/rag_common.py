"""적재·검색·평가에서 공통으로 쓰는 인코더와 하이브리드 검색 함수.

적재와 검색은 반드시 같은 Dense 모델, 같은 Kiwi 토크나이저 설정을 써야 한다.
"""
from __future__ import annotations

import hashlib
import zlib
from collections import Counter

import numpy as np
from qdrant_client import QdrantClient, models

COLLECTION = "sisa_terms"
DENSE_NAME, SPARSE_NAME = "dense", "sparse"
DENSE_MODEL = "nlpai-lab/KURE-v1"
DENSE_DIM = 1024
RERANK_MODEL = "dragonkue/bge-reranker-v2-m3-ko"

# BM25 파라미터 (일반적인 기본값)
BM25_K1, BM25_B = 1.2, 0.75

# 검색에 의미 있는 품사만 사용: 일반·고유·의존명사, 동사·형용사 어근, 어근, 외국어, 한자, 숫자
KEEP_TAGS = {"NNG", "NNP", "NNB", "VV", "VA", "XR", "SL", "SH", "SN"}


# ---------------------------------------------------------------- Sparse (Kiwi + BM25)
class SparseEncoder:
    """Kiwi 형태소 분석 → 토큰 해시 → BM25 TF 가중치.

    IDF는 Qdrant 컬렉션의 Modifier.IDF가 서버에서 계산하므로,
    문서 쪽에는 TF 성분만, 질의 쪽에는 토큰별 1.0만 넣는다.
    """

    def __init__(self, user_words: list[str] | None = None, avgdl: float | None = None):
        from kiwipiepy import Kiwi

        self.kiwi = Kiwi()
        for w in user_words or []:
            self.kiwi.add_user_word(w, "NNP")
        self.avgdl = avgdl

    def tokenize(self, text: str) -> list[str]:
        return [t.form.lower() for t in self.kiwi.tokenize(text) if t.tag in KEEP_TAGS]

    @staticmethod
    def _index(token: str) -> int:
        return zlib.crc32(token.encode("utf-8"))  # 실행마다 바뀌지 않는 안정적 해시

    def fit(self, texts: list[str]) -> list[list[str]]:
        toks = [self.tokenize(t) for t in texts]
        self.avgdl = float(np.mean([len(t) for t in toks])) or 1.0
        return toks

    def encode_doc(self, tokens: list[str]) -> models.SparseVector:
        assert self.avgdl, "fit()을 먼저 호출하거나 avgdl을 지정해야 함"
        tf, dl = Counter(tokens), len(tokens)
        norm = BM25_K1 * (1 - BM25_B + BM25_B * dl / self.avgdl)
        return self._to_vec({tok: c * (BM25_K1 + 1) / (c + norm) for tok, c in tf.items()})

    def encode_query(self, text: str) -> models.SparseVector:
        return self._to_vec({tok: 1.0 for tok in set(self.tokenize(text))})

    def _to_vec(self, weights: dict[str, float]) -> models.SparseVector:
        merged: dict[int, float] = {}
        for tok, w in weights.items():  # 해시 충돌 시 가중치 합산
            i = self._index(tok)
            merged[i] = merged.get(i, 0.0) + w
        return models.SparseVector(indices=list(merged), values=list(merged.values()))


# ---------------------------------------------------------------- Dense
class DenseEncoder:
    """sentence-transformers 기반 Dense 인코더. 'debug-hash'는 코드 점검용 가짜 모델."""

    def __init__(self, model_name: str = DENSE_MODEL, device: str | None = None):
        self.model_name = model_name
        if model_name == "debug-hash":
            self.model, self.dim = None, DENSE_DIM
        else:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(model_name, device=device)
            self.dim = self.model.get_sentence_embedding_dimension()

    def encode(self, texts: list[str], batch_size: int = 16, show_progress: bool = False) -> np.ndarray:
        if self.model is None:
            return np.stack([self._debug(t) for t in texts])
        return self.model.encode(
            texts, batch_size=batch_size, normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=show_progress,
        ).astype(np.float32)

    def _debug(self, text: str) -> np.ndarray:
        seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
        v = np.random.default_rng(seed).standard_normal(self.dim).astype(np.float32)
        return v / np.linalg.norm(v)


# ---------------------------------------------------------------- Reranker (Cross-Encoder)
class Reranker:
    """질문-문서 쌍의 관련성 점수(0~1)를 직접 계산해 후보를 다시 정렬한다.
    'debug-overlap'은 코드 점검용 가짜 모델(글자 겹침 비율)."""

    def __init__(self, model_name: str = RERANK_MODEL, device: str | None = None, max_length: int = 512):
        self.model_name = model_name
        if model_name == "debug-overlap":
            self.model = None
        else:
            from sentence_transformers import CrossEncoder

            self.model = CrossEncoder(model_name, device=device, max_length=max_length)

    def score(self, query: str, docs: list[str], batch_size: int = 16) -> np.ndarray:
        if self.model is None:
            q = set(query.replace(" ", ""))
            return np.array([len(q & set(d)) / max(len(q), 1) for d in docs], dtype=np.float32)
        s = np.asarray(self.model.predict([(query, d) for d in docs], batch_size=batch_size), dtype=np.float32)
        if s.min() < 0 or s.max() > 1:  # 버전에 따라 로짓이 나오면 시그모이드로 0~1 변환
            s = 1 / (1 + np.exp(-s))
        return s


# ---------------------------------------------------------------- 컬렉션 / 검색
def create_collection(client: QdrantClient, name: str, dim: int, recreate: bool = False) -> None:
    if client.collection_exists(name):
        if not recreate:
            return
        client.delete_collection(name)
    client.create_collection(
        collection_name=name,
        vectors_config={DENSE_NAME: models.VectorParams(size=dim, distance=models.Distance.COSINE)},
        sparse_vectors_config={SPARSE_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    for field in ("stages", "domain", "doc_id"):
        client.create_payload_index(name, field_name=field, field_schema=models.PayloadSchemaType.KEYWORD)


def stage_filter(stage: str | None) -> models.Filter | None:
    """stages 배열에 해당 값이 하나라도 있으면 매칭된다."""
    if not stage:
        return None
    return models.Filter(must=[models.FieldCondition(key="stages", match=models.MatchValue(value=stage))])


def search(client: QdrantClient, query: str, dense: DenseEncoder, sparse: SparseEncoder,
           mode: str = "hybrid", k: int = 5, stage: str | None = None,
           collection: str = COLLECTION, prefetch_k: int = 30):
    """mode: 'dense' | 'sparse' | 'hybrid'(RRF). 반환: ScoredPoint 목록."""
    flt = stage_filter(stage)
    dq = dense.encode([query])[0].tolist() if mode in ("dense", "hybrid") else None
    sq = sparse.encode_query(query) if mode in ("sparse", "hybrid") else None
    if mode == "dense":
        res = client.query_points(collection, query=dq, using=DENSE_NAME, limit=k,
                                  query_filter=flt, with_payload=True)
    elif mode == "sparse":
        res = client.query_points(collection, query=sq, using=SPARSE_NAME, limit=k,
                                  query_filter=flt, with_payload=True)
    else:
        res = client.query_points(
            collection,
            prefetch=[
                models.Prefetch(query=dq, using=DENSE_NAME, limit=prefetch_k, filter=flt),
                models.Prefetch(query=sq, using=SPARSE_NAME, limit=prefetch_k, filter=flt),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=k, with_payload=True,
        )
    return res.points


def rerank_search(client: QdrantClient, query: str, dense: DenseEncoder, reranker: Reranker,
                  k: int = 5, candidates: int = 20, stage: str | None = None,
                  collection: str = COLLECTION):
    """Dense로 후보 N개 검색 → 리랭커로 재정렬. 반환: [(ScoredPoint, rerank_score), ...] 점수 내림차순."""
    pts = search(client, query, dense, None, mode="dense", k=candidates, stage=stage, collection=collection)
    if not pts:
        return []
    scores = reranker.score(query, [p.payload["text"] for p in pts])
    order = np.argsort(-scores)[:k]
    return [(pts[i], float(scores[i])) for i in order]


def top_dense_score(client: QdrantClient, query: str, dense: DenseEncoder,
                    collection: str = COLLECTION) -> float:
    """DB에 없는 질문 판별용: Dense 코사인 유사도 최고점 (RRF 점수는 유사도가 아니라서 쓰지 않음)."""
    res = client.query_points(collection, query=dense.encode([query])[0].tolist(),
                              using=DENSE_NAME, limit=1)
    return res.points[0].score if res.points else 0.0