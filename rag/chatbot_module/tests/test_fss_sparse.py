"""교재 업로드 때의 어휘 ID/IDF를 질의에도 사용하는지 확인."""

import json

from chatbot.fss_sparse import FssSparseEncoder, MODEL_PATH


def test_fss_query_uses_uploaded_vocabulary_and_idf() -> None:
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    vector = FssSparseEncoder().encode_query("은행")
    bank_id = model["vocabulary"].index("은행")
    assert vector.indices == [bank_id]
    assert vector.values == [model["idf"][bank_id]]


def test_fss_query_without_indexed_terms_is_empty() -> None:
    assert FssSparseEncoder().encode_query("이 그").indices == []
