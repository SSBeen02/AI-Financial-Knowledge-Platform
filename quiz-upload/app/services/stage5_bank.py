"""고정 문제 파일을 기존 퀴즈 3문항 저장 형식으로 변환한다."""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_bank():
    path = Path(__file__).resolve().parents[2] / "stage5_questions.json"
    return {item["concept_id"]: item["questions"] for item in json.loads(path.read_text(encoding="utf-8"))}


def fixed_questions(concept_id):
    questions = load_bank()[concept_id]
    return [
        dict(
            question_index=q["question_number"],
            question_type="ox" if q["question_type"] == "OX" else "situation",
            prompt=q["question"],
            choices=[dict(key=(text if q["question_type"] == "OX" else "ABCD"[i]), text=text)
                     for i, text in enumerate(q["options"])],
            answer=q["answer"], explanation=q["explanation"],
        ) for q in questions
    ]
