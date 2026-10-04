import json
import threading
from pathlib import Path

QUESTION_FILE = Path(__file__).resolve().parent.parent / "data" / "pretest_questions_v2.json"
REQUIRED_FIELDS = {
    "id",
    "domain",
    "category",
    "difficulty",
    "concept",
    "question",
    "options",
    "answer",
    "explanation",
}

_questions: list[dict] | None = None
_lock = threading.Lock()


class QuestionBankError(RuntimeError):
    pass


def load_questions() -> list[dict]:
    global _questions
    if _questions is not None:
        return _questions
    with _lock:
        if _questions is None:
            _questions = _read_questions(QUESTION_FILE)
        return _questions


def count_by_domain(questions: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for question in questions:
        domain = question["domain"]
        counts[domain] = counts.get(domain, 0) + 1
    return counts


def _read_questions(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise QuestionBankError(f"문항 파일을 찾을 수 없습니다: {path}") from exc
    except json.JSONDecodeError as exc:
        raise QuestionBankError(f"문항 JSON을 읽지 못했습니다: {path}") from exc

    questions = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(questions, list) or not questions:
        raise QuestionBankError("문항 파일에 questions 배열이 없습니다.")

    seen: set[str] = set()
    for index, question in enumerate(questions, start=1):
        _validate_question(index, question, seen)
    return questions


def _validate_question(index: int, question: dict, seen: set[str]) -> None:
    if not isinstance(question, dict):
        raise QuestionBankError(f"{index}번 문항 형식이 올바르지 않습니다.")
    missing = REQUIRED_FIELDS - question.keys()
    if missing:
        raise QuestionBankError(f"{index}번 문항에 필드가 없습니다: {sorted(missing)}")

    question_id = question["id"]
    if not isinstance(question_id, str) or not question_id:
        raise QuestionBankError(f"{index}번 문항 id가 올바르지 않습니다.")
    if question_id in seen:
        raise QuestionBankError(f"중복 문항 id: {question_id}")
    seen.add(question_id)

    for field in ("domain", "category", "concept", "question"):
        if not isinstance(question[field], str) or not question[field].strip():
            raise QuestionBankError(f"{question_id}의 {field} 값이 올바르지 않습니다.")

    if isinstance(question["difficulty"], bool) or not isinstance(question["difficulty"], int):
        raise QuestionBankError(f"{question_id}의 난이도가 올바르지 않습니다.")

    options = question["options"]
    if not isinstance(options, list) or not options or not all(isinstance(item, str) and item for item in options):
        raise QuestionBankError(f"{question_id}의 보기가 올바르지 않습니다.")

    answer = question["answer"]
    if isinstance(answer, bool) or not isinstance(answer, int) or not 1 <= answer <= len(options):
        raise QuestionBankError(f"{question_id}의 정답 번호가 올바르지 않습니다.")

    explanation = question["explanation"]
    if (
        not isinstance(explanation, dict)
        or not isinstance(explanation.get("correct"), str)
        or not explanation["correct"].strip()
        or not isinstance(explanation.get("options_detail"), list)
        or len(explanation["options_detail"]) != len(options)
        or not all(isinstance(item, str) and item.strip() for item in explanation["options_detail"])
    ):
        raise QuestionBankError(f"{question_id}의 해설이 올바르지 않습니다.")
