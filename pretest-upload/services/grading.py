from services.domains import (
    HIGH_SEVERITY_SCORE_THRESHOLD,
    VULNERABLE_SCORE_THRESHOLD,
    domain_label,
    format_score,
    level_for,
    percent_score,
    recommendation_for,
)


def grade_attempt(questions: list[dict], answers: dict[str, int]) -> dict:
    """문항 순서대로 채점하고 영역 점수와 취약점 목록을 만듭니다."""
    question_results: list[dict] = []
    domain_order: list[str] = []
    grouped: dict[str, list[dict]] = {}

    for question in questions:
        selected = answers[question["id"]]
        is_correct = selected == question["answer"]
        result = {
            "question_id": question["id"],
            "domain": question["domain"],
            "domain_label": domain_label(question["domain"]),
            "category": question["category"],
            "difficulty": question["difficulty"],
            "concept": question["concept"],
            "question": question["question"],
            "options": list(question["options"]),
            "selected_answer": selected,
            "correct_answer": question["answer"],
            "is_correct": is_correct,
            "explanation": {
                "correct": question["explanation"]["correct"],
                "options_detail": list(question["explanation"]["options_detail"]),
            },
        }
        question_results.append(result)
        if question["domain"] not in grouped:
            domain_order.append(question["domain"])
            grouped[question["domain"]] = []
        grouped[question["domain"]].append(result)

    order_index = {domain: index for index, domain in enumerate(domain_order)}
    domain_scores: list[dict] = []
    vulnerabilities: list[dict] = []

    for domain in domain_order:
        items = grouped[domain]
        total = len(items)
        correct_count = sum(1 for item in items if item["is_correct"])
        score = percent_score(correct_count, total)
        missed = [item for item in items if not item["is_correct"]]
        is_vulnerable = score < VULNERABLE_SCORE_THRESHOLD
        domain_scores.append(
            {
                "domain": domain,
                "domain_label": domain_label(domain),
                "total_questions": total,
                "correct_count": correct_count,
                "incorrect_count": total - correct_count,
                "score": score,
                "is_vulnerable": is_vulnerable,
            }
        )
        if is_vulnerable:
            missed_concepts = [item["concept"] for item in missed]
            vulnerabilities.append(
                {
                    "domain": domain,
                    "domain_label": domain_label(domain),
                    "score": score,
                    "correct_count": correct_count,
                    "total_questions": total,
                    "severity": "high" if score < HIGH_SEVERITY_SCORE_THRESHOLD else "medium",
                    "missed_concepts": missed_concepts,
                    "missed_question_ids": [item["question_id"] for item in missed],
                    "recommendation": recommendation_for(domain, missed_concepts),
                }
            )

    vulnerabilities.sort(key=lambda item: (item["score"], order_index[item["domain"]]))

    total_questions = len(question_results)
    correct_count = sum(1 for item in question_results if item["is_correct"])
    score = percent_score(correct_count, total_questions)
    weakest = (
        min(domain_scores, key=lambda item: (item["score"], order_index[item["domain"]]))
        if domain_scores
        else None
    )
    level = level_for(score)

    return {
        "summary": {
            "total_questions": total_questions,
            "correct_count": correct_count,
            "incorrect_count": total_questions - correct_count,
            "score": score,
            "level": level,
            "vulnerable_threshold": VULNERABLE_SCORE_THRESHOLD,
            "weakest_domain": None if weakest is None else weakest["domain"],
            "weakest_domain_label": None if weakest is None else weakest["domain_label"],
            "analysis": _build_analysis(correct_count, total_questions, score, level, vulnerabilities),
        },
        "domain_scores": domain_scores,
        "vulnerabilities": vulnerabilities,
        "question_results": question_results,
    }


def _build_analysis(
    correct: int,
    total: int,
    score: float,
    level: str,
    vulnerabilities: list[dict],
) -> str:
    summary = (
        f"전체 {total}문항 중 {correct}문항을 맞혀 {format_score(score)}점, {level} 수준입니다."
    )
    if not vulnerabilities:
        return summary + f" 모든 영역이 {format_score(VULNERABLE_SCORE_THRESHOLD)}점 이상이라 두드러진 취약 영역은 없습니다."

    weak = ", ".join(
        f"{item['domain_label']} {format_score(item['score'])}점" for item in vulnerabilities
    )
    concepts: list[str] = []
    for item in vulnerabilities:
        for concept in item["missed_concepts"]:
            if concept not in concepts:
                concepts.append(concept)
    highlighted = ", ".join(concepts[:5])
    concept_sentence = f" 우선 확인할 개념은 {highlighted}입니다." if highlighted else ""
    return f"{summary} 취약 영역은 {weak}입니다.{concept_sentence}"
