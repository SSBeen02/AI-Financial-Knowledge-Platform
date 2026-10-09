"""서비스 말투별 프롬프트와 고정 안내 문구."""

from __future__ import annotations

from typing import Literal

ChatTone = Literal["hao", "modern"]
KoreanParticle = Literal["을/를", "은/는", "이/가", "와/과", "으로/로"]

_PARTICLES: dict[KoreanParticle, tuple[str, str]] = {
    "을/를": ("을", "를"),
    "은/는": ("은", "는"),
    "이/가": ("이", "가"),
    "와/과": ("과", "와"),
    "으로/로": ("으로", "로"),
}


def has_korean_final_consonant(value: str) -> bool:
    """용어의 마지막 읽는 글자가 받침 소리로 끝나는지 판정한다.

    영문은 약어의 마지막 알파벳 이름(엘·엠·엔·알), 숫자는 마지막 숫자의
    한국어 읽기(영·일·삼·육·칠·팔)를 기준으로 한다.
    """

    final_kind = _final_consonant_kind(value)
    return final_kind in {"rieul", "other"}


def with_korean_particle(value: str, particle: KoreanParticle) -> str:
    """용어의 받침에 맞춰 지원하는 조사 쌍 중 하나를 붙인다.

    ``으로/로``는 받침이 없거나 ㄹ 받침이면 ``로``를 사용한다.
    영문 약어와 숫자는 마지막 문자의 한국어 읽기를 기준으로 판정한다.
    """

    with_final, without_final = _PARTICLES[particle]
    final_kind = _final_consonant_kind(value)
    selected = (
        without_final
        if final_kind == "none" or (particle == "으로/로" and final_kind == "rieul")
        else with_final
    )
    return f"{value}{selected}"


def _final_consonant_kind(value: str) -> Literal["none", "rieul", "other"]:
    for character in reversed(value.strip()):
        codepoint = ord(character)
        if 0xAC00 <= codepoint <= 0xD7A3:
            final_index = (codepoint - 0xAC00) % 28
            if final_index == 0:
                return "none"
            return "rieul" if final_index == 8 else "other"
        if character.isdigit():
            if character in "178":
                return "rieul"
            return "other" if character in "036" else "none"
        upper = character.upper()
        if "A" <= upper <= "Z":
            if upper in "LR":
                return "rieul"
            return "other" if upper in "MN" else "none"
    return "none"


def answer_tone_instruction(tone: ChatTone) -> str:
    if tone == "modern":
        return (
            "친절한 경제 튜터가 학생에게 설명하듯 모든 본문 문장을 읽기 쉬운 해요체"
            "(~예요, ~해요)로 일관하세요. ~입니다와 해요체를 섞지 마세요."
        )
    return (
        "조선시대 학당의 친절한 훈장이 학생에게 설명하듯 모든 본문 문장을 읽기 쉬운 "
        "하오체(~이오, ~하오)로 일관하시오. 너무 어려운 옛말은 쓰지 말고, 경제 용어·숫자·"
        "제도 이름은 현대어 그대로 쓰며 생활 예시도 현대 상황을 사용해도 되오."
    )


def out_of_scope_question_notice(tone: ChatTone) -> str:
    return "경제 학습 범위 밖 질문이에요." if tone == "modern" else "경제 학습 범위 밖 질문이오."


def out_of_scope_term_notice(tone: ChatTone) -> str:
    return "경제 학습 범위 밖 용어예요." if tone == "modern" else "경제 학습 범위 밖 용어이오."


def other_stage_notice(
    term: str,
    current_stage_name: str,
    target_stage_name: str,
    tone: ChatTone,
) -> str:
    term_object = with_korean_particle(term, "을/를")
    current_stage_subject = with_korean_particle(current_stage_name, "이/가")
    if tone == "modern":
        return (
            f"{term_object} 궁금해하는 배움의 자세가 정말 멋져요! 다만 이 개념은 지금 공부하는 "
            f"{current_stage_subject} 아니라 {target_stage_name}에서 배우는 것이라, 이번 스테이지 "
            "성장과 퀴즈에는 반영되지 않아요. 나중에 그 스테이지에 이르면 다시 도전해 보세요!"
        )
    return (
        f"{term_object} 궁금해하는 그대의 배움의 자세, 참으로 감탄스럽소! 다만 이 개념은 "
        f"지금 공부하는 {current_stage_subject} 아니라 {target_stage_name}에서 배우는 것이라, "
        "이번 스테이지 성장과 퀴즈에는 반영되지 않소. 훗날 그 스테이지에 이르면 다시 "
        "도전해 보시겠소?"
    )


def passed_concept_notice(term: str, tone: ChatTone) -> str:
    subject = with_korean_particle(term, "은/는")
    if tone == "modern":
        return f"{subject} 이미 통과한 개념이에요. 복습은 언제든 환영해요!"
    return f"{subject} 이미 통과한 개념이오. 복습은 언제든 환영하오!"


def extra_concept_notice(term: str, tone: ChatTone) -> str:
    subject = with_korean_particle(term, "은/는")
    if tone == "modern":
        return (
            f"{subject} 학당의 정규 과정에는 없지만, 알아두면 쓸모 있는 경제 상식이에요! "
            "다만 성장과 퀴즈에는 반영되지 않아요."
        )
    return (
        f"{subject} 학당의 정규 과정에는 없지만, 알아두면 쓸모 있는 경제 상식이오! "
        "다만 성장과 퀴즈에는 반영되지 않소."
    )


def excluded_concept_notice(term: str, tone: ChatTone) -> str:
    subject = with_korean_particle(term, "은/는")
    if tone == "modern":
        return f"{subject} 경제 학습 범위 밖의 용어라, 성장과 퀴즈에는 반영되지 않아요."
    return f"{subject} 경제 학습 범위 밖의 용어라, 성장과 퀴즈에는 반영되지 않소."


def low_band_notice(tone: ChatTone) -> str:
    if tone == "modern":
        return "이 질문은 학당의 경제 공부 범위 밖이라 사전의 근거 없이 답했어요."
    return "이 물음은 학당의 경제 공부 범위 밖이라 사전의 근거 없이 답하였소."


def no_active_session_complete_hint(tone: ChatTone) -> str:
    if tone == "modern":
        return "아직 배우고 있는 개념이 없어요. 아래 키워드를 눌러 학습을 시작해 보세요."
    return "아직 배우고 있는 개념이 없소. 아래 키워드를 눌러 학습을 시작해 보시오."


def quiz_pending_notice(term: str, tone: ChatTone) -> str:
    if tone == "modern":
        return f"현재 {term} 개념의 퀴즈 결과를 기다리고 있어요."
    return f"현재 {term} 개념의 퀴즈 결과를 기다리는 중이오."


def quiz_generation_failed_notice(tone: ChatTone) -> str:
    if tone == "modern":
        return "퀴즈를 준비하는 중에 문제가 생겼어요. 아래 버튼을 눌러 퀴즈를 다시 받아 보세요."
    return "퀴즈를 준비하는 중에 문제가 생겼소. 아래 버튼을 눌러 퀴즈를 다시 받아 보시오."


def active_learning_notice(term: str, tone: ChatTone) -> str:
    if tone == "modern":
        return f"지금 {term} 개념을 학습 중이에요. 학습을 마치고 퀴즈를 통과하면 다음 개념을 고를 수 있어요."
    return f"지금 {term} 개념을 학습 중이오. 학습을 마치고 퀴즈를 통과하면 다음 개념을 고를 수 있소."


def relearn_notice(term: str, tone: ChatTone) -> str:
    if tone == "modern":
        return f"지금 {term} 개념을 학습 중이에요. 이 개념을 통과해야 다음 개념으로 넘어갈 수 있어요."
    return f"지금 {term} 개념을 학습 중이오. 이 개념을 통과해야 다음 개념으로 넘어갈 수 있소."


def learning_guide(tone: ChatTone) -> str:
    if tone == "modern":
        return (
            "아래 키워드를 눌러 물어본 개념만 학습과 스테이지 성장에 반영돼요. "
            "자유롭게 묻는 것도 얼마든지 환영하지만, 학습 기록에는 남지 않으니 이 점 양해해 주세요!"
        )
    return (
        "아래 키워드를 눌러 물어본 개념만 학습과 스테이지 성장에 반영되오. "
        "자유롭게 묻는 것도 얼마든지 환영하나, 학습 기록에는 남지 않으니 이 점 양해 바라오!"
    )


def suggested_concept_notice(term: str, tone: ChatTone) -> str:
    subject = with_korean_particle(term, "은/는")
    if tone == "modern":
        return f"{subject} 이번 스테이지에서 배우는 개념이에요. 학습으로 남기려면 아래 버튼을 눌러 시작해 보세요."
    return f"{subject} 이번 스테이지에서 배우는 개념이오. 학습으로 남기려면 아래 버튼을 눌러 시작해 보시오."
