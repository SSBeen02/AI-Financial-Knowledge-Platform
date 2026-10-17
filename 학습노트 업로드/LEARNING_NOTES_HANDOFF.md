# 학습노트 API·인수인계 (2026-10-18)

담당: 박서현. 아래는 최신 코드 기준이다.

## 조회

GET /api/v1/learning-notes/concepts

- 쿼리: stage_id, concept_id(선택), filter=all|wrong|correct, page(1부터).
- 화면에서는 stage1~stage5 중 하나를 선택하고 기본 stage1로 요청한다. API는 stage_id 생략도 지원한다.
- 응답: items, total, page, page_size(20개 개념).
- items: concept_id, term, stage_ids, latest_at, questions 및 호환 필드 stage_id·concept_status.
- questions: quiz_set_id, submission_id, question_index, stage_id, concept_status, question_type, prompt, choices, submitted_answer, is_correct, answer, explanation, is_passed, created_at, reviews.
- 제출 기록만 조회한다. 문항 필터 후 concept_id로 그룹핑하고 그룹 단위로 페이지 처리한다. 한 개념의 탭을 페이지 중간에서 자르지 않는다.
- 같은 개념의 여러 제출을 모두 유지한다. 문항 식별은 submission_id + question_index다.
- 그룹의 단일 stage_id·concept_status는 최신 기록의 호환 필드다. 선택 문항의 stage_id·concept_status를 표시·동작에 사용한다.
- 현재 개념 상태 조회는 configure_learning_callbacks의 concept_status_reader 연결을 사용한다. 미연결이면 null이다.
- 기존 GET /api/v1/learning-notes는 문항 단위 호환 API다. all에는 미제출이 포함될 수 있으며 현재 화면은 이 API를 사용하지 않는다.

## 다시 풀기 및 저장

화면 이동: /quiz?mode=review&concept_id=...&stage_id=...&submission_id=...&question_index=...

POST /api/v1/learning-notes/submissions/{submission_id}/questions/{question_index}/reviews

```json
{"answer":"O","idempotency_key":"client-generated-unique-key"}
```

- answer는 해당 문항 보기의 key다. 사용자 ID는 인증 정보에서만 받는다.
- 응답: id, submitted_answer, is_correct, created_at.
- 본인 최초 제출의 문항인지 확인하고 quiz_reviews에 저장한다.
- 같은 사용자·키·입력 재요청은 기존 결과를 반환한다. 같은 키의 다른 입력은 409다. 소유하지 않은 원본은 404다.
- 복습은 최초 답안·정오답·정답 수·통과 여부를 변경하지 않으며 학습 결과 콜백·진행률·보상 처리를 하지 않는다.
- 복습 이력은 그룹 조회의 questions[].reviews에서 확인한다.

## 데이터 구조

quiz_sets 1:N quiz_submissions, quiz_submissions 1:N quiz_reviews.
학습노트 문제 내용을 복제하는 전용 테이블은 없다. quiz_reviews는 원본 제출·문항에 대한 복습 답안만 저장한다.

관련 SQL:
- sql/quiz_001_tables.sql: 퀴즈 세트·최초 제출
- sql/quiz_002_learning_note_indexes.sql: 학습노트 조회 인덱스
- sql/quiz_003_reviews.sql: 복습 이력 테이블·인덱스·RLS 활성화

## 통합 범위

기존 학습 관리 → 퀴즈 내부 연결은 app/services/team_quiz.py의 register_quiz_integration을 사용한다. 현재 개념 상태는 concept_status_reader를 통해 제공한다.
학습노트의 개념 다시 학습 기능은 제거되어 relearn API·handler·URL 설정이 없다.
DEV_MODE의 사용자 헤더는 단독 개발 전용이다. 운영 사용자 인증은 공통 인증 담당자가 연결한다. 직접 DB 연결 검증과 실제 로그인·RLS 역할 검증은 구분한다.

해설은 app/services/quiz_tone.py에서 하오체로 처리하며 신규 동적 퀴즈 프롬프트에도 동일 지침을 사용한다.
