# 사전테스트 연동 계약

공유 API 및 DB 스키마 1004 수정안 기준. 학습·게임·캐릭터 데이터를 변경하지 않는다.

## 실행

Python 3.10 이상. `python -m pip install -r requirements.txt` 후 `.env.example`을 `.env`로 복사하고 `python -m uvicorn main:app --reload` 실행.
단독 개발: DEV_MODE=true, DIAGNOSTIC_REPOSITORY=memory, LLM_REPORT_MODE=local.
OpenAI 사전테스트 리포트: LLM_REPORT_MODE=openai와 서버 OPENAI_API_KEY를 설정한다. OPENAI_MODEL을 사용하며 beta.chat.completions.parse로 구조화된 서술을 받는다. 총평 1개와 영역별 분석을 병렬 생성한다. LLM 예산은 최대 28초이고 SDK 자동 재시도는 없다. 개념 퀴즈의 호출 정책과는 구분한다.
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
BackgroundTasks는 프로세스 내 작업이다. 서버 종료·작업 유실로 processing이 남으면 제출 후 30초가 지난 조회에서 failed로 전환한다. 종료된 작업을 자동 재실행하지 않는다. 운영에서 자동 복구가 필요하면 영속 작업 큐를 연결한다.
메모리 저장소는 재시작 시 데이터가 사라지므로 통합 시 Supabase를 사용한다.

## 사전테스트 리포트 생성 시간·문체 (2026-10-06)

제출 후 completed까지의 목표는 30초이며 LLM 생성 예산은 최대 28초다. 제출 후 이미 경과한 시간을 고려해 남은 예산을 전달한다. 이는 성공 완료를 보장하는 SLA가 아니다. DB·큐 대기·외부 API 지연·다중 사용자 부하에 따라 failed가 발생할 수 있다.

OpenAI 분석은 총평과 네 영역을 동시에 수행한다. 모델은 설명만 생성하며 점수·등급·문항 ID·영역별 결과·우선순위는 기존 채점 결과에서 조립한다. 프로세스당 동시 OpenAI 요청은 최대 12개다. SDK 자동 재시도는 없고 시간 초과는 REPORT_GENERATION_TIMEOUT, 기타 생성 오류는 REPORT_GENERATION_FAILED로 처리한다. processing → completed/failed 흐름을 유지하고 실패해도 채점 결과를 보존한다. 공개 API 필드·DB 스키마는 변경하지 않는다.

리포트는 친절하고 현대적인 하오체로 작성한다. 학습 권장은 주제별 3~5문장 단일 문단이며 혼동 지점·개념 구분 기준·이후 학습 방향과 문제 접근 전략을 자연스럽게 연결한다. 태그·불렛·과도한 강조와 기계적 문구 반복은 피한다.

2026-10-06 실제 OpenAI API로 각 사례 10회씩 총 30회 순차 측정했다. 평균은 만점 7.717초, 부분 오답 14.174초, 전부 오답 15.621초이며 최댓값은 각각 9.524초, 16.271초, 17.776초다. 실패·30초 초과·채점 불일치는 0건이었다. 로컬 메모리 저장소에서 서비스 제출부터 저장·조회까지 측정했으며 HTTP 전송·브라우저 폴링·Supabase 지연·동시 사용자 부하는 포함하지 않았다. 동일 응답 반복에 대한 제한된 표본이며 향후 성능·품질 보장이 아니다.

배포 후 로그의 report_llm_task(API/대기 시간·토큰), report_llm_total(생성 합계), report_service_total(서비스 시간)을 관찰한다. 로그에 API 키나 답안 본문을 추가하지 않는다. 사용자별 지연과 성공률은 운영 환경에서 별도 검증한다.
