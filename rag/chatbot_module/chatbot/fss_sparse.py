"""금융감독원 교재 적재 때 사용한 Kiwi BM25 질의 인코딩."""

from __future__ import annotations

import json
from pathlib import Path

from qdrant_client import models


MODEL_PATH = Path(__file__).resolve().parents[1] / "data" / "fss_hybrid_sparse_model.json"
STOPWORDS = {"것", "수", "등", "때", "이", "그", "하다", "되다", "있다", "없다", "대한", "위한"}


class FssSparseEncoder:
    """업로드 당시의 어휘 ID와 IDF를 그대로 사용한다."""

    def __init__(self, model_path: Path = MODEL_PATH) -> None:
        from kiwipiepy import Kiwi

        model = json.loads(model_path.read_text(encoding="utf-8"))
        vocabulary = model["vocabulary"]
        self._idf = model["idf"]
        if model["document_count"] != 502 or len(vocabulary) != len(self._idf):
            raise ValueError("금융감독원 교재 BM25 모델이 적재된 컬렉션과 일치하지 않습니다.")
        self._term_id = {term: index for index, term in enumerate(vocabulary)}
        self._kiwi = Kiwi()

    def encode_query(self, text: str) -> models.SparseVector:
        terms = {
            token.form.casefold()
            for token in self._kiwi.tokenize(text)
            if (token.tag.startswith(("NN", "VV", "VA")) or token.tag in ("SL", "SN"))
            and len(token.form) > 1
            and token.form not in STOPWORDS
        }
        indices = sorted(self._term_id[term] for term in terms if term in self._term_id)
        return models.SparseVector(indices=indices, values=[self._idf[index] for index in indices])
