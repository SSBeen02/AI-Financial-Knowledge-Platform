# 사전테스트 연동 계약

공유 API 및 DB 스키마 1004 수정안 기준. 학습·게임·캐릭터 데이터를 변경하지 않는다.

## 실행

Python 3.10 이상. `python -m pip install -r requirements.txt` 후 `.env.example`을 `.env`로 복사하고 `python -m uvicorn main:app --reload` 실행.
단독 개발: DEV_MODE=true, DIAGNOSTIC_REPOSITORY=memory, LLM_REPORT_MODE=local.
Gemini 확인: LLM_REPORT_MODE=gemini와 서버 GEMINI_API_KEY 설정. Gemini는 OpenAI 호환 API와 SDK의 beta.chat.completions.parse를 사용한다. timeout 60초, SDK 재시도 1회.
통합: DEV_MODE=false, DIAGNOSTIC_REPOSITORY=supabase, LLM_REPORT_MODE=gemini. 비밀키는 브라우저·Git에 전달하지 않는다.

## 공통 서버 등록

routers.diagnostics.router와 routers.reports.router를 통합 FastAPI 앱에 include_router한다.
`app.dependency_overrides[dependencies.get_current_user_id] = 공통_인증_함수`로 검증된 Supabase Auth UUID 문자열을 제공한다. 요청 본문 user_id는 금지. 공통 인증이 없고 DEV_MODE=false면 401.
main.py는 단독 개발 진입점이다. 통합 서버의 루트 화면, CORS, 인증, request_id 미들웨어, RequestValidationError 핸들러는 통합 담당자가 한 번 등록한다.
사전테스트 DiagnosticError 핸들러와 공통 code/message/request_id 규격을 통합 오류 처리에 연결한다. register_pretest_exception_handlers는 단독 앱용이다.
일반적인 database/services/schemas/dependencies 패키지 이름은 통합 저장소에 충돌이 없는지 확인하고 모듈 네임스페이스로 배치한다.

## API

- POST /diagnostics: 201. 본문 없음. id(UUID), user_id, status=pending, started_at, total_questions, questions 반환. questions의 id/domain/domain_label/category/difficulty/question/options만 공개한다. 정답·해설·개념명은 공개하지 않는다.
- POST /diagnostics/{id}/submit: `Idempotency-Key` 헤더 필수(1~128자, 공백만인 키 금지). 본문은 `{"answers":[{"question_id":"finance_investment_001","selected_answer":2}, ...]}`. 전체 문항을 한 번씩 제출하며 보기 번호는 1부터 시작한다. 본문에 키나 user_id를 넣지 않는다.
- 최초 접수: 202, id/report_id/user_id/status=processing/submitted_at/summary/domain_scores/question_results. 답안·채점 결과를 먼저 저장한 뒤 백그라운드에서 생성한다. 이 응답 후 프런트는 캐릭터 이름 설정 API를 독립적으로 호출할 수 있다.
- 같은 진단·키·답안 재요청: 기존 결과 반환. 처리 중 202, completed/failed는 200. 답안 순서는 무관. 다른 키나 답안은 409 IDEMPOTENCY_CONFLICT. 생성 작업은 다시 시작하지 않는다. 키는 진단별 범위다.
- GET /reports/{id}: 200. id=report_id=diagnostic_id. status는 pending/processing/completed/failed. 생성 전 필드는 생략 가능. 그래프는 domain_scores, 분석 문장은 llm_report. failed에도 채점 결과는 제공하며 error.code/message를 반환한다.
- 생성 실패 후 같은 제출은 실패 결과를 반환한다. 새 시도는 POST /diagnostics로 시작한다.

사용자 ID는 인증 UUID 문자열, 진단/리포트 ID는 UUID, 사전테스트 문항 ID는 문항 JSON의 문자열이다. concept는 표시용 개념명이며 sisa_* 개념 ID가 아니다. stage_id·개념 통과·학습 진행률과 연결하지 않는다.
시간은 서버 UTC ISO 8601. 점수는 0~100, 취약 기준은 70점 미만. 오류 응답은 code/message/request_id.

## 저장·장애

sql/diagnostic_attempts.sql은 팀 검토 후 공유 DB에 적용해야 한다. 새 컬럼 questions_snapshot/submission_key/error가 필요하다. 기존 pending 진단 중 문항 스냅샷이 없는 진단은 새로 시작해야 한다.
user_id는 현재 text이며 Auth UUID 문자열을 저장한다. auth.users 외래키·uuid 타입 변경은 임시 기록 정리 및 팀 DB 합의 후 별도 수행한다.
questions_snapshot은 서버 내부 정답을 포함하므로 직접 클라이언트 조회를 허용하지 않는다. 서비스 역할 키와 RLS를 유지한다.
조회는 개별 점수·LLM 컬럼이 기준이며 report 컬럼은 이전 데이터 읽기 호환용이다.
BackgroundTasks는 프로세스 내 작업이다. 서버 종료·저장 장애 뒤 processing이 남으면 제출 후 300초가 지난 조회에서 failed로 전환한다. 종료된 작업을 자동 재실행하지 않는다. 운영에서 자동 재실행이 필요하면 영속 작업 큐를 연결한다.
메모리 저장소는 재시작 시 데이터가 사라지므로 통합 시 Supabase를 사용한다.
