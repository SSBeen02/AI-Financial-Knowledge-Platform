from __future__ import annotations

import pickle

import pytest
from qdrant_client import models

from scripts.evaluate_ragas import _answer_for_scoring, _decode_point, select_cases


def test_select_cases_covers_question_types_before_filling() -> None:
    rows = [
        {"qid": "Q001", "질문유형": "정확 용어"},
        {"qid": "Q002", "질문유형": "정확 용어"},
        {"qid": "Q003", "질문유형": "풀어쓴 질문"},
        {"qid": "Q004", "질문유형": "DB에 없음"},
    ]
    assert [row["qid"] for row in select_cases(rows, 3)] == ["Q001", "Q003", "Q004"]
    assert [row["qid"] for row in select_cases(rows, 4)] == ["Q001", "Q003", "Q004", "Q002"]


def test_local_qdrant_point_decoder_accepts_expected_model() -> None:
    point = models.PointStruct(id="1", vector={"dense": [0.0, 1.0]}, payload={"text": "설명"})
    decoded = _decode_point(pickle.dumps(point))
    assert decoded.id == "1"
    assert decoded.payload == {"text": "설명"}


def test_local_qdrant_point_decoder_rejects_executable_pickle() -> None:
    class Executable:
        def __reduce__(self):
            return (print, ("should never execute",))

    with pytest.raises(ValueError, match="Unsupported pickle operation"):
        _decode_point(pickle.dumps(Executable()))


def test_answer_scoring_excludes_attribution_footer() -> None:
    answer = "기회비용은 포기한 최선의 대안 가치이오.\n\n핵심 정의 출처: 시사경제용어사전\n※ 보충 설명은 일반적인 경제 상식을 바탕으로 했소"
    assert _answer_for_scoring(answer) == "기회비용은 포기한 최선의 대안 가치이오."
