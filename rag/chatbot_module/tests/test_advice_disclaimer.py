"""고지 문구는 질문 의도와 실제 답변에 따라 서버에서 한 번만 붙인다."""

from chatbot.answer_format import ADVICE_DISCLAIMER, with_advice_disclaimer


def test_simple_education_has_no_disclaimer() -> None:
    for question in (
        "투자가 뭐야?", "ETF와 펀드의 차이가 뭐야?", "저축과 예산 관리 방법은?",
        "신용점수는 무엇인가요?", "보이스피싱 예방법은?",
    ):
        assert ADVICE_DISCLAIMER not in with_advice_disclaimer(
            "구조와 위험을 설명하오.", question, "ALLOW"
        )


def test_specific_product_risk_analysis_gets_one_disclaimer() -> None:
    answer = "KODEX 200 ETF의 변동성과 수수료를 비교하오."
    question = "KODEX 200 ETF의 투자 위험을 다른 상품과 비교해 줘."
    assert with_advice_disclaimer(answer, question, "ALLOW").count(ADVICE_DISCLAIMER) == 1
    assert with_advice_disclaimer(answer + "\n" + ADVICE_DISCLAIMER, question, "ALLOW").count(ADVICE_DISCLAIMER) == 1


def test_actual_answer_must_analyze_a_decision() -> None:
    assert ADVICE_DISCLAIMER not in with_advice_disclaimer(
        "지금은 답변할 수 없소.", "특정 주식을 지금 사도 될까?", "ALLOW"
    )


def test_block_and_unrelated_model_disclaimer_are_removed() -> None:
    answer = f"피해를 예방하시오.\n\n{ADVICE_DISCLAIMER}"
    assert ADVICE_DISCLAIMER not in with_advice_disclaimer(answer, "금융사기 예방법", "BLOCK")
    assert ADVICE_DISCLAIMER not in with_advice_disclaimer(answer, "투자가 뭐야?", "ALLOW")
