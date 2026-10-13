# 공유 API·DB 문서: Stage 5 수정본

Stage 5 문제·풀이 저장은 퀴즈 테이블로 통합한다. 담당은 박서현이다.

| 기존 항목 | 확정된 저장 위치·내용 |
|---|---|
| exam_questions | 별도 테이블 없음. 고정 210문제 원본은 stage5_questions.json, 사용자별 제공 세트는 quiz_sets에 stage_id=stage5로 저장 |
| exam_submissions | 별도 테이블 없음. 답안·문제별 정오답·정답 수·통과 판정은 quiz_submissions에 저장 |

학습 관리에는 report_quiz_result로 해당 세션의 concept_id, stage_id=stage5, correct_count, passed를 전달한다. 개념 상태·진행률·게임 이벤트는 학습 관리가 갱신한다. 동일 개념의 Stage 1~4 결과와 Stage 5 결과는 구분한다.

이 문서는 공유 문서에 반영할 수정본이다. 외부 공유 문서 원본을 직접 편집한 것은 아니다.
