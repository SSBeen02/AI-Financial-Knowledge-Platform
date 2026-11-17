# quiz-database 개선 기능의 DB 적용 절차

이 문서는 통합 브랜치의 SQL 적용 순서를 설명한다. 작성 과정에서 운영 DB를 변경하지 않았다.

## 적용 전 확인

1. 통합 서버가 연결하는 PostgreSQL의 백업과 복구 절차를 확인한다. `CHAT_DB_URL`과 `QUIZ_DATABASE_URL`이 가리키는 실제 DB 및 서버 로그인 역할을 확인한다. 연결 문자열과 비밀값은 기록하지 않는다.
2. `diagnostic_attempts`, `quiz_sets`, `quiz_submissions`, `quiz_reviews`의 현재 컬럼·제약·인덱스와 각 SQL의 차이를 확인한다. 이미 적용된 항목은 다시 만들 필요가 없다.
3. `quiz_submissions`에서 `quiz_set_id`별로 `count(*) > 1`인 행이 있는지 조회한다. 중복이 있으면 참조 중인 복습·학습·게임 기록을 먼저 검토한다. `quiz_002_first_submission.sql`은 중복 발견 시 실패하며 데이터를 삭제하지 않는다.
4. 통합 서버의 PostgreSQL 로그인 역할이 `public.start_diagnostic_once(jsonb)`를 실행할 수 있는지 확인한다. 이 함수는 기본적으로 `service_role`에만 실행 권한을 준다. 서버가 다른 역할을 쓰면 관리자가 해당 역할에만 실행 권한을 부여해야 한다.

## 적용 순서

1. `pretest-upload/sql/002_single_attempt_retry.sql`: 재시도 컬럼과 사용자별 최초 응시 재사용 함수.
2. `quiz-upload/sql/quiz_002_first_submission.sql`: 퀴즈 세트당 제출 1건 제약. 중복 데이터가 있으면 적용을 중단한다.
3. `quiz-upload/sql/quiz_004_reviews.sql`: 기존 DB에 `quiz_reviews`가 없는 경우의 복습 테이블.
4. `quiz-upload/sql/quiz_005_learning_note_indexes.sql`, `quiz-upload/sql/quiz_006_submission_indexes.sql`: 학습노트 조회 인덱스.
5. `quiz-upload/sql/quiz_003_client_access.sql`은 Supabase 클라이언트 권한을 사용하는 DB에서만 별도 검토 후 적용한다. 서버 로그인 역할의 테이블 접근 권한을 먼저 확인한다.

## 적용 후 확인

- 한 사용자가 `POST /diagnostics`를 두 번 호출했을 때 같은 응시 ID가 반환되고 두 번째 응답이 200인지 확인한다. `GET /diagnostics/current`와 제출 API의 기존 응답도 확인한다.
- 실패한 리포트만 `POST /reports/{id}/retry`로 다시 처리할 수 있고, 3회 제한 및 채점 결과 보존을 확인한다.
- 같은 퀴즈에 다른 멱등 키로 두 번 제출해도 최초 결과만 반환되는지 확인한다.
- 기존 `/api/v1/learning-notes`와 복습 API, 새 `/api/v1/learning-notes/concepts`를 같은 사용자 권한으로 조회한다.
- SQL 적용과 서비스 배포는 별도 승인 및 담당자의 실행 기록이 필요하다.
